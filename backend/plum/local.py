"""Local deals: a city or ZIP -> this week's weekly-ad deals at stores near it.

Pipeline: geocode -> ads for the ZIP -> items -> drop junk, expired, not-yet-started and duplicate items
          -> rank by headline discount -> read the full ad record of the leaders -> re-rank on the exact terms
          -> attach the nearest mapped store -> report, with every dropped item counted by reason.

Full records are read until the ranking is provably stable. Exact terms only ever lower a score (a BOGO's effective
saving is below its headline percent, a hedged "up to" saving is halved), apart from rounding in the headline percent,
so once the N-th best exact score beats the next unread headline score by more than that rounding, nothing unread can
enter the top N.
"""
from __future__ import annotations

import asyncio
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Iterable, Optional

from urllib.parse import urlsplit

from .adapters.flipp import FlippClient, detailed_deal, listing_deal, search_deal
from .adapters.osm import OVERPASS_MIRRORS, StoreLocator
from .geo import KM_PER_MILE, Geocoder
from .models import Flyer, LocalDeal, Place, Presence, StorePresence, utcnow
from .net import DiskCache, HttpClient, HttpError
from .terms import MAX_PLAUSIBLE_PCT
from .textfeatures import features, near_code, tokens

MIN_PCT = 5.0              # smaller "savings" are noise
ROUNDING = 1.0             # headline percents are rounded; exact ones can exceed them by this much
# Seconds between request starts per host: Nominatim's and Overpass's policies ask for about one a second.
POLITE_INTERVALS = {"nominatim.openstreetmap.org": 1.1, "backflipp.wishabi.com": 0.12,
                    **{urlsplit(u).netloc: 1.0 for u in OVERPASS_MIRRORS}}
# Words that mark an accessory for the thing searched for (a "case" for AirPods is not AirPods).
ACCESSORY_WORDS = {"case", "cover", "skin", "protector", "charger", "cable", "adapter", "replacement", "compatible",
                   "strap", "mount", "earpads", "cushions", "sleeve", "holder"}


@dataclass
class SourceStatus:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class LocalReport:
    place: Place
    radius_km: float
    generated_at: datetime
    deals: list[LocalDeal] = field(default_factory=list)      # firm price, saving vs the store's own regular price
    promos: list[LocalDeal] = field(default_factory=list)     # % off, BOGO, hedged or unreferenced savings
    flyers: list[Flyer] = field(default_factory=list)         # ads running now
    upcoming: list[Flyer] = field(default_factory=list)       # ads that haven't started yet
    presence: dict[str, StorePresence] = field(default_factory=dict)
    skipped: Counter = field(default_factory=Counter)         # reason -> items dropped for it
    sources: list[SourceStatus] = field(default_factory=list)
    items_seen: int = 0
    details_read: int = 0
    complete: bool = True      # False when the full-record budget ran out before the ranking was provably stable


@dataclass
class SearchReport:
    query: str
    place: Place
    radius_km: float
    generated_at: datetime
    results: list[LocalDeal] = field(default_factory=list)    # cheapest unit price first, grouped by unit
    presence: dict[str, StorePresence] = field(default_factory=dict)
    skipped: Counter = field(default_factory=Counter)
    sources: list[SourceStatus] = field(default_factory=list)


def score(d: LocalDeal) -> float:
    """Effective percent saved. A hedged saving ("up to", compare-at, no stated regular price) counts half, so a
    promised 30% outranks an "up to 50%"."""
    pct = d.terms.pct_off or 0.0
    return pct / 2 if d.terms.hedge else pct


def is_firm_deal(d: LocalDeal) -> bool:
    """A price you can walk in and pay, with a saving the ad states outright."""
    t = d.terms
    return t.price is not None and not t.hedge and (t.pct_off or 0) >= MIN_PCT


def top(deals: Iterable[LocalDeal], limit: int, per_store: int) -> list[LocalDeal]:
    out: list[LocalDeal] = []
    per: Counter = Counter()
    for d in sorted(deals, key=lambda d: (-score(d), -(d.terms.dollars_off or 0), d.merchant, d.title)):
        if per[d.merchant] < per_store:
            out.append(d)
            per[d.merchant] += 1
            if len(out) == limit:
                break
    return out


def _word_match(w: str, t: str) -> bool:
    return t == w or t in (w + "s", w + "es") or w in (t + "s", t + "es") or (w.endswith("y") and t == w[:-1] + "ies")


def matches_query(query: str, title: str) -> str:
    """Why `title` is not what `query` asks for, or "" if it is."""
    q, t = tokens(query), tokens(title)
    qc, tc = features(query).codes, features(title).codes
    if any(near_code(a, b) for a in qc for b in tc) and not qc & tc:
        return "a different model"                 # XM6 when you asked for XM5
    if any(not any(_word_match(w, x) for x in t) for w in q):
        return "doesn't match the search"
    acc = next((x for x in t if x in ACCESSORY_WORDS or x.rstrip("s") in ACCESSORY_WORDS), None)
    if acc and not any(_word_match(acc, w) for w in q):
        return "an accessory, not the item"
    return ""


def _dedupe_key(d: LocalDeal) -> tuple:
    return d.merchant, " ".join(tokens(d.title)), d.terms.price, d.terms.quantity, d.terms.pct_off


def _timing(d: LocalDeal, now: datetime) -> str:
    if d.valid_to < now:
        return "ad has ended"
    if d.valid_from > now:
        return "ad hasn't started yet"
    return ""


class LocalDealService:
    def __init__(self, http: HttpClient, *, detail_budget: int = 200, batch: int = 8,
                 clock: Callable[[], datetime] = utcnow):
        self.http = http
        self.geocoder = Geocoder(http)
        self.flipp = FlippClient(http)
        self.stores = StoreLocator(http)
        self.detail_budget = detail_budget
        self.batch = batch
        self.clock = clock

    @classmethod
    def live(cls, *, cache: bool = True, **kw) -> "LocalDealService":
        return cls(HttpClient(cache=DiskCache() if cache else None, min_interval_s=POLITE_INTERVALS), **kw)

    async def aclose(self) -> None:
        await self.http.aclose()

    # --- sources ---------------------------------------------------------------------------------------------------

    async def _presence(self, place: Place, merchants: set[str], radius_km: float,
                        sources: list[SourceStatus]) -> dict[str, StorePresence]:
        try:
            pres = await self.stores.presence(place, merchants, radius_km)
        except HttpError as e:
            sources.append(SourceStatus(self.stores.name, False, f"{e}; store locations not checked"))
            return {m: StorePresence(m, Presence.UNCHECKED) for m in merchants}
        near = sum(p.status == Presence.CONFIRMED for p in pres.values())
        sources.append(SourceStatus(self.stores.name, True, f"{near} of {len(pres)} merchants have a mapped store in range"))
        return pres

    async def _items(self, flyers: list[Flyer], rep: LocalReport) -> list[tuple[Flyer, dict]]:
        async def one(f: Flyer) -> list[tuple[Flyer, dict]]:
            try:
                return [(f, raw) for raw in await self.flipp.flyer_items(f.id)]
            except HttpError as e:
                rep.sources.append(SourceStatus(f"{self.flipp.name}: {f.merchant}", False, str(e)))
                return []
        return [x for chunk in await asyncio.gather(*(one(f) for f in flyers)) for x in chunk]

    async def _detail(self, d: LocalDeal, flyer: Optional[Flyer]) -> tuple[Optional[LocalDeal], str]:
        try:
            raw = await self.flipp.item(d.id.split(":", 1)[1])
        except HttpError:
            return None, "couldn't read the full ad record"
        return detailed_deal(raw, flyer) if raw else (None, "full ad record missing")

    # --- deals -----------------------------------------------------------------------------------------------------

    async def deals(self, where: str, *, radius_mi: float = 25.0, limit: int = 25, promo_limit: int = 10,
                    per_store: int = 3, merchants: Iterable[str] = (), category: str = "",
                    confirmed_only: bool = False) -> LocalReport:
        now = self.clock()
        place = await self.geocoder.resolve(where)
        rep = LocalReport(place, radius_mi * KM_PER_MILE, now)
        rep.sources.append(SourceStatus(place.source, True, f"{place.name} -> ZIP {place.postal_code}"))
        try:
            flyers = await self.flipp.flyers(place.postal_code)
        except HttpError as e:
            rep.sources.append(SourceStatus(self.flipp.name, False, str(e)))
            return rep
        wanted = {m.lower() for m in merchants}
        flyers = [f for f in flyers if (not wanted or f.merchant.lower() in wanted)
                  and (not category or any(category.lower() == c.lower() for c in f.categories))]
        rep.flyers = [f for f in flyers if f.active(now)]
        rep.upcoming = [f for f in flyers if f.valid_from > now]
        rep.sources.append(SourceStatus(self.flipp.name, True, f"{len(rep.flyers)} ads running for ZIP {place.postal_code}"
                                        f" ({len(rep.upcoming)} start later)"))
        if not rep.flyers:
            return rep
        items, rep.presence = await asyncio.gather(
            self._items(rep.flyers, rep),
            self._presence(place, {f.merchant for f in rep.flyers}, rep.radius_km, rep.sources))

        by_flyer = {f.id: f for f in rep.flyers}
        seen: set[tuple] = set()
        candidates: list[LocalDeal] = []
        for flyer, raw in items:
            rep.items_seen += 1
            d, why = listing_deal(raw, flyer)
            why = why or _timing(d, now)
            if not why and confirmed_only and rep.presence[d.merchant].status != Presence.CONFIRMED:
                why = "no store mapped in range"
            if not why and not d.terms.pct_off:
                why = "price only, no saving stated" if d.terms.price is not None else "no price or saving in the ad"
            if not why and _dedupe_key(d) in seen:
                why = "same item in another ad"
            if why:
                rep.skipped[why] += 1
                continue
            seen.add(_dedupe_key(d))
            candidates.append(d)

        rep.deals, rep.promos, rep.complete = await self._rank(candidates, by_flyer, limit, promo_limit, per_store, rep)
        for d in rep.deals + rep.promos:
            self._annotate(d, rep)
        return rep

    async def _rank(self, cands: list[LocalDeal], flyers: dict[int, Flyer], limit: int, promo_limit: int,
                    per_store: int, rep: LocalReport) -> tuple[list[LocalDeal], list[LocalDeal], bool]:
        """Firm deals come from items listed with a price, promotions from items without one. An item whose full
        record turns out hedged or compare-at moves to the promotions list."""
        firm: list[LocalDeal] = []
        loose: list[LocalDeal] = []
        by_score = sorted(cands, key=score, reverse=True)
        stable = await self._read([c for c in by_score if c.terms.price is not None], firm, limit, per_store,
                                  firm, loose, flyers, rep)
        stable &= await self._read([c for c in by_score if c.terms.price is None], loose, promo_limit, per_store,
                                   firm, loose, flyers, rep)
        return top(firm, limit, per_store), top(loose, promo_limit, per_store), stable

    async def _read(self, pool: list[LocalDeal], target: list[LocalDeal], n: int, per_store: int,
                    firm: list[LocalDeal], loose: list[LocalDeal], flyers: dict[int, Flyer], rep: LocalReport) -> bool:
        """Read full records from `pool` (best headline first) until `target`'s top n can't change.

        Returns True when that point is reached, False when the read budget ran out first."""
        if n <= 0:
            return True
        i = 0
        while True:
            best = top(target, n, per_store)
            floor = score(best[-1]) if len(best) == n else None
            batch: list[LocalDeal] = []
            while i < len(pool) and len(batch) < self.batch:
                c = pool[i]
                if floor is not None and floor > score(c) + ROUNDING:
                    return True                  # the pool is sorted, so nothing further down can enter either
                i += 1
                mine = sorted((score(d) for d in target if d.merchant == c.merchant), reverse=True)[:per_store]
                if len(mine) == per_store and mine[-1] > score(c) + ROUNDING:
                    continue                     # can't beat this merchant's own best `per_store`
                batch.append(c)
            if not batch:
                return True
            room = self.detail_budget - rep.details_read
            if room <= 0:
                return False
            batch = batch[:room]
            rep.details_read += len(batch)
            for d, why in await asyncio.gather(*(self._detail(c, flyers.get(c.flyer_id)) for c in batch)):
                if d is not None and (d.terms.pct_off or 0) > MAX_PLAUSIBLE_PCT:
                    why = "implausible discount"
                elif d is not None and not d.terms.pct_off:
                    why = "no saving in the full ad"
                if why:
                    rep.skipped[why] += 1
                elif is_firm_deal(d):
                    firm.append(d)
                elif score(d) >= MIN_PCT:
                    loose.append(d)
                else:
                    rep.skipped["saving too small"] += 1

    def _annotate(self, d: LocalDeal, rep: "LocalReport | SearchReport") -> None:
        p = rep.presence.get(d.merchant)
        miles = rep.radius_km / KM_PER_MILE
        if p is None or p.status == Presence.UNCHECKED:
            d.flags.append("store locations weren't checked")
        elif p.status == Presence.CONFIRMED:
            d.store = p.nearest
        elif p.status == Presence.FAR and p.nearest:
            d.flags.append(f"nearest mapped {d.merchant} is {p.nearest.distance_km / KM_PER_MILE:.0f} mi away"
                           f" (maps can be incomplete)")
        else:
            d.flags.append(f"no {d.merchant} mapped within {miles:.0f} mi; check the store locator")

    # --- search ----------------------------------------------------------------------------------------------------

    async def search(self, query: str, where: str, *, radius_mi: float = 25.0, limit: int = 20,
                     confirmed_only: bool = False) -> SearchReport:
        now = self.clock()
        place = await self.geocoder.resolve(where)
        rep = SearchReport(query, place, radius_mi * KM_PER_MILE, now)
        rep.sources.append(SourceStatus(place.source, True, f"{place.name} -> ZIP {place.postal_code}"))
        try:
            raws = await self.flipp.search(place.postal_code, query)
        except HttpError as e:
            rep.sources.append(SourceStatus(self.flipp.name, False, str(e)))
            return rep
        rep.sources.append(SourceStatus(self.flipp.name, True, f"{len(raws)} ad items for {query!r}"))
        found: list[LocalDeal] = []
        seen: set[tuple] = set()
        for raw in raws:
            d, why = search_deal(raw)
            why = why or _timing(d, now) or matches_query(query, d.title)
            if not why and d.terms.price is None:
                why = "no price in the ad"
            if not why and _dedupe_key(d) in seen:
                why = "same item in another ad"
            if why:
                rep.skipped[why] += 1
                continue
            seen.add(_dedupe_key(d))
            found.append(d)
        rep.presence = await self._presence(place, {d.merchant for d in found}, rep.radius_km, rep.sources)
        if confirmed_only:
            kept = [d for d in found if rep.presence[d.merchant].status == Presence.CONFIRMED]
            rep.skipped["no store mapped in range"] += len(found) - len(kept)
            found = kept
        # Read the full record of what we'll show: exact conditions and the retailer's own link.
        shown = _by_unit_price(found)[:limit]
        exact = [e if e is not None else d for d, (e, _) in zip(shown, await asyncio.gather(
            *(self._detail(d, None) for d in shown)))]
        unpriced = sum(d.terms.price is None for d in exact)          # e.g. a "$5 OFF" that had been read as a price
        if unpriced:
            rep.skipped["no price in the full ad"] += unpriced
        rep.results = _by_unit_price([d for d in exact if d.terms.price is not None])
        for d in rep.results:
            self._annotate(d, rep)
        return rep


def _by_unit_price(deals: list[LocalDeal]) -> list[LocalDeal]:
    """Cheapest unit price first, keeping per-lb and per-item prices apart (the most common unit leads)."""
    common = Counter(d.terms.unit for d in deals).most_common(1)
    lead = common[0][0] if common else ""
    return sorted(deals, key=lambda d: (d.terms.unit != lead, d.terms.unit, d.terms.hedge != "",
                                        d.terms.unit_price or 0.0, d.merchant))
