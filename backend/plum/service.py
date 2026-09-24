"""Orchestration: one call turns a query into a ranked, explained set of offers."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

from . import coupons as C
from .adapters.base import Adapter, AdapterOutcome, run_adapters
from .adapters.checkout_probe import CheckoutProbe
from .cache import TTLCache
from .matching import ProductIndex, match
from .models import (Condition, DealPost, Listing, MatchResult, ProbeResult, Product, Quote, RetailerPolicy,
                     StoreEvent, Tier, utcnow)
from .pricing import quote, shipping_cost
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
    history: dict[str, list[float]] = field(default_factory=dict)   # retailer -> prices seen before this fetch

    @property
    def best(self) -> Optional[Quote]:
        return self.offers[0] if self.offers else None

    def is_low(self, q: Quote) -> bool:
        return is_period_low(q.listing.price, self.history.get(q.listing.retailer, []))


class PriceHistoryStore:
    """Observed prices per (product, retailer) over a rolling window. Swap for a time-series DB."""

    def __init__(self, window: timedelta = timedelta(days=90)):
        self.window = window
        self._d: dict[tuple[str, str], list[tuple[datetime, float]]] = {}

    def record(self, product_id: str, retailer: str, price: float, at: datetime) -> None:
        pts = self._d.setdefault((product_id, retailer), [])
        pts.append((at, price))
        pts[:] = [(t, p) for t, p in pts if t >= at - self.window]

    def series(self, product_id: str, retailer: str, before: datetime) -> list[float]:
        """Prices observed in the window ending just before `before`."""
        return [p for t, p in self._d.get((product_id, retailer), []) if before - self.window <= t < before]


@dataclass
class _Fetch:
    """One round of adapter calls. Prices are recorded once per fetch, however many searches reuse it."""
    outcomes: list[AdapterOutcome]
    at: datetime
    prior: Optional[dict[str, list[float]]] = None


class DealService:
    def __init__(self, products: list[Product], policies: dict[str, RetailerPolicy], adapters: list[Adapter],
                 coupons: list[C.Coupon], probe: Optional[CheckoutProbe] = None, budget_s: float = 1.4):
        self.index = ProductIndex(products)
        self.policies = policies
        self.adapters = adapters
        self.coupons = C.dedupe(coupons)                 # copies, so probe results never leak into the caller's data
        self.probe = probe
        self.budget_s = budget_s
        self.history = PriceHistoryStore()
        self.verified: dict[str, Optional[str]] = {}     # listing id -> code that worked (or None)
        self.cache: TTLCache[_Fetch] = TTLCache(ttl_s=300)
        self.events: list[StoreEvent] = []
        self.deals: list[DealPost] = []

    async def _fetch(self, product: Product) -> _Fetch:
        async def fresh() -> _Fetch:
            return _Fetch(await run_adapters(self.adapters, product, self.budget_s), utcnow())
        return await self.cache.get_or_fetch(product.id, fresh)

    async def find(self, query: str = "", include_used: bool = False, now: Optional[datetime] = None,
                   product_id: Optional[str] = None) -> DealReport:
        if product_id:
            product, how = self.index.products.get(product_id), "id"
        else:
            product, how = self.index.find(query)
        if product is None:
            return DealReport(None, how if not product_id else "unknown id")
        return self.assemble(product, how, await self._fetch(product), include_used, now)

    async def listing(self, product_id: str, listing_id: str) -> tuple[Optional[Product], Optional[Listing]]:
        """A listing from the product's current results (what a probe request refers to)."""
        product = self.index.products.get(product_id)
        if product is None:
            return None, None
        fetch = await self._fetch(product)
        return product, next((l for o in fetch.outcomes for l in o.listings if l.id == listing_id), None)

    def assemble(self, product: Product, how: str, fetch: _Fetch, include_used: bool,
                 now: Optional[datetime] = None) -> DealReport:
        report = DealReport(product, how, adapters=fetch.outcomes)
        matched: list[tuple[Listing, MatchResult]] = []
        for oc in fetch.outcomes:
            for l in oc.listings:
                m = match(product, l)
                if m.tier == Tier.REJECTED:
                    why = next((r for r in m.reasons if "words line up" not in r), "too little in common")
                    report.skipped.append(Skipped(l, m, why))
                elif l.retailer not in self.policies:
                    report.skipped.append(Skipped(l, m, "unknown store (no shipping policy)"))
                else:
                    matched.append((l, m))
        if fetch.prior is None:        # first look at this fetch: snapshot what came before, then record it
            fetch.prior = {r: self.history.series(product.id, r, fetch.at) for r in {l.retailer for l, _ in matched}}
            for l, _ in matched:
                self.history.record(product.id, l.retailer, l.price, fetch.at)
        report.history = fetch.prior
        quotes: list[Quote] = []
        for l, m in matched:
            if not include_used and l.condition != Condition.NEW:
                report.skipped.append(Skipped(l, m, f"{l.condition.value} (hidden)"))
                continue
            quotes.append(quote(l, product, m, self.policies[l.retailer], self.coupons, l.id in self.verified,
                                self.verified.get(l.id), now))
        report.offers = rank_quotes(quotes, self.policies)
        return report

    async def test_codes(self, listing: Listing, product: Product) -> ProbeResult:
        if self.probe is None:
            raise RuntimeError("no checkout probe configured")
        policy = self.policies.get(listing.retailer)
        ship = shipping_cost(policy, listing) if policy else (listing.shipping or 0.0)
        cands = [e.coupon for e in C.rank(self.coupons, listing, product, ship) if e.applicable]
        res = await self.probe.try_codes(listing, product, cands)
        self.verified[listing.id] = res.winner
        self.cache.invalidate(product.id)
        return res
