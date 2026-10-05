"""SlompService: one entry point for the API, the CLI and the verification harness.

Validates inputs against the fixed lists, runs the pipelines, merges restaurant promotions and regular deals into
the local result, and caches results for 30 minutes so repeat views are instant.
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime
from typing import Optional

from . import industries as ind
from .config import Settings
from .db import Store as DB
from .http import PoliteClient
from .local import LocalDeals, LocalResult, window_for
from .models import City
from .online import OnlineDeals, OnlineResult
from .promos import RestaurantPromos
from .regulars import Regulars
from .reference import city as city_by_id, find_cities
from .sources.feeds import DealFeeds
from .sources.flipp import FlippClient
from .sources.prices import PriceSources
from .sources.stores import RestaurantLocator, StoreLocator

RESULT_TTL_S = 30 * 60
ONLINE_MAX = 100            # online deals kept per industry; requests take a slice
RADII = (10.0, 25.0, 50.0)


class InputError(ValueError):
    """An input outside the fixed lists. `choices` helps the caller fix it."""

    def __init__(self, message: str, choices: Optional[list] = None):
        super().__init__(message)
        self.choices = choices or []


def resolve_city(city_id: str) -> City:
    c = city_by_id(city_id)
    if c:
        return c
    near = [x.id for x in find_cities(city_id, 5)]
    raise InputError(f"unknown city {city_id!r}: choose a Texas city id from /api/v1/meta", near)


def resolve_industries(raw, online_only: bool = False) -> list[str]:
    ok, bad = ind.parse_ids(raw)
    if bad or not ok:
        raise InputError(f"unknown industries {bad}" if bad else "choose at least one industry", list(ind.IDS))
    return [i for i in dict.fromkeys(ok) if not online_only or ind.BY_ID[i].online]


class SlompService:
    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or Settings()
        self.db = DB(self.settings.db_path)
        self.http = PoliteClient(self.db, self.settings)
        self.flipp = FlippClient(self.http)
        self.stores = StoreLocator()
        self.feeds = DealFeeds(self.http)
        self.prices = PriceSources(self.http, self.flipp)
        self.local_deals = LocalDeals(self.flipp, self.stores)
        self.online_deals = OnlineDeals(self.feeds, self.prices, self.db)
        self.promos = RestaurantPromos(self.feeds, RestaurantLocator())
        self.regulars = Regulars(self.http, self.db, self.settings)
        self._cache: dict[tuple, tuple[float, object]] = {}
        self._locks: dict[tuple, asyncio.Lock] = {}

    async def aclose(self) -> None:
        await self.http.aclose()

    async def _cached(self, key: tuple, make):
        hit = self._cache.get(key)
        if hit and time.time() - hit[0] < RESULT_TTL_S:
            return hit[1]
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:                                  # one computation per key, however many callers
            hit = self._cache.get(key)
            if hit and time.time() - hit[0] < RESULT_TTL_S:
                return hit[1]
            value = await make()
            self._cache[key] = (time.time(), value)
            return value

    async def local(self, city_id: str, industries, radius_mi: float = 25.0,
                    now: Optional[datetime] = None, use_cache: bool = True) -> LocalResult:
        c = resolve_city(city_id)
        inds = resolve_industries(industries)
        radius = float(radius_mi)
        if radius not in RADII:
            raise InputError(f"radius must be one of {list(RADII)}", list(RADII))

        async def make() -> LocalResult:
            retail = [i for i in inds if i not in ind.LOCAL_ONLY]         # the industries weekly ads cover
            if retail:
                res = await self.local_deals.run(c, retail, radius, now, self.settings.window_days)
            else:
                start, end = window_for(c, now, self.settings.window_days)
                res = LocalResult(c, inds, radius, start, end)
            if "dining" in inds:
                promos, sources = await self.promos.near(c, radius, res.window_start, res.window_end, res.excluded)
                res.promotions = sorted(res.promotions + promos, key=lambda d: (-d.score, d.ends_in_days, d.title))
                res.sources += sources
            res.regulars, sources = await self.regulars.near(c, inds, radius, res.window_start, res.window_end,
                                                              res.excluded)
            res.sources += sources
            res.industries = inds
            return res
        if not use_cache or now is not None:
            return await make()
        return await self._cached(("local", c.id, tuple(sorted(inds)), radius), make)

    async def online(self, industries, limit: int = 25, compare: bool = True,
                     use_cache: bool = True) -> OnlineResult:
        inds = resolve_industries(industries, online_only=True)
        if not inds:
            raise InputError("Restaurants & Dining and Movies & Entertainment have local deals only; choose another "
                             "industry for online deals", [i for i in ind.IDS if ind.BY_ID[i].online])
        limit = max(1, min(int(limit), ONLINE_MAX))
        if not use_cache:
            return await self.online_deals.run(inds, limit=limit, compare=compare)
        # Cached per industry at the largest size, so "tech" and "tech,fashion", any limit, and the warm-up all
        # share one computation.
        parts = await asyncio.gather(*(
            self._cached(("online", i, compare),
                         lambda i=i: self.online_deals.run([i], limit=ONLINE_MAX, compare=compare)) for i in inds))
        merged = OnlineResult(inds)
        names: set[str] = set()
        for i, part in zip(inds, parts):
            merged.deals[i] = part.deals.get(i, [])[:limit]
            for k, v in part.excluded.items():          # shared feeds are counted once, not once per industry
                merged.excluded[k] = max(merged.excluded[k], v)
            merged.sources += [x for x in part.sources if x["name"] not in names]
            names |= {x["name"] for x in part.sources}
            merged.generated_at = min(merged.generated_at, part.generated_at)
        return merged

    async def warm(self) -> None:
        """Compute every industry's online deals in the background, one at a time (the price sources are slow by
        design), so the first visitor doesn't wait for them."""
        try:
            await self.regulars.all()                     # regular deals are the same for every city
        except Exception:                                 # warming is best-effort
            pass
        for i in ind.IDS:
            if ind.BY_ID[i].online:
                try:
                    await self.online(i)
                except Exception:
                    pass

    def health(self) -> dict:
        return {"hosts": self.http.health(), "store_map_built": self.stores.built(),
                "venue_map_built": self.regulars.venues.built(), "cached_results": len(self._cache)}
