"""Orchestration: one call turns a query into a ranked, explained set of offers."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from . import coupons as C
from .adapters.base import Adapter, AdapterOutcome, run_adapters
from .adapters.checkout_probe import CheckoutProbe
from .cache import TTLCache
from .matching import ProductIndex, match
from .models import Condition, Listing, MatchResult, ProbeResult, Product, Quote, RetailerPolicy, Tier
from .pricing import quote
from .ranking import is_period_low, rank_quotes


@dataclass
class Skipped:
    listing: Listing
    match: MatchResult
    why: str


@dataclass
class DealReport:
    product: Optional[Product]
    how: str
    offers: list[Quote] = field(default_factory=list)
    skipped: list[Skipped] = field(default_factory=list)
    adapters: list[AdapterOutcome] = field(default_factory=list)
    history: dict[str, list[float]] = field(default_factory=dict)   # retailer -> last N prices

    @property
    def best(self) -> Optional[Quote]:
        return self.offers[0] if self.offers else None

    def is_low(self, q: Quote) -> bool:
        return is_period_low(q.listing.price, self.history.get(q.listing.retailer, []))


class PriceHistoryStore:
    """In-memory ring of observed prices per (product, retailer). Swap for a time-series DB."""

    def __init__(self, keep: int = 90):
        self.keep, self._d = keep, {}

    def record(self, product_id: str, retailer: str, price: float) -> None:
        key = (product_id, retailer)
        arr = self._d.setdefault(key, [])
        arr.append(price)
        del arr[:-self.keep]

    def series(self, product_id: str, retailer: str) -> list[float]:
        return list(self._d.get((product_id, retailer), []))


class DealService:
    def __init__(self, products: list[Product], policies: dict[str, RetailerPolicy], adapters: list[Adapter],
                 coupons: list[C.Coupon], probe: Optional[CheckoutProbe] = None, budget_s: float = 1.4):
        self.index = ProductIndex(products)
        self.policies = policies
        self.adapters = adapters
        self.coupons = C.dedupe(coupons)
        self.probe = probe
        self.budget_s = budget_s
        self.history = PriceHistoryStore()
        self.verified: dict[str, Optional[str]] = {}     # listing id -> code that worked (or None)
        self.cache: TTLCache[list[AdapterOutcome]] = TTLCache(ttl_s=300)
        self.events: list = []      # StoreEvent
        self.deals: list = []       # DealPost

    async def _fetch(self, product: Product) -> list[AdapterOutcome]:
        return await self.cache.get_or_fetch(product.id, lambda: run_adapters(self.adapters, product, self.budget_s))

    async def find(self, query: str = "", include_used: bool = False, now: Optional[datetime] = None,
                   product_id: Optional[str] = None) -> DealReport:
        if product_id:
            product, how = self.index.products.get(product_id), "id"
        else:
            product, how = self.index.find(query)
        if product is None:
            return DealReport(None, how if not product_id else "unknown id")
        outcomes = await self._fetch(product)
        return self.assemble(product, how, outcomes, include_used, now)

    def assemble(self, product: Product, how: str, outcomes: list[AdapterOutcome], include_used: bool, now: Optional[datetime] = None) -> DealReport:
        report = DealReport(product, how, adapters=outcomes)
        quotes: list[Quote] = []
        for oc in outcomes:
            for l in oc.listings:
                m = match(product, l, self.index.fcache)
                if m.tier == Tier.REJECTED:
                    why = next((r for r in m.reasons if "words line up" not in r), "too little in common")
                    report.skipped.append(Skipped(l, m, why))
                    continue
                if not include_used and l.condition != Condition.NEW:
                    report.skipped.append(Skipped(l, m, f"{l.condition.value} (hidden)"))
                    continue
                policy = self.policies[l.retailer]
                is_verified = l.id in self.verified
                q = quote(l, product, m, policy, self.coupons, is_verified, self.verified.get(l.id), now)
                self.history.record(product.id, l.retailer, l.price)
                quotes.append(q)
        report.offers = rank_quotes(quotes, self.policies)
        for q in report.offers:
            report.history[q.listing.retailer] = self.history.series(product.id, q.listing.retailer)
        return report

    async def test_codes(self, listing: Listing, product: Product) -> ProbeResult:
        if self.probe is None:
            raise RuntimeError("no checkout probe configured")
        cands = [e.coupon for e in C.rank(self.coupons, listing, product, listing.shipping or 0.0) if e.applicable]
        res = await self.probe.try_codes(listing, product, cands)
        self.verified[listing.id] = res.winner
        self.cache.invalidate(product.id)
        return res
