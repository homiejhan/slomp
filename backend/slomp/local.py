"""Output 1: every deal at stores near a Texas city that is valid at some point in the next 7 days.

city -> ZIP -> ads -> items (+ taxonomy) -> terms -> industry -> stores -> window -> rank -> detail pass.
"""
from __future__ import annotations

import asyncio
import hashlib
import re
from collections import Counter
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from . import industries as ind
from .geo import ad_end_local, ad_start_local, days_between, miles, parse_time
from .http import FetchError
from .models import BASIS_WEIGHT, City, LocalDeal, Merchant, Store, Terms
from .reference import merchant as merchant_entry, merchants, norm
from .sources.flipp import FlippClient, Flyer, is_product_link, item_url, junk_reason
from .sources.shops import MIN_PCT, PER_SITE, ShopSite, ShopSites, SiteRead, near as sites_near, same_name
from .sources.stores import MAX_RADIUS_MI, StoreLocator, StoreMap
from .terms import ad_terms, clean

DETAIL_TOP_N = 24           # full records read for the leading deals of each industry (the first page shown)
DETAIL_ROUNDS = 3           # re-read the lead this many times as fine print reshuffles it
PER_MERCHANT_SAMPLE = 1     # full records read per ad to learn whether its items come from the retailer's feed


@dataclass
class LocalResult:
    city: City
    industries: list[str]
    radius_mi: float
    window_start: datetime
    window_end: datetime
    deals: list[LocalDeal] = field(default_factory=list)
    promotions: list[LocalDeal] = field(default_factory=list)
    unconfirmed: list[LocalDeal] = field(default_factory=list)
    regulars: list[LocalDeal] = field(default_factory=list)          # standing offers that repeat on a schedule
    excluded: Counter = field(default_factory=Counter)
    excluded_items: dict[int, str] = field(default_factory=dict)     # item id -> why it isn't shown
    merchants: list[dict] = field(default_factory=list)
    sources: list[dict] = field(default_factory=list)

    def all_deals(self) -> list[LocalDeal]:
        return self.deals + self.promotions + self.unconfirmed

    def to_dict(self) -> dict:
        return {
            "city": {"id": self.city.id, "name": self.city.name, "county": self.city.county, "zip": self.city.zip,
                     "tz": self.city.tz, "lat": self.city.lat, "lon": self.city.lon},
            "industries": self.industries, "radius_mi": self.radius_mi,
            "window": {"start": self.window_start.isoformat(), "end": self.window_end.isoformat()},
            "counts": {"deals": len(self.deals), "promotions": len(self.promotions),
                       "unconfirmed": len(self.unconfirmed), "regulars": len(self.regulars)},
            "deals": [d.to_dict() for d in self.deals],
            "promotions": [d.to_dict() for d in self.promotions],
            "unconfirmed": [d.to_dict() for d in self.unconfirmed],
            "regulars": [d.to_dict() for d in self.regulars],
            "excluded": dict(self.excluded.most_common()),
            "merchants": self.merchants, "sources": self.sources,
            # when nothing is close enough: which advertising stores a wider radius would reach
            "beyond_radius": sorted(({"merchant": m["merchant"], "nearest_mi": m["nearest_mi"]} for m in self.merchants
                                     if m["status"] == "far" and m["nearest_mi"]), key=lambda x: x["nearest_mi"]),
        }


def window_for(city: City, now: Optional[datetime], days: int) -> tuple[datetime, datetime]:
    now = (now or datetime.now(ZoneInfo(city.tz))).astimezone(ZoneInfo(city.tz))
    return now, now + timedelta(days=days)


def score(d: LocalDeal) -> float:
    t = d.terms
    pct = t.pct or 0.0
    w = BASIS_WEIGHT.get(t.basis, 0.0)
    if t.hedge:
        w *= 0.5
    conf = 1.0 - 0.1 * len([c for c in t.conditions if c not in ("in store only",)])
    return round(pct * w * max(conf, 0.5), 2)


def _merge(listing: dict, hit: Optional[dict]) -> dict:
    """One record from the ad listing (price, headline %, dates) and the search hit (taxonomy, original price,
    sale story, price text). The listing wins on price and dates: it is the ad as published."""
    raw = dict(hit or {})
    for k in ("id", "flyer_id", "name", "brand", "valid_from", "valid_to", "cutout_image_url", "discount",
              "display_type"):
        if listing.get(k) not in (None, ""):
            raw[k] = listing[k]
    if listing.get("price") not in (None, ""):
        raw["current_price"] = listing["price"]
    return raw


def labelled_items(m: Merchant, items) -> list[tuple[str, str, str, str]]:
    """A merchant's search hits whose industry is the source's own label (the taxonomy, or a specialty store's
    line), as examples to learn industry words from: one per distinct product name at the merchant."""
    out = []
    for raw in items:
        l1 = raw.get("_L1")
        if not l1 and not m.exclusive:
            continue
        title, brand = clean(raw.get("name")), clean(raw.get("brand"))
        c = ind.classify_ad_item(l1, raw.get("_L2"), title, brand, m.industries, m.exclusive, m.sells, m.food)
        row = ind.example("flipp", f"{norm(m.name)}|{norm(f'{brand} {title}')[:120]}", [brand, title], c.industries) \
            if ind.source_label(c.rule, l1) else None
        if row:
            out.append(row)
    return out


# --- the sales stores' own websites state (sources/shops.py) ---------------------------------------------------
SITE_DAYS = 2               # a price read on a store's site is shown on the day of the read and the next; read daily
SITES_PER_SEARCH = 40       # a server search reads at most this many stores' sites it has no fresh copy of
CENTRAL = ZoneInfo("America/Chicago")


def site_merchant(site: ShopSite) -> Merchant:
    """A store found on the map, as a merchant: what its kind of shop sells is its line. Named as the shops are,
    unless that is the name of a chain in the registry (then its site says which store it is)."""
    taken = any(norm(site.name) in {norm(n) for n in (m.name, *m.flipp, *m.osm_names)} for m in merchants())
    name = f"{site.name} ({site.host})" if taken else site.name
    return Merchant(name=name, flipp=[], wikidata=[], osm_names=[], domains=[site.host],
                    industries=list(site.industries), sells=list(site.industries), food="grocery" in site.industries)


def site_deals(site: ShopSite, read: Optional[SiteRead]) -> list[LocalDeal]:
    """The deals a store's own site states, the same for every city (the shop nearest a city is attached later):
    a product on sale by at least MIN_PCT, filed by its words and then by what the store sells, at most PER_SITE of
    them, the biggest savings first. Its dates run from the read for SITE_DAYS."""
    if not read or not read.items or not read.read_at:
        return []
    m = site_merchant(site)
    # From midnight of the day it was read to the end of the last day it is shown, as an ad states its days
    day = datetime.fromtimestamp(read.read_at, CENTRAL).date()
    last = day + timedelta(days=SITE_DAYS - 1)
    vf = datetime(day.year, day.month, day.day, tzinfo=CENTRAL)
    vt = datetime(last.year, last.month, last.day, 23, 59, 59, tzinfo=CENTRAL)
    out: list[LocalDeal] = []
    for it in read.items:
        if it.pct < MIN_PCT or it.pct >= 95:
            continue
        cls = ind.classify_ad_item(None, None, it.title, it.words, m.industries, False, m.sells, m.food)
        if not cls.industries:
            continue
        conditions = ["price on the store's website"] + (["some sizes or colors only"] if it.options else [])
        terms = Terms(price=it.price, regular=it.regular, savings=round(it.regular - it.price, 2), pct=it.pct,
                      basis=it.basis, conditions=conditions)
        iid = int(hashlib.sha1(f"{site.host}|{it.url}|{it.title}".encode()).hexdigest()[:12], 16)
        d = LocalDeal(id=f"site:{iid}", item_id=iid, flyer_id=site.key, title=it.title, merchant=m.name, brand="",
                      industries=cls.industries, industry_rule=cls.rule, category=it.words[:80], terms=terms,
                      valid_from=vf, valid_to=vt, source_url=it.url, retailer_url=it.url, image_url=it.image,
                      detailed=True, raw={"site": site.host, "platform": read.platform})
        d.score = score(d)
        out.append(d)
    out.sort(key=lambda d: (-d.score, -(d.terms.savings or 0), d.title))
    seen, kept = set(), []
    for d in out:                                   # one product in two sizes is one deal
        if norm(d.title) not in seen:
            seen.add(norm(d.title))
            kept.append(d)
    return kept[:PER_SITE]


def site_stores(site: ShopSite, merchant: str, city: City) -> list[Store]:
    """A site's shops within MAX_RADIUS_MI of a city, nearest first, as StoreLocator.near gives a chain's."""
    rows = sorted(((round(miles(city.lat, city.lon, r[0], r[1]), 1), r) for r in site.locations), key=lambda x: x[0])
    return [Store(merchant=merchant, name=r[2] or merchant, lat=r[0], lon=r[1], address=r[3], distance_mi=d,
                  source="osm", ref=r[4]) for d, r in rows if d <= MAX_RADIUS_MI]


class LocalDeals:
    def __init__(self, flipp: FlippClient, stores: StoreLocator, shops: Optional[ShopSites] = None):
        self.flipp, self.stores, self.shops = flipp, stores, shops
        self._feed_cache: dict[int, bool] = {}

    async def run(self, city: City, industries: list[str], radius_mi: float = 25.0,
                  now: Optional[datetime] = None, days: int = 7) -> LocalResult:
        start, end = window_for(city, now, days)
        res = LocalResult(city, industries, radius_mi, start, end)
        wanted = set(industries)
        try:
            flyers = await self.flipp.flyers(city.zip)
            res.sources.append({"name": "Flipp weekly ads", "ok": True, "ads": len(flyers)})
        except FetchError as e:
            res.sources.append({"name": "Flipp weekly ads", "ok": False, "error": e.reason})
            return res

        live: list[Flyer] = []
        for f in flyers:
            if min(ad_end_local(f.valid_to, city.tz), f.valid_to) < start or ad_start_local(f.valid_from, city.tz) > end:
                res.excluded["ad outside the 7-day window"] += 1
            else:
                live.append(f)
        entries = {f.merchant: merchant_entry(f.merchant) for f in live}

        store_map: StoreMap = self.stores.near(city, list({m.name: m for m in entries.values()}.values()))
        res.sources.append({"name": "OpenStreetMap stores", "ok": store_map.source_ok, "built": store_map.built,
                            **({"error": store_map.error} if store_map.error else {})})
        sites: dict[str, ShopSite] = {}
        if self.shops is not None:
            sites, err = await self.shops.directory()
            res.sources.append({"name": "Stores' own websites", "ok": not err, "sites": len(sites),
                                **({"error": err} if err else {})})
            # A merchant with an ad on Flipp that the store registry doesn't list: its shops, if the map has them
            for m in {m.name: m for m in entries.values()}.values():
                if not store_map.stores.get(m.name) and not self.stores.known(m):
                    s = same_name(sites, m.name)
                    if s:
                        store_map.stores[m.name] = site_stores(s, m.name, city)
        ads_of: dict[str, set[int]] = {}
        for f in live:
            ads_of.setdefault(f.merchant, set()).add(f.id)
        hits_by_merchant = await self._merchant_hits(city.zip, sorted(entries), ads_of)
        listings = await asyncio.gather(*(self._listing(f) for f in live))

        candidates: list[LocalDeal] = []
        seen: dict[tuple, LocalDeal] = {}
        for flyer, items in zip(live, listings):
            m = entries[flyer.merchant]
            hits = hits_by_merchant.get(flyer.merchant, {})
            for raw_listing in items:
                why = junk_reason(raw_listing)
                if why:
                    res.excluded[why] += 1
                    continue
                raw = _merge(raw_listing, hits.get(raw_listing.get("id")))
                deal = self._deal(raw, flyer, m, city, start, end, res)
                if deal is None:
                    continue
                if not wanted & set(deal.industries):
                    res.excluded["other industry"] += 1
                    res.excluded_items[deal.item_id] = f"other industry ({','.join(deal.industries)}; {deal.industry_rule})"
                    continue
                key = (m.name, norm(deal.title), deal.terms.price, deal.terms.pct)
                if key in seen:
                    # The same item at the same price in two overlapping ads: show the copy that runs longer, as is.
                    keep = seen[key]
                    res.excluded["same item in another ad"] += 1
                    if deal.valid_to > keep.valid_to:
                        candidates[candidates.index(keep)] = deal
                        seen[key] = deal
                        keep, deal = deal, keep
                    res.excluded_items[deal.item_id] = f"same item in another ad ({keep.item_id})"
                    continue
                seen[key] = deal
                candidates.append(deal)

        await self._learn_feeds(candidates)
        candidates += await self._site_candidates(sites, city, wanted, start, end, store_map, seen, res)
        for d in candidates:
            self._attach_store(d, entries[d.merchant] if d.merchant in entries else merchant_entry(d.merchant),
                               store_map, radius_mi, res)
        kept = [d for d in candidates if d.store_status in ("nearby", "unmapped")]
        for d in kept:
            d.score = score(d)
        order = lambda d: (-d.score, -(d.terms.savings or 0), d.title)     # noqa: E731
        kept.sort(key=order)
        for _ in range(DETAIL_ROUNDS):          # fine print can lower a deal, which lets unread ones into the lead
            if not await self._detail_pass(kept, wanted):
                break
            kept.sort(key=order)

        for d in kept:
            if d.store_status == "unmapped":
                res.unconfirmed.append(d)
            elif d.kind == "promotion":
                res.promotions.append(d)
            else:
                res.deals.append(d)
        res.merchants = self._merchant_table(entries, store_map, radius_mi)
        return res

    # -- fetching -----------------------------------------------------------------------------------------------
    async def _listing(self, flyer: Flyer) -> list[dict]:
        try:
            return await self.flipp.flyer_items(flyer.id)
        except FetchError:
            return []

    async def _merchant_hits(self, zip_code: str, merchants: list[str],
                             ads_of: Optional[dict[str, set[int]]] = None) -> dict[str, dict[int, dict]]:
        async def one(name: str) -> tuple[str, dict[int, dict]]:
            try:
                items = await self.flipp.merchant_items(zip_code, name, (ads_of or {}).get(name, ()))
                return name, {i.get("id"): i for i in items if i.get("id")}
            except FetchError:
                return name, {}
        return dict(await asyncio.gather(*(one(n) for n in merchants)))

    async def _site_candidates(self, sites: dict[str, ShopSite], city: City, wanted: set[str], start: datetime,
                               end: datetime, store_map: StoreMap, seen: dict, res: LocalResult) -> list[LocalDeal]:
        """The deals the own sites of the stores within MAX_RADIUS_MI state, read and kept as the published site's
        build keeps them (site.site_ads): each site is one more ad, its shops its stores."""
        if self.shops is None or not sites:
            return []
        nearby = sites_near(sites, city.lat, city.lon, MAX_RADIUS_MI)
        reads = await self.shops.read_all(nearby, budget=SITES_PER_SEARCH)
        out: list[LocalDeal] = []
        for s in sorted(nearby, key=lambda s: s.key):
            deals = site_deals(s, reads.get(s.host))
            if not deals:
                continue
            store_map.stores[deals[0].merchant] = site_stores(s, deals[0].merchant, city)
            vf, vt = deals[0].valid_from, deals[0].valid_to
            if min(ad_end_local(vt, city.tz), vt) < start or ad_start_local(vf, city.tz) > end:
                res.excluded["ad outside the 7-day window"] += 1
                continue
            vf_l, vt_l = ad_start_local(vf, city.tz), ad_end_local(vt, city.tz)
            for d in deals:
                if not wanted & set(d.industries):
                    res.excluded["other industry"] += 1
                    res.excluded_items[d.item_id] = f"other industry ({','.join(d.industries)}; {d.industry_rule})"
                    continue
                key = (d.merchant, norm(d.title), d.terms.price, d.terms.pct)
                if key in seen:
                    res.excluded["same item in another ad"] += 1
                    continue
                seen[key] = d
                out.append(replace(d, valid_from=vf_l, valid_to=vt_l,
                                   starts_in_days=max(0, days_between(start, vf_l, city.tz)),
                                   ends_in_days=days_between(start, vt_l, city.tz)))
        return out

    # -- one item -----------------------------------------------------------------------------------------------
    def _deal(self, raw: dict, flyer: Flyer, m: Merchant, city: City, start: datetime, end: datetime,
              res: LocalResult) -> Optional[LocalDeal]:
        vf = parse_time(raw.get("valid_from")) or flyer.valid_from
        vt = parse_time(raw.get("valid_to")) or flyer.valid_to
        vf_l, vt_l = ad_start_local(vf, city.tz), ad_end_local(vt, city.tz)
        iid = int(raw.get("id") or 0)
        # Flipp writes "through Oct 4" as 11:59 PM Eastern and pulls the item then (10:59 PM Central): the item is
        # gone from the source at the earlier of that instant and the end of the day locally.
        if min(vt_l, vt) < start:
            return self._skip(res, iid, "item already ended")
        if vf_l > end:
            return self._skip(res, iid, "item starts after the 7-day window")
        title = clean(raw.get("name"))
        brand = clean(raw.get("brand"))
        cls = ind.classify_ad_item(raw.get("_L1"), raw.get("_L2"), title, brand, m.industries, m.exclusive,
                                   m.sells, m.food)
        if not cls.industries:
            return self._skip(res, iid, "no industry")
        terms = ad_terms(raw, feed=self._feed_cache.get(flyer.id, False), merchant_membership=m.membership)
        if terms.rejected:
            return self._skip(res, iid, f"implausible saving ({terms.rejected})")
        if terms.basis == "none" and not terms.promo:
            return self._skip(res, iid, "ad price with no saving stated")
        if not (terms.pct or terms.savings):
            return self._skip(res, iid, "no saving amount")
        return LocalDeal(
            id=f"flipp:{raw.get('id')}", item_id=int(raw.get("id")), flyer_id=flyer.id, title=title,
            merchant=m.name, brand=brand, industries=cls.industries, industry_rule=cls.rule, category=cls.category,
            terms=terms, valid_from=vf_l, valid_to=vt_l, source_url=item_url(raw.get("id")),
            # the item as it appears in the ad (Flipp has no separate product photo); always over https
            image_url=str(raw.get("cutout_image_url") or raw.get("clean_image_url") or "").replace("http://", "https://", 1),
            starts_in_days=max(0, days_between(start, vf_l, city.tz)), ends_in_days=days_between(start, vt_l, city.tz),
            raw=raw)

    @staticmethod
    def _skip(res: LocalResult, item_id: int, why: str) -> None:
        res.excluded[why] += 1
        res.excluded_items[item_id] = why
        return None

    def _reterm(self, d: LocalDeal, feed: bool) -> None:
        m = merchant_entry(d.merchant)
        d.terms = ad_terms(d.raw, feed=feed, merchant_membership=m.membership)

    async def _learn_feeds(self, deals: list[LocalDeal]) -> None:
        """Whether each ad's items come from the retailer's own product feed (savings vs its regular price) or were
        transcribed from print (a saving may be a compare-at claim). Learned from one full record per ad."""
        todo: dict[int, LocalDeal] = {}
        for d in deals:
            if d.flyer_id not in self._feed_cache and d.flyer_id not in todo:
                todo[d.flyer_id] = d

        async def one(d: LocalDeal) -> None:
            try:
                rec = await self.flipp.item(d.item_id)
            except FetchError:
                return
            m = merchant_entry(d.merchant)
            self._feed_cache[d.flyer_id] = is_product_link(str(rec.get("ttm_url") or ""), m.domains)
        await asyncio.gather(*(one(d) for d in todo.values()))
        for d in deals:
            if self._feed_cache.get(d.flyer_id):
                d.feed = True
                self._reterm(d, True)

    async def _detail_pass(self, deals: list[LocalDeal], wanted: set[str]) -> int:
        """Read the full record (retailer link, fine print, buy-one-get-one terms) of the leading deals in each
        requested industry: the ones a user sees first. Returns how many were read."""
        todo: dict[int, LocalDeal] = {}
        for i in wanted:
            for d in [d for d in deals if i in d.industries][:DETAIL_TOP_N]:
                if not d.detailed:
                    todo[d.item_id] = d
        await self.read_details(list(todo.values()))
        return len(todo)                         # a failed read stays unread and is retried in the next round

    async def read_details(self, deals: list[LocalDeal]) -> None:
        """Read the full records of these deals, retermed and rescored from what they say."""
        async def one(d: LocalDeal) -> None:
            try:
                rec = await self.flipp.item(d.item_id)
            except FetchError:
                return
            if not rec:
                d.detailed = True                # the source has nothing more for this item
                return
            merged = {**d.raw, **{k: v for k, v in rec.items() if v not in (None, "", [])}}
            merged["current_price"] = rec.get("current_price") or d.raw.get("current_price")
            link = str(rec.get("ttm_url") or "")
            m = merchant_entry(d.merchant)
            feed = self._feed_cache.get(d.flyer_id, False) or is_product_link(link, m.domains)
            d.raw, d.detailed, d.feed = merged, True, feed
            d.retailer_url = link if is_product_link(link, m.domains) else ""   # not a coupons or deals landing page
            self._reterm(d, feed)
            d.score = score(d)
        await asyncio.gather(*(one(d) for d in deals))

    # -- stores -------------------------------------------------------------------------------------------------
    def _attach_store(self, d: LocalDeal, m: Merchant, store_map: StoreMap, radius_mi: float,
                      res: LocalResult) -> None:
        near = store_map.nearest(m.name)
        if near and near.distance_mi <= radius_mi:
            d.store, d.store_status = near, "nearby"
        elif near:
            d.store, d.store_status = near, "far"
            res.excluded[f"nearest store beyond {radius_mi:g} mi"] += 1
            res.excluded_items[d.item_id] = f"nearest store {near.distance_mi:g} mi away"
        elif not store_map.source_ok or m.map_coverage == "sparse" or (not m.wikidata and not self.stores.known(m)):
            d.store_status = "unmapped"            # the map can't confirm or rule out a store: shown, flagged
        else:
            d.store_status = "far"
            res.excluded["no store within 50 mi"] += 1
            res.excluded_items[d.item_id] = "no store within 50 mi"

    def _merchant_table(self, entries: dict[str, Merchant], store_map: StoreMap, radius_mi: float) -> list[dict]:
        rows = []
        for name, m in sorted(entries.items()):
            near = store_map.nearest(m.name)
            status = ("nearby" if near and near.distance_mi <= radius_mi else
                      "unmapped" if m.map_coverage == "sparse" or (not m.wikidata and not self.stores.known(m))
                      else "far")
            rows.append({"merchant": m.name, "flipp_name": name, "status": status,
                         "nearest_mi": near.distance_mi if near else None,
                         "store": near.to_dict() if near else None})
        return rows
