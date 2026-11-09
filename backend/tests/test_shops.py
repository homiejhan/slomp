"""Every store in an area and the sales its own site states (sources/shops.py, local.site_deals, site.site_ads)."""
import asyncio
import json
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from slomp.config import Settings
from slomp.db import Store as DB
from slomp.http import Blocked, PoliteClient, Response, cache_key
from slomp.local import SITE_DAYS, LocalDeals, site_deals, site_merchant
from slomp.sources.shops import (ShopSite, ShopSites, SiteItem, SiteRead, host_of, parse_map, platform_of,
                                 shopify_items, woo_items)

NOW = datetime(2026, 11, 9, 18, tzinfo=timezone.utc)          # Monday noon in Texas


def _shop(i, kind, website, lat=30.27, lon=-97.74, name="Bike Shed", typ="node", **tags):
    return {"type": typ, "id": i, **({"lat": lat, "lon": lon} if typ == "node" else {"center": {"lat": lat, "lon": lon}}),
            "tags": {"shop": kind, "name": name, "website": website, "addr:housenumber": "12",
                     "addr:street": "Main St", "addr:city": "Austin", **tags}}


MAP = {"elements": [
    _shop(1, "bicycle", "https://www.bikeshed.example/"),
    _shop(2, "bicycle", "https://bikeshed.example", typ="way"),                 # its building: the same shop
    _shop(3, "bicycle", "bikeshed.example/locations/north", lat=30.40, lon=-97.70, name="Bike Shed North"),
    _shop(4, "clothes", "https://www.facebook.com/somestore", name="Some Store"),   # not the shop's own site
    _shop(5, "supermarket", "https://www.heb.com/heb-store/US/tx/austin", name="H-E-B"),   # on Flipp: read there
    _shop(6, "hairdresser", "https://cuts.example", name="Cuts"),               # a service, not goods
    _shop(7, "furniture", "http://Sofa-Town.example:8080/home", lat=29.42, lon=-98.49, name="Sofa Town"),
]}


def test_the_map_gives_one_site_per_store_with_its_shops():
    sites = parse_map(MAP)
    assert sorted(sites) == ["bikeshed.example", "sofa-town.example"]
    bike = sites["bikeshed.example"]
    assert (bike.name, bike.kinds, bike.industries) == ("Bike Shed", ("bicycle",), ("sports",))
    assert [r[2:] for r in bike.locations] == [["Bike Shed", "12 Main St, Austin", "osm:node/1"],
                                              ["Bike Shed North", "12 Main St, Austin", "osm:node/3"]]
    assert bike.key < 0 and bike.key == ShopSite("bikeshed.example", "", (), ()).key
    assert host_of("WWW.Example.com/a") == "example.com" and host_of("") == host_of("not a site") == ""


def test_a_site_says_which_platform_it_runs_on():
    assert platform_of('<script src="//cdn.shopify.com/s/files/1/theme.js"></script>') == "shopify"
    assert platform_of('<body class="home woocommerce-page">') == "woocommerce"
    assert platform_of("<html><body>Just a page</body></html>") == ""


SHOPIFY = {"products": [
    {"title": "Trail Helmet", "handle": "trail-helmet", "product_type": "Helmets", "tags": ["MTB", "Safety"],
     "images": [{"src": "https://cdn.example/helmet.jpg"}],
     "variants": [{"price": "59.99", "compare_at_price": "89.99", "available": True},
                  {"price": "64.99", "compare_at_price": "89.99", "available": True}]},
    {"title": "Tube", "handle": "tube", "variants": [{"price": "8.00", "compare_at_price": None}]},
    {"title": "Gloves", "handle": "gloves", "tags": "Apparel, Winter",
     "variants": [{"price": "20.00", "compare_at_price": "40.00", "available": False},
                  {"price": "30.00", "compare_at_price": "40.00", "available": True},
                  {"price": "40.00", "compare_at_price": None, "available": True}]},
]}
WOO = [
    {"name": "Velvet Sofa &amp; Ottoman", "permalink": "https://sofa-town.example/p/velvet",
     "prices": {"price": "79900", "regular_price": "119900", "sale_price": "79900", "currency_code": "USD",
                "currency_minor_unit": 2}, "categories": [{"name": "Sofas"}], "images": [{"src": "https://x/s.jpg"}]},
    {"name": "Lamp", "permalink": "https://sofa-town.example/p/lamp",
     "prices": {"price": "5000", "regular_price": "5000", "currency_code": "USD", "currency_minor_unit": 2}},
    {"name": "Rug", "prices": {"price": "100", "regular_price": "200", "currency_code": "CAD", "currency_minor_unit": 0}},
]


def test_a_shops_products_on_sale_with_the_price_they_were():
    helmet, gloves = shopify_items(SHOPIFY, "bikeshed.example")
    assert (helmet.title, helmet.price, helmet.regular, helmet.basis, helmet.pct) == \
        ("Trail Helmet", 59.99, 89.99, "list", 33.3)
    assert helmet.url == "https://bikeshed.example/products/trail-helmet" and not helmet.options
    assert helmet.words == "Helmets MTB Safety" and helmet.image == "https://cdn.example/helmet.jpg"
    assert (gloves.price, gloves.regular, gloves.options) == (30.0, 40.0, True)     # the sold-out size isn't counted
    sofa, = woo_items(WOO, "sofa-town.example")
    assert (sofa.title, sofa.price, sofa.regular, sofa.basis, sofa.words) == \
        ("Velvet Sofa & Ottoman", 799.0, 1199.0, "store_regular", "Sofas")


class _Net:
    """A PoliteClient whose network is a dict: URL (with its query) -> body, a status, or an exception."""

    def __init__(self, tmp_path, pages):
        self.client = PoliteClient(DB(tmp_path / "c.db"), Settings(cache_dir=tmp_path))
        self.pages, self.calls = pages, []

        async def fetch(url, params, headers, html, timeout_s):
            key = cache_key(url, params)
            self.calls.append(key)
            got = self.pages.get(key, 404)
            if isinstance(got, Exception):
                raise got
            status, body = (got, b"") if isinstance(got, int) else (200, got.encode() if isinstance(got, str)
                                                                         else json.dumps(got).encode())
            return Response(key, key, status, "", body, time.time())
        self.client._fetch = fetch


def _pages():
    return {"https://bikeshed.example/robots.txt": "User-agent: *\nDisallow: /cart",
            "https://bikeshed.example/": '<link href="//cdn.shopify.com/x.css">',
            "https://bikeshed.example/products.json?limit=250&page=1": SHOPIFY,
            "https://sofa-town.example/robots.txt": "",
            "https://sofa-town.example/": '<link href="/wp-content/plugins/woocommerce/x.css">',
            "https://sofa-town.example/wp-json/wc/store/v1/products?on_sale=true&page=1&per_page=100": 404,
            "https://sofa-town.example/wp-json/wc/store/products?on_sale=true&page=1&per_page=100": WOO,
            "https://walled.example/robots.txt": "",
            "https://walled.example/": Blocked("https://walled.example/", "the site served a bot check"),
            "https://private.example/robots.txt": "User-agent: *\nDisallow: /"}


def test_reading_a_sites_sales_on_each_platform_and_what_stops_it(tmp_path):
    net = _Net(tmp_path, _pages())
    sh = ShopSites(net.client)
    site = lambda host: ShopSite(host, host, ("bicycle",), ("sports",), [[30.27, -97.74, "", "", "osm:node/1"]])  # noqa
    reads = asyncio.run(sh.read_all([site(h) for h in ("bikeshed.example", "sofa-town.example", "walled.example",
                                                       "private.example")], budget=10))
    assert reads["bikeshed.example"].platform == "shopify" and len(reads["bikeshed.example"].items) == 2
    assert reads["sofa-town.example"].platform == "woocommerce" and reads["sofa-town.example"].items[0].price == 799.0
    assert reads["walled.example"].note == "the site answered with a bot check"
    assert reads["private.example"].note == "disallowed by robots.txt"
    assert all(r.charged for r in reads.values()) and sh.budget == 6
    # the cache keeps what the pages said, not the pages: the platform, and the products on sale
    store = net.client.store
    assert store.cache_get("https://bikeshed.example/").body == b"<!-- slomp: the site runs on shopify -->"
    kept = json.loads(store.cache_get("https://bikeshed.example/products.json?limit=250&page=1").body)
    assert kept["_count"] == 3 and [p["title"] for p in kept["products"]] == ["Trail Helmet", "Gloves"]
    # read again: all cached, nothing spent
    again = asyncio.run(sh.read_all([site("bikeshed.example")], budget=0))
    assert len(again["bikeshed.example"].items) == 2 and not again["bikeshed.example"].charged
    # a site not read yet waits when the build's reads are spent
    assert asyncio.run(sh.read_all([site("new.example")], budget=0))["new.example"].note.startswith("not read yet")


def _read(items, at=NOW):
    return SiteRead(platform="shopify", items=items, read_at=at.timestamp())


def test_a_stores_sale_items_become_its_deals():
    bike = ShopSite("bikeshed.example", "Bike Shed", ("bicycle",), ("sports",), [[30.27, -97.74, "Bike Shed", "", "r"]])
    items = [SiteItem("Trail Helmet", 59.99, 89.99, "list", "https://bikeshed.example/products/a", words="Helmets"),
             SiteItem("Trail Helmet", 61.99, 89.99, "list", "https://bikeshed.example/products/b"),   # same product
             SiteItem("Chain Lube", 9.50, 10.00, "list", "https://bikeshed.example/products/lube"),   # 5%: too little
             SiteItem("Gift Card", 1.0, 100.0, "list", "https://bikeshed.example/products/gc"),        # 99%: not a price
             SiteItem("Rain Jacket", 45.0, 90.0, "list", "https://bikeshed.example/products/jacket", options=True)]
    deals = site_deals(bike, _read(items))
    assert [d.title for d in deals] == ["Rain Jacket", "Trail Helmet"]
    jacket, helmet = deals
    # a bike shop's jacket is cycling gear: what the store sells decides what its words leave open
    assert jacket.industries == ["sports"] and helmet.industries == ["sports"]
    assert jacket.terms.conditions == ["price on the store's website", "some sizes or colors only"]
    assert (helmet.terms.basis, helmet.terms.savings, helmet.terms.pct) == ("list", 30.0, 33.3)
    assert helmet.id.startswith("site:") and helmet.flyer_id == bike.key and helmet.detailed
    assert helmet.source_url == helmet.retailer_url == "https://bikeshed.example/products/a"
    # shown on the day it was read and the next, as an ad states its days
    assert helmet.valid_from.isoformat() == "2026-11-09T00:00:00-06:00"
    assert helmet.valid_to.isoformat() == "2026-11-10T23:59:59-06:00" and SITE_DAYS == 2
    # a store named like a chain in the registry is told apart by its site
    assert site_merchant(ShopSite("target-feed.example", "Target", ("variety_store",), ("home",))).name == \
        "Target (target-feed.example)"
    assert site_deals(bike, SiteRead()) == [] and site_deals(bike, None) == []


class _Shops:
    """ShopSites with a fixed map and reads."""

    def __init__(self, sites, reads):
        self.sites, self.reads, self.budget = sites, reads, 0

    async def directory(self):
        return self.sites, ""

    async def read_all(self, sites, budget=None, at_once=24):
        return {s.host: self.reads[s.host] for s in sites if s.host in self.reads}


class _NoAds:
    async def flyers(self, zip_code):
        return []


def _two_stores():
    bike = ShopSite("bikeshed.example", "Bike Shed", ("bicycle",), ("sports",),
                    [[30.2672, -97.7431, "Bike Shed", "12 Main St, Austin", "osm:node/1"]])
    far = ShopSite("faraway.example", "Far Away", ("toys",), ("toys",),
                   [[31.7619, -106.4850, "Far Away", "1 Sun St, El Paso", "osm:node/2"]])
    reads = {"bikeshed.example": _read([SiteItem("Trail Helmet", 59.99, 89.99, "list", "https://bikeshed.example/p/h")]),
             "faraway.example": _read([SiteItem("Kite", 5.0, 10.0, "list", "https://faraway.example/p/k")])}
    return {s.host: s for s in (bike, far)}, reads


def test_the_server_search_shows_the_sales_of_stores_nearby(tmp_path):
    from slomp.reference import city
    from slomp.sources.stores import StoreLocator
    sites, reads = _two_stores()
    ld = LocalDeals(_NoAds(), StoreLocator(), _Shops(sites, reads))
    res = asyncio.run(ld.run(city("austin"), ["sports", "toys"], radius_mi=10, now=NOW))
    helmet, = res.deals
    assert (helmet.id[:5], helmet.merchant, helmet.store.name, helmet.store_status) == \
        ("site:", "Bike Shed", "Bike Shed", "nearby")
    assert helmet.store.distance_mi < 10 and helmet.valid_to.isoformat() == "2026-11-10T23:59:59-06:00"
    assert {"name": "Stores' own websites", "ok": True, "sites": 2} in res.sources


needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="Node isn't installed")
STATIC = Path(__file__).resolve().parents[1] / "slomp" / "static"


@needs_node
def test_the_published_page_shows_a_stores_sales_as_the_server_does(tmp_path):
    from slomp.reference import city
    from slomp.site import Ads, ad_files, site_ads, store_file
    from slomp.sources.stores import StoreLocator
    sites, reads = _two_stores()
    austin = city("austin")
    ads = Ads(NOW, NOW)
    ads.at = {"austin": []}
    lines = []
    asyncio.run(site_ads(SimpleNamespace(shops=_Shops(sites, reads)), ads, [austin], lines.append))
    assert ads.at["austin"] == [sites["bikeshed.example"].key]            # El Paso's store is too far from Austin
    assert lines[0].startswith("stores' own sites: 2 shops on the map with a website, 2 sites; read 2")
    files = ad_files(ads)
    row, = files[f"ads/{sites['bikeshed.example'].key}.json"]["deals"]
    assert row["source_url"] == "https://bikeshed.example/p/h" and row["dk"].startswith("Bike Shed|")
    assert store_file(ads)["merchants"]["Bike Shed"][0][2] == "Bike Shed"
    # the page's engine, on the files the build wrote
    site = tmp_path / "site"
    (site / "data" / "ads").mkdir(parents=True)
    shutil.copy(STATIC / "engine.js", site / "engine.js")
    meta = {"built": NOW.isoformat(), "radii_mi": [10, 25, 50], "anchors": {"austin": {"name": "Austin", "zip": "78701"}},
            "industries": [{"id": "sports", "name": "Sports", "description": "", "online": True}],
            "cities": [{"id": "austin", "name": "Austin", "county": "Travis", "population": 1, "zip": austin.zip,
                        "kind": "city", "lat": austin.lat, "lon": austin.lon, "tz": austin.tz, "anchor": "austin",
                        "anchor_mi": 0.0}]}
    others = {"meta.json": meta, "stores.json": store_file(ads), "promos.json": {"excluded": {}, "sources": [],
              "chains": {}, "items": []}, "regulars.json": {"excluded": {}, "sources": [], "chains": {}, "regulars": []}}
    for rel, content in {**files, **others}.items():
        (site / "data" / rel).write_text(json.dumps(content, default=str))
    driver = ("const fs=require('fs'),path=require('path');const [s]=process.argv.slice(1);"
              "const e=require(path.join(s,'engine.js'));"
              "e.configure({loader:p=>Promise.resolve(JSON.parse(fs.readFileSync(path.join(s,'data',p),'utf8')))});"
              f"e.search({{city:'austin',industries:'sports',radius_mi:10,now:'{NOW.isoformat()}'}})"
              ".then(r=>process.stdout.write(JSON.stringify(r.local)))")
    page = json.loads(subprocess.run(["node", "-e", driver, str(site)], capture_output=True, text=True,
                                     check=True).stdout)
    server = asyncio.run(LocalDeals(_NoAds(), StoreLocator(), _Shops(sites, reads)).run(
        austin, ["sports"], radius_mi=10, now=NOW))
    pd, = page["deals"]
    sd, = server.deals
    assert pd["id"] == sd.id and pd["source_url"] == sd.source_url and pd["store"]["name"] == sd.store.name
    assert pd["store"]["distance_mi"] == sd.store.distance_mi and pd["score"] == sd.score
    assert pd["valid_from"] == sd.valid_from.isoformat() and pd["valid_to"] == sd.valid_to.isoformat()
    assert {"name": "Stores' own websites", "ok": True, "sites": 1} in page["sources"]


def test_a_merchant_with_a_flipp_ad_and_no_mapped_stores_is_placed_by_its_name():
    from slomp.reference import city, merchant as merchant_entry
    from slomp.site import Ads, site_ads, store_file
    sites, reads = _two_stores()
    sites["faraway.example"].name = "Far Away Market"
    ads = Ads(NOW, NOW)
    ads.at = {"austin": []}
    ads.entries["Far Away Market"] = merchant_entry("Far Away Market")        # not in the store registry's map
    lines = []
    asyncio.run(site_ads(SimpleNamespace(shops=_Shops(sites, {"bikeshed.example": reads["bikeshed.example"]})), ads,
                         [city("austin")], lines.append))
    assert store_file(ads)["merchants"]["Far Away Market"][0][3] == "1 Sun St, El Paso"
    assert lines[-1] == "  merchants with a Flipp ad placed on the map by name: Far Away Market"
