"""Flipp weekly ads (flipp.com): the circulars retailers publish for a ZIP code, item by item.

These are the keyless endpoints flipp.com's own web app calls. They are undocumented, so every field is read
defensively. Four views of the same items:

  /flyers?postal_code=      the ads running (or about to run) for a ZIP
  /flyers/{id}              every item in one ad: name, price, headline % off, per-item dates
  /items/search?q=          search hits; searching a merchant's name returns that merchant's ad items (max 150)
                            with Google Product Taxonomy labels (_L1/_L2) and the original price
  /items/{id}               the full record: sale story, $ and % off, fine print, the retailer's product link
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable, Optional

from ..config import TTL
from ..geo import parse_time
from ..http import FetchError, PoliteClient
from ..terms import clean

API = "https://backflipp.wishabi.com/flipp"
WEB = "https://flipp.com/en-us"
PRODUCT = 1                          # display_type of real items; others are banners and page furniture
SEARCH_LIMIT = 200                   # the most the search endpoint accepts (it returns at most ~150 per merchant)
_PLACEHOLDER = re.compile(r"^[A-Z]{3,}[0-9_]{6,}|^[A-Z]{3,}_[A-Z0-9_-]+$")   # BESBU093025390110, DKSPT_COVER-BANNER


_FINE_PRINT = re.compile(r"^(?:must be|must have|limit \d|excludes?|exclusions|valid (?:on|through|thru|with|only)|see store|"
                         r"while supplies|offer valid|offers? good|prices? (?:good|valid|effective)|not valid|"
                         r"no rain ?checks|selection varies)\b", re.I)


def item_url(item_id: Any) -> str:
    return f"{WEB}/item/{item_id}"


def flyer_url(flyer_id: Any) -> str:
    return f"{WEB}/weekly_ad/{flyer_id}"


@dataclass
class Flyer:
    id: int
    merchant: str
    merchant_id: int
    valid_from: datetime
    valid_to: datetime
    categories: list[str] = field(default_factory=list)
    postal_code: str = ""


def parse_flyer(raw: dict) -> Optional[Flyer]:
    start, end = parse_time(raw.get("valid_from")), parse_time(raw.get("valid_to"))
    merchant = clean(raw.get("merchant"))
    if not (raw.get("id") and merchant and start and end):
        return None
    cats = [c for c in raw.get("categories") or [] if c and c != "All Flyers"]
    return Flyer(int(raw["id"]), merchant, int(raw.get("merchant_id") or 0), start, end, cats,
                 str(raw.get("postal_code") or ""))


def junk_reason(raw: dict) -> str:
    """Why an entry isn't a sellable item, or '' if it is."""
    if raw.get("display_type", PRODUCT) != PRODUCT:
        return "page element, not an item"
    name = clean(raw.get("name"))
    if not name:
        return "no item name"
    if _PLACEHOLDER.match(name) and " " not in name:
        return "placeholder code, not an item"
    if _FINE_PRINT.match(name):
        return "fine print, not an item"
    return ""


def is_product_link(url: str, domains: list[str]) -> bool:
    """A retailer product page (the item came from the retailer's feed), not a promo landing page."""
    if not url or not url.startswith("http"):
        return False
    if re.search(r"/(?:site/promo|promo|deals|weekly-?ad|sale|c/|category|browse/category|shop/)", url, re.I) \
            and not re.search(r"/(?:p|product|ip|dp)/|/product\.do|pid=", url, re.I):
        return False
    return bool(re.search(r"/(?:p|product|products|ip|dp|pd)/|/product\.do|[?&]pid=|/\d{6,}|/A-\d+|\.html?$|/sku/",
                          url, re.I))


class FlippClient:
    name = "Flipp weekly ads"

    def __init__(self, http: PoliteClient, locale: str = "en-us"):
        self.http, self.locale = http, locale

    async def flyers(self, postal_code: str) -> list[Flyer]:
        r = await self.http.get(f"{API}/flyers", {"locale": self.locale, "postal_code": postal_code},
                                ttl_s=TTL["flyers"])
        data = r.json() if r.status == 200 else {}
        return [f for f in map(parse_flyer, data.get("flyers") or []) if f]

    async def flyer_items(self, flyer_id: int) -> list[dict]:
        r = await self.http.get(f"{API}/flyers/{flyer_id}", {"locale": self.locale}, ttl_s=TTL["flyer_items"])
        return list((r.json() if r.status == 200 else {}).get("items") or [])

    async def search(self, postal_code: str, query: str, ttl_s: Optional[float] = None) -> dict:
        return (await self._search(postal_code, query, ttl_s))[0]

    async def _search(self, postal_code: str, query: str, ttl_s: Optional[float] = None,
                      use_cache: bool = True) -> tuple[dict, bool]:
        r = await self.http.get(f"{API}/items/search", {"locale": self.locale, "postal_code": postal_code, "q": query,
                                                       "limit": SEARCH_LIMIT}, ttl_s=ttl_s or TTL["flipp_search"],
                                use_cache=use_cache)
        return (r.json() if r.status == 200 else {}), r.from_cache

    async def merchant_items(self, postal_code: str, merchant: str, expect: Iterable[int] = ()) -> list[dict]:
        """That merchant's ad items with taxonomy labels. Searching the name also matches other merchants' items
        that mention it, so only the merchant's own items are kept. `expect` is the merchant's ads at that ZIP: a
        result from the cache with nothing from one of them was read before that ad came out, so it is read again."""
        key = re.sub(r"[^a-z0-9]", "", merchant.lower())

        def own(data: dict) -> list[dict]:
            return [i for i in data.get("items") or []
                    if re.sub(r"[^a-z0-9]", "", str(i.get("merchant_name") or "").lower()) == key]
        data, cached = await self._search(postal_code, merchant, TTL["merchant_search"])
        items = own(data)
        if cached and set(expect) - {i.get("flyer_id") for i in items}:
            try:
                items = own((await self._search(postal_code, merchant, TTL["merchant_search"], use_cache=False))[0])
            except FetchError:
                pass                                # the older answer is still the best there is
        return items

    async def item(self, item_id: Any) -> dict:
        r = await self.http.get(f"{API}/items/{item_id}", ttl_s=TTL["item"])
        return (r.json() if r.status == 200 else {}).get("item") or {}
