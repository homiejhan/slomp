"""Online deals: specific products at big discounts on web stores right now, with the same product's price elsewhere.

Sources (adapters/feeds.py): Slickdeals' front page and popular deals (community-vetted), dealnews (editor-checked,
often with other stores' prices), camelcamelcamel (Amazon drops against Amazon's own price history). A deal counts only
if it names one product at one price; storewide sales, memberships and services are left out.

The same product elsewhere comes from three places, all current:
  * dealnews editors: "You'd pay $5 more at Macy's", "the best price we found by $16"
  * this week's ads from stores near you, matched on the model number. The big chains' ad prices are their web prices
    too, and each ad item links to the retailer's page.
  * the other feeds, when one carries the same model at another store
Matching is on model numbers only (textfeatures.model_codes), so two different 1080p monitors never look alike.
"""
from __future__ import annotations

import asyncio
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable, Optional

from .adapters.feeds import FEEDS, DealFeeds
from .adapters.flipp import FlippClient, end_day, search_deal
from .geo import Geocoder
from .local import SourceStatus
from .models import OnlineDeal, Place, PricePoint, utcnow
from .net import HttpClient, HttpError
from .textfeatures import ACCESSORY, features, model_codes, near_code, tokens, unit_of

MAX_AGE = timedelta(days=5)        # older posts are usually sold out or repriced
# Posts about many products: "Up to 50% off", "Eyewear Deals for $1", "Deals from $30", "$10 off $40", "Promo Code".
_NOT_ONE_ITEM = re.compile(r"^\s*(?:up to\s+|at least\s+)?\d+%\s+off\b|\bsitewide\b|\bstorewide\b|^\s*select\s|"
                           r"\bbuy\s+(?:one|two|\d+).{0,20}\bget\b|\bsale\s*(?:$|:)|\bdeals\b|\bfrom\s+\$|"
                           r"\$\d[\d,.]*\s+off\s+\$\d|\bpromo code\b", re.I)
_SERVICE = re.compile(r"\bmemberships?\b|\bbanking\b|\bchecking\b|\bcredit card\b|\bvacation\b|\bflights?\b|\bhotel\b|"
                      r"\bcruise\b|\bauctions?\b|\bgiveaway\b|\bsubscription\b|\bgift cards?\b|\bfree\s+(?:kindle|e?books?)\b",
                      re.I)
_QUANTITY = re.compile(r"^\d+(?:-?(?:pk|pack|pc|piece|ct|count|oz|sheets?|in|inch|ft|gallon|quart))?$", re.I)
# Screen and product sizes in inches: 43", 55-inch, 32 in., 65" Class. Within one TV or monitor series, the size is
# what makes it a different product (a 43" and a 55" U8000H share the series name).
_INCHES = re.compile(r"(?<![\d.])(\d{2,3}(?:\.\d)?)\s*(?:\"|”|″|''|-?\s*inch(?:es)?\b|\s?in\.?(?![a-z]))", re.I)


def inches(title: str) -> set[str]:
    return set(_INCHES.findall(title))


@dataclass
class OnlineReport:
    generated_at: datetime
    deals: list[OnlineDeal] = field(default_factory=list)       # a stated discount of at least min_pct, biggest first
    popular: list[OnlineDeal] = field(default_factory=list)     # community favorites that state no discount
    compared_near: Optional[Place] = None
    looked_up: int = 0                                          # deals with a model number checked against the ads
    sources: list[SourceStatus] = field(default_factory=list)
    skipped: Counter = field(default_factory=Counter)


def score(d: OnlineDeal) -> float:
    """Percent saved. A discount against other stores' prices or the store's own counts fully; against a list price,
    a range, or no stated price at all it counts half."""
    pct = d.terms.pct_off or 0.0
    return pct if d.terms.hedge in ("", "elsewhere") else pct / 2


def not_an_item(d: OnlineDeal) -> str:
    """Why this post isn't one product at one price, or ""."""
    said = f"{d.title} | {d.headline}"                # the headline keeps wording the product name drops ("$10 off $40")
    if _SERVICE.search(said) or _SERVICE.search(d.category):
        return "a service or membership"
    if _NOT_ONE_ITEM.search(d.title) or _NOT_ONE_ITEM.search(d.headline):
        return "a sale, not one item"
    if d.terms.price is None:
        return "no single price"
    return ""


def same_product(a: str, b: str) -> bool:
    """Same model number, no conflicting one (XM5 vs XM6), same size, and neither is an accessory for the other."""
    ca, cb = model_codes(a), model_codes(b)
    if not ca & cb:
        return False
    if any(near_code(x, y) for x in ca - cb for y in cb - ca):  # real model numbers only: joined word pairs such as
        return False                                            # "u8000h43" vs "u8000h4k" would look like a conflict
    fa, fb = features(a), features(b)
    if (fa.bag & ACCESSORY) ^ (fb.bag & ACCESSORY):
        return False
    ia, ib = inches(a), inches(b)
    if ia and ib and not ia & ib:
        return False
    return not any(unit_of(s) == unit_of(t) and s != t for s in fa.sizes for t in fb.sizes)


def _search_terms(d: OnlineDeal) -> Optional[str]:
    """Brand plus model number, the way a store's ad would name it: "Samsung U8000H"."""
    codes = model_codes(d.title)
    if not codes:
        return None
    words = [w for w in tokens(d.title) if not _QUANTITY.match(w)]
    brand = next((w for w in words if w.isalpha() and len(w) > 2), "")
    code = max(codes, key=len)
    original = next((t for t in d.title.replace("(", " ").replace(")", " ").split() if t.lower().replace("-", "") == code),
                    code)
    return f"{brand} {original}".strip()


def cross_link(deals: list[OnlineDeal]) -> None:
    """The same model posted for another store in another feed is that store's price."""
    for i, a in enumerate(deals):
        for b in deals[i + 1:]:
            if a.store.lower() != b.store.lower() and same_product(a.title, b.title):
                a.elsewhere.append(PricePoint(b.store, b.terms.unit_price, f"{b.source} post", b.url))
                b.elsewhere.append(PricePoint(a.store, a.terms.unit_price, f"{a.source} post", a.url))


class OnlineDealService:
    def __init__(self, http: HttpClient, *, lookups: int = 12, clock: Callable[[], datetime] = utcnow):
        self.http = http
        self.feeds = DealFeeds(http)
        self.geocoder = Geocoder(http)
        self.flipp = FlippClient(http)
        self.lookups = lookups
        self.clock = clock

    async def _fetch(self, source: str, rep: OnlineReport) -> list[OnlineDeal]:
        try:
            deals = await self.feeds.fetch(source)
        except HttpError as e:
            rep.sources.append(SourceStatus(source, False, str(e)))
            return []
        rep.sources.append(SourceStatus(source, True, f"{len(deals)} posts"))
        return deals

    async def _compare_with_ads(self, d: OnlineDeal, place: Place, now: datetime) -> None:
        q = _search_terms(d)
        if not q:
            return
        try:
            raws = await self.flipp.search(place.postal_code, q)
        except HttpError:
            return
        for raw in raws:
            item, why = search_deal(raw)
            if why or item.valid_to < now or item.valid_from > now or item.terms.unit_price is None:
                continue
            if same_product(d.title, item.title) and item.merchant.lower() != d.store.lower():
                d.elsewhere.append(PricePoint(item.merchant, round(item.terms.unit_price, 2), f"{item.merchant} weekly ad",
                                              item.product_url or item.source_url,
                                              note=f"ad runs through {end_day(item.valid_to)}"))

    async def deals(self, *, where: str = "", min_pct: float = 30.0, limit: int = 30, popular: int = 8) -> OnlineReport:
        now = self.clock()
        rep = OnlineReport(now)
        batches = await asyncio.gather(*(self._fetch(s, rep) for s in FEEDS))
        kept: list[OnlineDeal] = []
        for d in (d for batch in batches for d in batch):
            why = not_an_item(d)
            if not why and d.expires and d.expires < now:
                why = "deal has ended"
            if not why and d.posted and now - d.posted > MAX_AGE:
                why = "posted more than 5 days ago"
            if why:
                rep.skipped[why] += 1
            else:
                kept.append(d)
        cross_link(kept)
        ranked = sorted(kept, key=lambda d: (-score(d), -(d.votes or 0)))
        rep.deals = [d for d in ranked if score(d) >= min_pct][:limit]
        chosen = {d.id for d in rep.deals}
        rep.popular = sorted((d for d in kept if d.id not in chosen and d.votes and not d.terms.pct_off),
                             key=lambda d: -(d.votes or 0))[:popular]
        if where.strip():
            try:
                rep.compared_near = await self.geocoder.resolve(where)
            except (LookupError, HttpError) as e:
                rep.sources.append(SourceStatus("Store ads near you", False, str(e)))
            if rep.compared_near:
                todo = [d for d in rep.deals + rep.popular if _search_terms(d)][:self.lookups]
                rep.looked_up = len(todo)
                await asyncio.gather(*(self._compare_with_ads(d, rep.compared_near, now) for d in todo))
                rep.sources.append(SourceStatus("Store ads near you", True, f"{len(todo)} model numbers looked up near "
                                                f"{rep.compared_near.name}"))
        for d in rep.deals + rep.popular:
            d.elsewhere.sort(key=lambda p: p.price or 0)
        return rep
