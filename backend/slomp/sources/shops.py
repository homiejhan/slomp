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
read there, not here. robots.txt is honored, a bot check is never worked around, and a build reads at most
SITES_PER_BUILD sites it has no fresh copy of; the rest wait for the next build.
"""
from __future__ import annotations

import asyncio
import hashlib
import html as htmllib
import json
import re
from collections import Counter
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Iterable, Optional
from urllib.parse import urlsplit

from ..config import DAY
from ..db import CachedResponse
from ..geo import miles
from ..http import Blocked, Disallowed, FetchError, PoliteClient, cache_key
from ..reference import merchants, norm
from ..stores_online import registry
from ..terms import clean

OVERPASS = "https://overpass-api.de/api/interpreter"
QUERY = """[out:json][timeout:900];
area["ISO3166-2"="US-TX"]->.tx;
(nwr["shop"]["website"](area.tx);nwr["shop"]["contact:website"](area.tx););
out center tags;"""
MAP_TTL = 7 * DAY            # the shops on the map
HOME_TTL = 7 * DAY           # a shop's home page: which platform its site runs on
ITEMS_TTL = DAY              # what it has on sale
SITES_PER_BUILD = 600        # sites read afresh in one build, at most
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
# What the response cache keeps of a shop's home page: which platform it runs on, not the page (see _keep).
_KEPT = re.compile(r"^<!-- slomp: the site runs on (\w*) -->")


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
    return sites


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
    read_at: float = 0.0           # when what it states was read (the newest of its pages)
    charged: bool = False          # it spent one of the build's fresh reads


def _money(v) -> Optional[float]:
    try:
        x = float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None
    return x if x > 0 else None


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
        """The shops on the map that give a website, by site, and "" or why the map could not be read."""
        try:
            r = await self.http.get(OVERPASS, {"data": QUERY}, ttl_s=MAP_TTL, timeout_s=900)
        except FetchError as e:
            return {}, e.reason
        if r.status != 200:
            return {}, f"HTTP {r.status}"
        try:
            return parse_map(r.json()), ""
        except ValueError:
            return {}, "the map's answer could not be read"

    def _fresh(self, url: str, params: Optional[dict] = None) -> bool:
        c = self.http.store.cache_get(cache_key(url, params))
        return bool(c and c.fresh)

    def _afford(self, out: SiteRead, url: str, params: Optional[dict] = None) -> bool:
        """Whether a page can be read: it is cached and fresh, or the site has spent (or can still spend) one of the
        build's fresh reads. A site costs one read however many of its pages it takes."""
        if out.charged or self._fresh(url, params):
            return True
        if self.budget <= 0:
            out.note = "not read yet: this build's reads were spent"
            return False
        self.budget -= 1
        out.charged = True
        return True

    async def read(self, site: ShopSite) -> SiteRead:
        """What the site has on sale."""
        out = SiteRead()
        if not self._afford(out, site.url):
            return out
        try:
            home = await self.http.get(site.url, ttl_s=HOME_TTL, html=True)
        except Blocked:
            out.note = "the site answered with a bot check"
            return out
        except Disallowed as e:
            out.note = e.reason
            return out
        except FetchError as e:
            out.note = f"the site could not be read ({e.reason})"
            return out
        out.fetched += not home.from_cache
        out.read_at = home.fetched_at
        if home.status != 200:
            out.note = f"the site answered HTTP {home.status}"
            return out
        out.platform = platform_of(home.text)
        if not home.from_cache:
            _keep(self.http, site.url, None, home, f"<!-- slomp: the site runs on {out.platform} -->".encode(),
                  HOME_TTL)
        base = f"https://{urlsplit(home.final_url or site.url).hostname or site.host}"
        host = urlsplit(base).hostname or site.host
        if out.platform == "shopify":
            out.items = await self._pages(out, f"{base}/products.json", "limit", 250, SHOPIFY_PAGES,
                                          lambda d: shopify_items(d, host), _shopify_kept,
                                          lambda d: d.get("_count", len(d.get("products") or [])))
        elif out.platform == "woocommerce":
            for path in ("/wp-json/wc/store/v1/products", "/wp-json/wc/store/products"):
                out.items = await self._pages(out, f"{base}{path}", "per_page", 100, WOO_PAGES,
                                              lambda d: woo_items(d, host), _woo_kept,
                                              lambda d: len(d) if isinstance(d, list) else d.get("_count", 0),
                                              {"on_sale": "true"})
                if out.items or out.note != "the products could not be read (HTTP 404)":
                    break
        else:
            out.note = "the site runs on no platform Slomp reads"
        return out

    async def _pages(self, out: SiteRead, url: str, size_key: str, size: int, pages: int, parse, kept, count,
                     extra: Optional[dict] = None) -> list[SiteItem]:
        """A platform's product pages, in order, until one comes back short. `kept` is what the cache keeps of one."""
        items: list[SiteItem] = []
        for page in range(1, pages + 1):
            params = {**(extra or {}), size_key: size, "page": page}
            if not self._afford(out, url, params):
                break
            try:
                r = await self.http.get(url, params, ttl_s=ITEMS_TTL, robots=True)
            except FetchError as e:
                out.note = f"the products could not be read ({e.reason})"
                break
            out.fetched += not r.from_cache
            out.read_at = max(out.read_at, r.fetched_at)
            if r.status != 200:
                out.note = f"the products could not be read (HTTP {r.status})"
                break
            try:
                data = r.json()
            except ValueError:
                out.note = "the products could not be read (not JSON)"
                break
            if not r.from_cache:
                data = kept(data)
                _keep(self.http, url, params, r, json.dumps(data, separators=(",", ":")).encode(), ITEMS_TTL)
            items += parse(data)
            if count(data) < size:
                break
        return items

    async def read_all(self, sites: Iterable[ShopSite], budget: Optional[int] = None,
                       at_once: int = 24) -> dict[str, SiteRead]:
        """Every site's read, the cached ones first so the fresh reads (`budget` of them) go to sites not read yet."""
        if budget is not None:
            self.budget = budget
        todo = sorted(sites, key=lambda s: (not self._fresh(s.url), hashlib.sha1(s.host.encode()).hexdigest()))
        gate = asyncio.Semaphore(at_once)
        out: dict[str, SiteRead] = {}

        async def one(s: ShopSite) -> None:
            async with gate:
                out[s.host] = await self.read(s)
        await asyncio.gather(*(one(s) for s in todo))
        return out


def near(sites: dict[str, ShopSite], lat: float, lon: float, radius_mi: float) -> list[ShopSite]:
    """The sites with a shop within `radius_mi` of a point."""
    return [s for s in sites.values() if any(miles(lat, lon, r[0], r[1]) <= radius_mi for r in s.locations)]


def same_name(sites: dict[str, ShopSite], name: str) -> Optional[ShopSite]:
    """The site whose shops carry a name (a Flipp merchant Slomp has no stores for, found on the map by name)."""
    key = norm(name)
    return next((s for s in sites.values() if norm(s.name) == key), None) if key else None
