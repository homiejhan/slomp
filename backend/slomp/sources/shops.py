"""Every store in an area, and the sales each one's own website states.

Flipp carries the weekly ads of the chains that publish one there; a store that doesn't is not there at all. So every
shop in Texas that gives a website is taken from OpenStreetMap (one Overpass query, read again weekly, so a store
that opens or gets mapped shows up by itself), and each one's own site is read for what it puts on sale.

A shop's site says what is on sale, in a form a reader can trust, when it runs on one of the shop platforms that
publish every product with its price and the price it was before:

  Shopify       /products.json: each variant's price and "compare at" price (a price the shop compares with: the
                deal's basis is "list")
  WooCommerce   /wp-json/wc/store/v1/products?on_sale=true: each product's price and its regular price ("store
                regular")

A site on neither is noted and left. The chains on Flipp, and the online stores whose sales the deal sites post, are
read there, not here. robots.txt is honored and a bot check is never worked around. A build reads at most
SITES_PER_BUILD sites over the network: the shop platforms' products first (they are read daily), then sites never
read, then second looks at sites that had nothing or could not be read. What a site said is remembered, a failure
included, so it is not asked again by every build; a store waiting its turn keeps its last deals until they lapse.
"""
from __future__ import annotations

import asyncio
import hashlib
import html as htmllib
import json
import re
import time
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Iterable, Optional
from urllib.parse import urlsplit

from ..config import DAY
from ..db import CachedResponse
from ..geo import miles
from ..http import Blocked, Disallowed, FetchError, PoliteClient, cache_key
from ..reference import fold, merchants, norm
from ..stores_online import registry
from ..terms import clean

OVERPASS = ("https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter")
# The Overpass servers turn away a client whose User-Agent doesn't name its application: overpass-api.de answered a
# browser-like one with HTTP 406 (run 125, Nov 9, 2026), and its operator's terms ask for the application's name.
OVERPASS_HEADERS = {"User-Agent": "Slomp/1.0 (deals near Texas cities; +https://github.com/homiejhan/slomp)",
                    "Accept": "application/json, */*"}
QUERY = """[out:json][timeout:900];
area["ISO3166-2"="US-TX"]->.tx;
(nwr["shop"]["website"](area.tx);nwr["shop"]["contact:website"](area.tx););
out center tags;"""
MAP_TTL = 7 * DAY            # the shops on the map
RECORD_TTL = 30 * DAY        # which platform a shop's site runs on: looked at again after this long, or longer (_spread)
FAILED_TTL = 14 * DAY        # a site behind a bot check or robots.txt, or with no page at its address: tried again then
ERROR_TTL = 3 * DAY          # a site that did not answer, or answered with an error
PRODUCTS_FAILED_TTL = 7 * DAY   # a shop platform whose product listing is closed
ITEMS_TTL = DAY              # what it has on sale
SITES_PER_BUILD = 600        # sites read over the network in one build, at most
PLATFORMS = ("shopify", "woocommerce")
WOO_PATHS = ("/wp-json/wc/store/v1/products", "/wp-json/wc/store/products")
NOT_YET = "not read yet: this build's reads were spent"
SHOPIFY_PAGES = 4            # of 250 products each
WOO_PAGES = 3                # of 100 products on sale each
MIN_PCT = 10.0               # a smaller saving on a shop's site is not shown
PER_SITE = 12                # deals kept from one site: its biggest savings

# The kinds of shop OpenStreetMap distinguishes (its `shop` key), and what each sells, in Slomp's industries. A kind
# not listed sells a service or nothing Slomp covers (hairdresser, car dealer, tattoo, pawnbroker, vape).
SHOP_INDUSTRIES: dict[str, tuple[str, ...]] = {
    "supermarket": ("grocery",), "convenience": ("grocery",), "greengrocer": ("grocery",), "butcher": ("grocery",),
    "seafood": ("grocery",), "deli": ("grocery",), "cheese": ("grocery",), "alcohol": ("grocery",),
    "wine": ("grocery",), "beverages": ("grocery",), "frozen_food": ("grocery",), "spices": ("grocery",),
    "tea": ("grocery",), "coffee": ("grocery",), "chocolate": ("grocery",), "confectionery": ("grocery",),
    "health_food": ("grocery", "health"), "farm": ("grocery", "home"), "wholesale": ("grocery", "home"),
    "general": ("home",), "variety_store": ("home", "grocery"), "department_store": ("fashion", "home"),
    "clothes": ("fashion",), "shoes": ("fashion",), "boutique": ("fashion",), "fashion_accessories": ("fashion",),
    "bag": ("fashion",), "jewelry": ("fashion",), "watches": ("fashion",), "leather": ("fashion",),
    "second_hand": ("fashion", "home"), "charity": ("fashion", "home"),
    "furniture": ("home",), "bed": ("home",), "kitchen": ("home",), "houseware": ("home",),
    "interior_decoration": ("home",), "lighting": ("home",), "carpet": ("home",), "curtain": ("home",),
    "bathroom_furnishing": ("home",), "doityourself": ("home",), "hardware": ("home",), "trade": ("home",),
    "paint": ("home",), "garden_centre": ("home",), "florist": ("home",), "appliance": ("home",),
    "electrical": ("home",), "flooring": ("home",), "tiles": ("home",), "candles": ("home",), "frame": ("home",),
    "pottery": ("home",), "antiques": ("home",), "agrarian": ("home",), "country_store": ("home",),
    "swimming_pool": ("home",), "gift": ("home",), "glaziery": ("home",),
    "electronics": ("tech",), "computer": ("tech",), "hifi": ("tech",), "video_games": ("tech", "toys"),
    "camera": ("tech",), "printer_ink": ("tech", "office"), "music": ("tech",),
    "sports": ("sports",), "outdoor": ("sports",), "bicycle": ("sports",), "fishing": ("sports",),
    "hunting": ("sports",), "weapons": ("sports",), "golf": ("sports",), "ski": ("sports",),
    "scuba_diving": ("sports",), "surf": ("sports",), "water_sports": ("sports",), "fitness": ("sports",),
    "cosmetics": ("beauty",), "perfumery": ("beauty",), "chemist": ("health", "beauty"),
    "medical_supply": ("health",), "nutrition_supplements": ("health",), "herbalist": ("health",),
    "toys": ("toys",), "games": ("toys",), "model": ("toys",), "craft": ("toys",), "art": ("toys", "home"),
    "musical_instrument": ("toys",), "anime": ("toys",), "collector": ("toys",), "party": ("toys",),
    "fabric": ("toys",), "sewing": ("toys",), "hobby": ("toys",),
    "baby_goods": ("baby",), "pet": ("pets",), "animal_feed": ("pets",),
    "car_parts": ("auto",), "stationery": ("office",), "books": ("office",),
}
# Where a shop's "website" is a page on a site that is not the shop's own.
_NOT_A_SHOP_SITE = re.compile(r"(?:^|\.)(?:facebook|instagram|twitter|x|tiktok|youtube|linkedin|pinterest|yelp|google|"
                              r"goo|g|business|linktr|linktree|bit|tinyurl|etsy|amazon|ebay|square|squareup|"
                              r"doordash|ubereats|grubhub|nextdoor|mapquest|foursquare|tripadvisor|wix|wixsite|godaddysites|"
                              r"sites|weebly|blogspot|wordpress)\.(?:com|ee|ly|gl|page|site|co|net|org)$", re.I)
_SHOPIFY = re.compile(r"cdn\.shopify\.com|\bShopify\.shop\s*=|\.myshopify\.com|shopify-section", re.I)
_WOO = re.compile(r"/wp-content/plugins/woocommerce|\bwoocommerce(?:-page|-active|_params)?\b|wc-block-", re.I)
# What the response cache keeps of a shop's site: which platform it runs on (and, for WooCommerce, which listing
# answered), or why it could not be read; not the page (see ShopSites._remember).
_KEPT = re.compile(r"^<!-- slomp: the site runs on ?(\w*) ?(\S*) -->")
_KEPT_FAILED = re.compile(r"^<!-- slomp: not read: (.*) -->", re.S)


def host_of(url: str) -> str:
    """The site a website tag names, as compared: lower case, no "www.", no port."""
    u = (url or "").strip().split(";")[0].strip()
    if not u:
        return ""
    if not re.match(r"https?://", u, re.I):
        u = "http://" + u
    host = (urlsplit(u).hostname or "").lower()
    return host.removeprefix("www.") if "." in host else ""


@lru_cache(maxsize=1)
def covered_hosts() -> frozenset[str]:
    """The sites of the chains whose deals come from Flipp and of the online stores whose sales come from the deal
    sites: read there, not here."""
    out = set()
    for m in merchants():
        out.update(d.lower().removeprefix("www.") for d in m.domains)
    for s in registry():
        out.update(d.lower().removeprefix("www.") for d in s.domains)
    return frozenset(out)


def _covered(host: str) -> bool:
    return any(host == d or host.endswith("." + d) for d in covered_hosts())


_NAME_FILLER = frozenset("the and shop shops store stores company inc llc ltd market supply supplies outlet center "
                         "centre co".split())
_GENERIC_LABELS = frozenset("www shop store stores online us com net org co biz info".split())


def own_site(host: str, names: Iterable[str]) -> bool:
    """Whether a website is the shop's own: its address carries the shop's name, run together ("REI" -> rei.com) or
    by a word of it ("Bomb City Safes" -> bombcitysafes.com). A shop tagged with the site of a brand it sells
    ("Barrels and Bullets" -> henryusa.com, the rifle maker's) is not read as if the brand's prices were the shop's."""
    labels = [x.replace("-", "") for x in host.split(".")[:-1] if x not in _GENERIC_LABELS]
    if not labels:
        return False
    for name in names:
        whole = fold(name)
        words = [w for w in re.findall(r"[a-z0-9]+", fold_words(name)) if len(w) >= 4 and w not in _NAME_FILLER]
        if any(whole and (whole == lab or (len(whole) >= 4 and (whole in lab or lab in whole))) for lab in labels) or \
                any(w in lab for w in words for lab in labels):
            return True
    return False


def fold_words(text: str) -> str:
    """Lower case, accents removed, words kept apart (`fold` runs them together)."""
    plain = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", plain.replace("&", " and "))


def address(tags: dict) -> str:
    street = " ".join(x for x in (tags.get("addr:housenumber"), tags.get("addr:street")) if x)
    return ", ".join(x for x in (street, tags.get("addr:city", "")) if x)


@dataclass
class ShopSite:
    host: str
    name: str
    kinds: tuple[str, ...]
    industries: tuple[str, ...]
    locations: list[list] = field(default_factory=list)      # rows of [lat, lon, name, address, ref]

    @property
    def url(self) -> str:
        return f"https://{self.host}/"

    @property
    def key(self) -> int:
        """A stable number for the site, negative so it never meets a Flipp ad's id."""
        return -int(hashlib.sha1(self.host.encode()).hexdigest()[:12], 16)

    def nearest(self, lat: float, lon: float) -> tuple[Optional[list], float]:
        best, d = None, float("inf")
        for row in self.locations:
            x = miles(lat, lon, row[0], row[1])
            if x < d:
                best, d = row, x
        return best, d


def parse_map(data: dict) -> dict[str, ShopSite]:
    """The Overpass answer, as one entry per site: the shops that give it, where each is, and what they sell."""
    sites: dict[str, ShopSite] = {}
    names: dict[str, Counter] = {}
    seen: set = set()
    for el in data.get("elements") or []:
        tags = el.get("tags") or {}
        kind = tags.get("shop", "")
        inds = SHOP_INDUSTRIES.get(kind)
        host = host_of(tags.get("website") or tags.get("contact:website") or "")
        if not inds or not host or _NOT_A_SHOP_SITE.search(host) or _covered(host):
            continue
        lat, lon = (el.get("lat"), el.get("lon")) if "lat" in el else ((el.get("center") or {}).get("lat"),
                                                                       (el.get("center") or {}).get("lon"))
        if lat is None or lon is None:
            continue
        place = (host, round(lat * 500), round(lon * 500))          # a shop's node and its building: one shop
        if place in seen:
            continue
        seen.add(place)
        name = clean(tags.get("name") or tags.get("brand") or "")
        s = sites.get(host)
        if s is None:
            s = sites[host] = ShopSite(host, "", (), ())
            names[host] = Counter()
        if kind not in s.kinds:
            s.kinds += (kind,)
            s.industries += tuple(i for i in inds if i not in s.industries)
        names[host][tags.get("brand") or name] += 1
        s.locations.append([round(lat, 6), round(lon, 6), name, address(tags), f"osm:{el.get('type')}/{el.get('id')}"])
    for host, s in sites.items():
        s.name = (names[host].most_common(1)[0][0] if names[host] else "") or host
    return {h: s for h, s in sites.items() if own_site(h, list(names[h]) or [s.name])}


@dataclass
class SiteItem:
    """One product a shop's site has on sale."""
    title: str
    price: float
    regular: float
    basis: str                     # "list" (Shopify's compare-at price) or "store_regular" (WooCommerce's regular)
    url: str
    image: str = ""
    words: str = ""                # the product's own type, tags or categories
    options: bool = False          # only some of its options (sizes, colors) are at this price

    @property
    def pct(self) -> float:
        return round(100 * (1 - self.price / self.regular), 1) if self.regular else 0.0


@dataclass
class SiteRead:
    platform: str = ""             # "shopify" | "woocommerce" | "" (neither, or not read)
    items: list[SiteItem] = field(default_factory=list)
    note: str = ""                 # why nothing was read: "the site answered with a bot check", "not read yet", ...
    fetched: int = 0               # requests this read made over the network
    read_at: float = 0.0           # when what it states was read (the oldest of its product pages)
    charged: bool = False          # it was read over the network this time, not answered from what is kept


def _money(v) -> Optional[float]:
    try:
        x = float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None
    return x if x > 0 else None


def _spread(host: str, ttl_s: float) -> float:
    """A lifetime up to half as long again, by the site's name, so that sites read on one day don't all fall due on
    another: the first week's reads all lapsed in the same build, and a third of the stores' deals went with them."""
    return ttl_s * (1 + int(hashlib.sha1(host.encode()).hexdigest()[:2], 16) / 510)


def _json(body: bytes):
    try:
        return json.loads(body)
    except ValueError:
        return None


def _record(rec: CachedResponse) -> tuple[str, str, str]:
    """What is kept of a site: (the platform it runs on, the listing that answered, why it could not be read)."""
    text = (rec.body or b"")[:4000].decode("utf-8", "replace")
    failed = _KEPT_FAILED.match(text)
    if failed:
        return "", "", failed.group(1)
    kept = _KEPT.match(text)
    if kept:
        return kept.group(1), kept.group(2), ""
    if rec.status != 200:
        return "", "", f"the site answered HTTP {rec.status}"
    return platform_of((rec.body or b"").decode("utf-8", "replace")), "", ""


def platform_of(page: str) -> str:
    kept = _KEPT.match(page)
    if kept:
        return kept.group(1)
    head = page[:400000]
    if _SHOPIFY.search(head):
        return "shopify"
    if _WOO.search(head):
        return "woocommerce"
    return ""


def _keep(http: PoliteClient, url: str, params: Optional[dict], r, body: bytes, ttl_s: float) -> None:
    """The response cache keeps what a shop's page said, not the page: there are thousands of shops, their pages run
    to hundreds of kilobytes, and the cache travels from build to build."""
    key = cache_key(url, params)
    http.store.cache_put(key, CachedResponse(key, r.status, "application/json", r.final_url, body, r.fetched_at,
                                             r.fetched_at + ttl_s))


def _shopify_kept(data: dict) -> dict:
    """A products page, as kept: the products on sale, with what shopify_items reads, and how many the page had."""
    keep = ("title", "handle", "product_type", "tags")
    products = [{**{k: p.get(k) for k in keep}, "images": (p.get("images") or [])[:1],
                 "variants": [{k: v.get(k) for k in ("price", "compare_at_price", "available")}
                              for v in p.get("variants") or []]}
                for p in data.get("products") or []
                if any(_money(v.get("compare_at_price")) for v in p.get("variants") or [])]
    return {"_count": len(data.get("products") or []), "products": products}


def _woo_kept(data) -> dict:
    items = data if isinstance(data, list) else []
    return {"_count": len(items), "items": [{"name": p.get("name"), "permalink": p.get("permalink"),
                                             "prices": p.get("prices"), "images": (p.get("images") or [])[:1],
                                             "categories": [{"name": c.get("name")} for c in p.get("categories") or []]}
                                            for p in items]}


def shopify_items(data: dict, host: str) -> list[SiteItem]:
    out = []
    for p in data.get("products") or []:
        sale = []
        variants = p.get("variants") or []
        for v in variants:
            price, was = _money(v.get("price")), _money(v.get("compare_at_price"))
            if price and was and was > price and v.get("available", True) is not False:
                sale.append((price / was, price, was))
        if not sale:
            continue
        _, price, was = min(sale)                                  # the variant with the biggest saving
        tags = p.get("tags") or []
        tags = tags if isinstance(tags, list) else str(tags).split(",")
        images = p.get("images") or []
        out.append(SiteItem(title=clean(htmllib.unescape(p.get("title") or "")), price=price, regular=was, basis="list",
                            url=f"https://{host}/products/{p.get('handle')}" if p.get("handle") else f"https://{host}/",
                            image=(images[0] or {}).get("src", "") if images else "",
                            words=" ".join(clean(x) for x in [p.get("product_type") or "", *tags[:8]] if x),
                            options=len(sale) < len(variants)))
    return out


def woo_items(data, host: str) -> list[SiteItem]:
    out = []
    for p in data if isinstance(data, list) else (data.get("items") or [] if isinstance(data, dict) else []):
        prices = p.get("prices") or {}
        if (prices.get("currency_code") or "USD") != "USD":
            continue
        unit = 10 ** int(prices.get("currency_minor_unit") or 0)
        price = _money(prices.get("sale_price") or prices.get("price"))
        was = _money(prices.get("regular_price"))
        if not price or not was or was <= price:
            continue
        images = p.get("images") or []
        out.append(SiteItem(title=clean(htmllib.unescape(re.sub(r"<[^>]+>", " ", p.get("name") or ""))),
                            price=round(price / unit, 2), regular=round(was / unit, 2), basis="store_regular",
                            url=p.get("permalink") or f"https://{host}/",
                            image=(images[0] or {}).get("src", "") if images else "",
                            words=" ".join(clean(c.get("name")) for c in (p.get("categories") or [])[:6])))
    return out


class ShopSites:
    def __init__(self, http: PoliteClient):
        self.http = http
        self.budget = SITES_PER_BUILD

    async def directory(self) -> tuple[dict[str, ShopSite], str]:
        """The shops on the map that give a website, by site, and "" or why the map could not be read: each Overpass
        server in turn, with what each said when it didn't answer."""
        why = []
        for url in OVERPASS:
            server = urlsplit(url).hostname
            try:
                r = await self.http.get(url, {"data": QUERY}, ttl_s=MAP_TTL, timeout_s=900, headers=OVERPASS_HEADERS)
            except FetchError as e:
                why.append(f"{server}: {e.reason}")
                continue
            if r.status != 200:
                said = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", r.text[:2000])).strip()[:160]
                why.append(f"{server}: HTTP {r.status}" + (f" ({said})" if said else ""))
                continue
            try:
                return parse_map(r.json()), ""
            except ValueError:
                why.append(f"{server}: its answer could not be read")
        return {}, "; ".join(why)

    # -- one site ----------------------------------------------------------------------------------------------
    # What Slomp knows of a site is kept in the response cache under its address: the platform it runs on, or why it
    # could not be read. A failure is remembered for a while, not tried again by every build: in the first week the
    # sites behind bot checks, robots.txt and dead addresses were retried each time and used up the builds' reads, so
    # a tenth of the stores were never read and the rest fell due on the same day (runs 126-147, Nov 9-16, 2026).
    def _cached(self, url: str, params: Optional[dict] = None) -> Optional[CachedResponse]:
        return self.http.store.cache_get(cache_key(url, params))

    def _remember(self, site: ShopSite, text: str, ttl_s: float, final_url: str = "") -> None:
        now = time.time()
        self.http.store.cache_put(site.url, CachedResponse(site.url, 200, "text/html", final_url or site.url,
                                                           f"<!-- slomp: {text} -->".encode(), now,
                                                           now + _spread(site.host, ttl_s)))

    def _products(self, site: ShopSite, rec: CachedResponse, platform: str, api: str) -> list[tuple]:
        """The product listings to try for a site on a platform: (address, page-size key, size, pages, extra, parse,
        kept, count), the one that worked last time first."""
        host = urlsplit(rec.final_url or site.url).hostname or site.host
        base = f"https://{host}"
        if platform == "shopify":
            return [(f"{base}/products.json", "limit", 250, SHOPIFY_PAGES, None, lambda d: shopify_items(d, host),
                     _shopify_kept, lambda d: d.get("_count", len(d.get("products") or [])))]
        paths = sorted(WOO_PATHS, key=lambda x: x != api)
        return [(f"{base}{path}", "per_page", 100, WOO_PAGES, {"on_sale": "true"}, lambda d: woo_items(d, host),
                 _woo_kept, lambda d: len(d) if isinstance(d, list) else d.get("_count", 0)) for path in paths]

    def need(self, site: ShopSite) -> int:
        """What reading a site would take, from what is already kept: 0 nothing (all of it is fresh), 1 its products
        again (a known shop platform; the deals come from these), 2 a first read, 3 another look at a site that had
        no platform or could not be read. A build's reads go to the lower numbers first."""
        rec = self._cached(site.url)
        if rec is None:
            return 2
        platform, api, _ = _record(rec)
        if platform in PLATFORMS:
            url, key, size, _, extra, *_ = self._products(site, rec, platform, api)[0]
            page = self._cached(url, {**(extra or {}), key: size, "page": 1})
            return 0 if page and page.fresh else 1
        return 0 if rec.fresh else 3

    async def read(self, site: ShopSite, fetch: bool = True) -> SiteRead:
        """What the site has on sale. With `fetch` off, only what is kept is used, though it has fallen due: a store
        keeps its last deals (they lapse by themselves two days after their read) while it waits its turn."""
        out = SiteRead()
        rec = self._cached(site.url)
        platform, api, note = _record(rec) if rec else ("", "", "")
        if rec is None or (not rec.fresh and fetch and platform not in PLATFORMS):
            if not fetch:
                out.note = NOT_YET
                return out
            rec, platform, note = await self._look(site, out)
            api = ""
        if note or rec is None:
            out.note = note
            return out
        out.platform = platform
        if platform not in PLATFORMS:
            out.note = "the site runs on no platform Slomp reads"
            return out
        failed = ""
        for url, key, size, pages, extra, parse, kept, count in self._products(site, rec, platform, api):
            got = SiteRead()
            got.items = await self._pages(got, url, key, size, pages, extra, parse, kept, count, fetch)
            out.fetched += got.fetched
            out.charged = out.charged or got.charged
            if got.read_at:
                out.items, out.read_at, out.note = got.items, got.read_at, ""
                path = urlsplit(url).path
                if got.charged and (path != api and platform == "woocommerce" or rec.expires_at - time.time() < 7 * DAY):
                    # the listing answered: the site is what the record says, for another while
                    self._remember(site, f"the site runs on {platform} {path}".strip(), RECORD_TTL, rec.final_url)
                return out
            failed = got.note if failed in ("", NOT_YET) else failed
        out.note = failed
        if failed and failed != NOT_YET:
            # No listing answers, and nothing is kept of one: the shop has closed it. Looked at again later.
            self._remember(site, f"not read: {failed}", PRODUCTS_FAILED_TTL, rec.final_url)
        return out

    async def _look(self, site: ShopSite, out: SiteRead) -> tuple[Optional[CachedResponse], str, str]:
        """Read the site's home page for the platform it runs on, and keep the answer: (record, platform, why not)."""
        out.charged = True
        try:
            home = await self.http.get(site.url, ttl_s=RECORD_TTL, html=True, use_cache=False)
        except Blocked:
            note, ttl = "the site answered with a bot check", FAILED_TTL
        except Disallowed as e:
            if "AI assistants" in e.reason:           # who runs Slomp today, not the site: nothing to remember
                return None, "", e.reason
            note, ttl = e.reason, FAILED_TTL
        except FetchError as e:
            note, ttl = f"the site could not be read ({e.reason})", ERROR_TTL
        else:
            out.fetched += 1
            if home.status == 200:
                platform = platform_of(home.text)
                self._remember(site, f"the site runs on {platform}".strip(), RECORD_TTL, home.final_url)
                return self._cached(site.url), platform, ""
            # 202 is a page that asks the browser to wait and prove itself: a bot check by another name
            note = f"the site answered HTTP {home.status}"
            ttl = FAILED_TTL if home.status in (202, 401, 403, 404, 410) else ERROR_TTL
        self._remember(site, f"not read: {note}", ttl)
        return None, "", note

    async def _pages(self, out: SiteRead, url: str, size_key: str, size: int, pages: int, extra: Optional[dict],
                     parse, kept, count, fetch: bool) -> list[SiteItem]:
        """A platform's product pages, in order, until one comes back short. `kept` is what the cache keeps of one.
        `out.read_at` is when the oldest page used was read; it stays 0, with `out.note`, when the first page gave
        nothing to go by."""
        items: list[SiteItem] = []
        times: list[float] = []
        for page in range(1, pages + 1):
            params = {**(extra or {}), size_key: size, "page": page}
            had = self._cached(url, params)
            good = had if had and had.status == 200 and _json(had.body) is not None else None
            if good and (good.fresh or not fetch):
                data, at = _json(good.body), good.fetched_at
            elif not fetch:
                out.note = NOT_YET
                break
            else:
                out.charged = True
                data, at = None, 0.0
                try:
                    r = await self.http.get(url, params, ttl_s=ITEMS_TTL, robots=True, use_cache=False)
                    out.fetched += 1
                    fresh = _json(r.body) if r.status == 200 else None
                    if fresh is not None:
                        data, at = kept(fresh), r.fetched_at
                        _keep(self.http, url, params, r, json.dumps(data, separators=(",", ":")).encode(), ITEMS_TTL)
                    else:
                        out.note = "the products could not be read (" + \
                            (f"HTTP {r.status}" if r.status != 200 else "not JSON") + ")"
                except FetchError as e:
                    out.note = f"the products could not be read ({e.reason})"
                if data is None and good:          # it answered before: the last answer stands, and stays kept
                    self.http.store.cache_put(cache_key(url, params), good)
                    data, at, out.note = _json(good.body), good.fetched_at, ""
            if data is None:
                break
            items += parse(data)
            times.append(at)
            if count(data) < size:
                break
        if times:
            out.read_at, out.note = min(times), ""
        return items

    async def read_all(self, sites: Iterable[ShopSite], budget: Optional[int] = None,
                       at_once: int = 24) -> dict[str, SiteRead]:
        """Every site's read. At most `budget` sites are read over the network: first the known shop platforms whose
        products have fallen due, then sites never read, then second looks; the rest use what is kept."""
        self.budget = SITES_PER_BUILD if budget is None else budget
        order = sorted(sites, key=lambda s: (self.need(s), hashlib.sha1(s.host.encode()).hexdigest()))
        fetch = {s.host for s in [s for s in order if self.need(s)][:max(0, self.budget)]}
        self.budget -= len(fetch)
        gate = asyncio.Semaphore(at_once)
        out: dict[str, SiteRead] = {}

        async def one(s: ShopSite) -> None:
            async with gate:
                out[s.host] = await self.read(s, s.host in fetch)
        await asyncio.gather(*(one(s) for s in order))
        return out


def near(sites: dict[str, ShopSite], lat: float, lon: float, radius_mi: float) -> list[ShopSite]:
    """The sites with a shop within `radius_mi` of a point."""
    return [s for s in sites.values() if any(miles(lat, lon, r[0], r[1]) <= radius_mi for r in s.locations)]


def same_name(sites: dict[str, ShopSite], name: str) -> Optional[ShopSite]:
    """The site whose shops carry a name (a Flipp merchant Slomp has no stores for, found on the map by name)."""
    key = norm(name)
    return next((s for s in sites.values() if norm(s.name) == key), None) if key else None
