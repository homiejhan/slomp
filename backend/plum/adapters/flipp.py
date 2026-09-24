"""Flipp weekly ads (flipp.com): the circulars retailers publish for a ZIP code, item by item.

These are the endpoints flipp.com's own web app calls: public and keyless but undocumented, so every field is read
defensively and anything malformed is dropped with a reason instead of guessed at. Retailers supply the ads; Flipp
notes prices can change after posting, so every deal links to the ad itself and, when it has one, the retailer's page.

Three item shapes come back:
  * flyer index (/flyers/<id>): name, price and a headline percent only; enough to rank, not to display
  * full record (/items/<id>): all the ad text (multi-buy, BOGO, "with card", ...) plus the retailer link
  * search hit (/items/search): most of the ad text, no retailer link
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any, Optional

from ..models import Flyer, LocalDeal
from ..net import HttpClient
from ..terms import clean, parse_terms

API = "https://backflipp.wishabi.com/flipp"
WEB = "https://flipp.com/en-us"
TTL_S = 3600               # ads change weekly; an hour keeps repeat runs quick without serving stale prices
PRODUCT = 1                # display_type of real items; others are banners, page furniture and placeholders
_PLACEHOLDER = re.compile(r"^[A-Z]{3,}\d{6,}$")        # "BESBU093025990119": an internal code, not an item


def item_url(item_id: Any) -> str:
    return f"{WEB}/item/{item_id}"


def flyer_url(flyer_id: Any) -> str:
    return f"{WEB}/weekly_ad/{flyer_id}"


def end_day(d: datetime) -> str:
    """The calendar day an ad ends on. Search results give end times in UTC, where "11:59 PM Sep 28" in any US time zone
    reads as early Sep 29, so an early-morning UTC end belongs to the day before."""
    if d.utcoffset() == timedelta(0) and d.hour < 12:
        d -= timedelta(hours=12)
    return f"{d:%b} {d.day}"


def when(raw: Any) -> Optional[datetime]:
    try:
        d = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else None           # a naive time can't be compared honestly with "now"


def parse_flyer(raw: dict) -> Optional[Flyer]:
    start, end = when(raw.get("valid_from")), when(raw.get("valid_to"))
    merchant = clean(raw.get("merchant"))
    if not (raw.get("id") and merchant and start and end):
        return None
    cats = tuple(c for c in raw.get("categories") or () if c and c != "All Flyers")
    return Flyer(int(raw["id"]), merchant, int(raw.get("merchant_id") or 0), start, end, cats,
                 str(raw.get("postal_code") or ""))


def junk(raw: dict) -> str:
    """Why this entry isn't a sellable item, or "" if it is."""
    if raw.get("display_type", PRODUCT) != PRODUCT:
        return "not an item (ad banner or page element)"
    name = clean(raw.get("name"))
    if not name:
        return "no item name"
    if _PLACEHOLDER.match(name):
        return "placeholder entry"
    return ""


def _deal(raw: dict, merchant: str, terms_kw: dict, flyer: Optional[Flyer], *, detailed: bool,
          image_key: str, feed: Optional[bool] = None) -> tuple[Optional[LocalDeal], str]:
    why = junk(raw)
    if why:
        return None, why
    start = when(raw.get("valid_from")) or (flyer.valid_from if flyer else None)
    end = when(raw.get("valid_to")) or (flyer.valid_to if flyer else None)
    if not (start and end and raw.get("id")):
        return None, "no validity dates"
    link = str(raw.get("ttm_url") or "")
    link = link if link.startswith(("https://", "http://")) else ""
    # Items linked to a retailer product page come from the retailer's feed; the rest were transcribed from the ad.
    return LocalDeal(
        id=f"flipp:{raw['id']}", merchant=merchant, title=clean(raw.get("name")),
        terms=parse_terms(merchant=merchant, name=raw.get("name"), feed=bool(link) if feed is None else feed, **terms_kw),
        valid_from=start, valid_to=end, flyer_id=raw.get("flyer_id") or (flyer.id if flyer else None),
        source_url=item_url(raw["id"]), product_url=link,
        image_url=str(raw.get(image_key) or ""), brand=clean(raw.get("brand")),
        category=clean(raw.get("_L2") or raw.get("_L1") or raw.get("category")), detailed=detailed,
    ), ""


def listing_deal(raw: dict, flyer: Flyer) -> tuple[Optional[LocalDeal], str]:
    """Flyer-index entry: price and headline percent only, so it seeds ranking but is never shown as-is. Its score
    must be an upper bound on the full record's, so the headline saving is taken at face value here."""
    return _deal(raw, flyer.merchant, {"price": raw.get("price"), "pct": raw.get("discount")}, flyer,
                 detailed=False, image_key="cutout_image_url", feed=True)


def detailed_deal(raw: dict, flyer: Optional[Flyer] = None) -> tuple[Optional[LocalDeal], str]:
    """Full item record: every price field the ad has."""
    merchant = clean(raw.get("merchant")) or (flyer.merchant if flyer else "")
    return _deal(raw, merchant, {
        "price": raw.get("current_price"), "original": raw.get("original_price"), "pre": raw.get("pre_price_text"),
        "post": raw.get("price_text"), "story": raw.get("sale_story"), "pct": raw.get("percent_off"),
        "dollars": raw.get("dollars_off"), "in_store_only": bool(raw.get("in_store_only")),
        "description": raw.get("description"), "disclaimer": raw.get("disclaimer_text")},
        flyer, detailed=True, image_key="cutout_image_url")


def search_deal(raw: dict) -> tuple[Optional[LocalDeal], str]:
    return _deal(raw, clean(raw.get("merchant_name")), {
        "price": raw.get("current_price"), "original": raw.get("original_price"), "pre": raw.get("pre_price_text"),
        "post": raw.get("post_price_text"), "story": raw.get("sale_story")},
        None, detailed=False, image_key="clean_image_url")


class FlippClient:
    name = "Flipp weekly ads"

    def __init__(self, http: HttpClient, locale: str = "en-us"):
        self.http, self.locale = http, locale

    async def flyers(self, postal_code: str) -> list[Flyer]:
        data = await self.http.get_json(f"{API}/flyers", {"locale": self.locale, "postal_code": postal_code}, ttl_s=TTL_S)
        return [f for f in map(parse_flyer, (data or {}).get("flyers") or []) if f]

    async def flyer_items(self, flyer_id: int) -> list[dict]:
        data = await self.http.get_json(f"{API}/flyers/{flyer_id}", {"locale": self.locale}, ttl_s=TTL_S)
        return list((data or {}).get("items") or [])

    async def item(self, item_id: Any) -> dict:
        data = await self.http.get_json(f"{API}/items/{item_id}", ttl_s=TTL_S)
        return (data or {}).get("item") or {}

    async def search(self, postal_code: str, query: str) -> list[dict]:
        data = await self.http.get_json(f"{API}/items/search", {"locale": self.locale, "postal_code": postal_code,
                                                               "q": query}, ttl_s=TTL_S)
        return list((data or {}).get("items") or [])
