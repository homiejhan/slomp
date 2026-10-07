"""The home page's biggest deals: what the page shows before a search, the same anywhere in Texas.

Before a city is chosen nothing near it can be shown, so the home page shows the biggest deals that don't depend on
where you are (docs/DESIGN-top-deals.md):

  regular deals   at chains with branches all over Texas: not a single place, nor one area's operator of a chain
  promotions      such restaurant chains' own offers, from deal-site posts (as on the Near you tab)
  online deals    product deals at the big online stores of data/online_stores.json (the Online tab)
  sales           those stores' store-wide and category sales (the Sales tab)

`candidates` ranks every such deal and keeps the best POOL of each kind, one per brand. `pick` chooses the TOP_N shown
at a moment: live then, one per brand, at most PER_KIND of each kind while other kinds have deals to show, in an order
that mixes kinds within each group of PAGE (the page shows them three at a time). The server answers /api/v1/top with
both, at the moment of the request; the published site's build writes the candidates (data/top.json) and engine.js
picks from them in the browser, as `pick` does.
"""
from __future__ import annotations

import re
from collections import Counter
from datetime import date, datetime, time, timedelta
from functools import lru_cache
from typing import Iterable, Optional
from zoneinfo import ZoneInfo

from . import industries as ind
from .geo import miles
from .models import BASIS_WEIGHT, City, OnlineDeal
from .online import OnlineResult
from .promos import RestaurantPromos
from .reference import cities, fold
from .regulars import Regular, Regulars, offer_terms, regular_conditions
from .sales import AHEAD_DAYS, POSTED_DAYS, UNDATED_DAYS, SalesResult, select, stores_payload
from .sources.feeds import Post
from .sources.stores import _restaurants
from .sources.venues import Venues

TOP_N = 9                    # deals the home page shows
PAGE = 3                     # ...three at a time
PER_KIND = 3                 # at most this many of one kind, while the other kinds have deals to fill the rest
POOL = 12                    # candidates kept per kind (the published site picks from these in the browser)
MIN_BRANCHES = 5             # a chain counts with this many mapped branches in Texas or more...
MIN_SPREAD_MI = 150.0        # ...over an area at least this wide, corner to corner: found all over Texas
PROMO_TRUST = 0.7            # a promotion rests on one deal-site post, like a regular deal an article reports
WINDOW_DAYS = 7              # as the tabs: a deal counts when it runs at some point in the next 7 days
CENTRAL = "America/Chicago"  # the home page has no city: dates are Texas's (most of it is on Central time)
KINDS = ("regular", "promotion", "online", "sale")
ONLINE_IDS = tuple(i for i in ind.IDS if ind.BY_ID[i].online)


# --- which chains count -----------------------------------------------------------------------------------------
def footprint(locations: Iterable) -> tuple[int, float]:
    """A chain's mapped branches in Texas: how many, and how far apart (in miles) the corners of the area they cover."""
    rows = list(locations)
    if not rows:
        return 0, 0.0
    lats, lons = [r[0] for r in rows], [r[1] for r in rows]
    return len(rows), miles(min(lats), min(lons), max(lats), max(lons))


def statewide(locations: Iterable) -> bool:
    """A chain you can find wherever you are in Texas: MIN_BRANCHES or more branches, spread over MIN_SPREAD_MI or
    more. The count alone won't do: the map has 9 of Main Event's branches, from El Paso to Houston, and 10 of Kerbey
    Lane Cafe's, all between Round Rock and San Antonio."""
    n, spread = footprint(locations)
    return n >= MIN_BRANCHES and spread >= MIN_SPREAD_MI


def _branches(qid: str) -> list:
    """A restaurant chain's mapped branches, less the ones its own locator no longer lists (as regular deals use)."""
    chain = Venues().get(f"r:{qid}")
    if chain:
        return list(chain.locations)
    return [tuple(r) for r in _restaurants()["brands"].get(qid, {}).get("locations", [])]


@lru_cache(maxsize=1)
def _central() -> City:
    """The largest city on Central time: the time zone the home page's dates are in."""
    return next(c for c in cities() if c.tz == CENTRAL)


# --- how big a deal is ------------------------------------------------------------------------------------------
_FREE = re.compile(r"\bfree\b", re.I)
_TAKES_PURCHASE = re.compile(r"\b(?:(?:with|when (?:you|they))\b|w/)[^.]{0,40}\b(?:purchase|buy|order)|"
                             r"\b(?:with|per) (?:an? |each |every |any )?(?:adult|regular|full-priced)\b", re.I)


def badge_pct(d: dict) -> Optional[float]:
    """How big a deal is, as the page's "Best deal first" counts it (savePct in index.html): the percent on its badge.
    Something free is 100% off, or 50% when it takes a purchase; a price with nothing to compare it to has none."""
    if d.get("discount_pct") is not None:
        return float(d["discount_pct"])
    t = d.get("terms") or {}
    if t.get("pct"):
        return float(t["pct"])
    summary = t.get("summary") or ""
    if not _FREE.search(summary):
        return None
    purchase = any(re.match(r"with\b", c, re.I) for c in t.get("conditions") or []) or \
        re.search(r"kids eat free", summary, re.I) or _TAKES_PURCHASE.search(d.get("title") or "")
    return 50.0 if purchase else 100.0


def _trust(t: dict) -> float:
    """How far a chain's stated saving can be taken at its word, as Regulars ranks it: what the saving is measured
    against (a free item, against its own price), halved for a hedge ("up to", "select weeks")."""
    basis = t.get("basis") or "none"
    return BASIS_WEIGHT.get("store_regular" if basis == "none" else basis, 0.0) * (0.5 if t.get("hedge") else 1.0)


# --- the candidates ---------------------------------------------------------------------------------------------
def _iso(t: Optional[datetime]) -> Optional[str]:
    return t.isoformat(timespec="seconds") if t else None


def _item(d: dict, kind: str, brand: str, rank: float, *, since: Optional[datetime] = None,
          until: Optional[datetime] = None, branches: Optional[int] = None) -> dict:
    """The deal as its tab shows it, plus `top`: its kind, brand, rank and the moments it can be shown between."""
    d["top"] = {"kind": kind, "brand": brand, "key": fold(brand), "rank": round(rank, 2), "from": _iso(since),
                "until": _iso(until)}
    if branches is not None:
        d["top"]["branches"] = branches
    return d


def regular_items(regulars: Iterable[Regular], now: datetime) -> list[dict]:
    """Regular deals at chains found all over Texas that run in the next 7 days, ranked by their percent, what it is
    measured against and how Slomp knows (Regulars' own weights). Your own entries stay out: Slomp hasn't checked
    them."""
    tz = ZoneInfo(CENTRAL)
    start = now.astimezone(tz)
    end = start + timedelta(days=WINDOW_DAYS)
    out = []
    for r in regulars:
        if r.origin == "yours" or r.places or r.area or not r.chain or not r.industries or \
                not statewide(r.chain.locations):
            continue
        off = {d for e in r.evidence if e.live for d in e.off}
        dates = [d for d in r.schedule.occurrences(start, end) if d.isoformat() not in off]
        if not dates:
            continue
        deal = Regulars._deal(r, list(r.industries), None, dates, _central(), start, tz)
        d = deal.to_dict()
        d["store_status"] = "unknown"                 # no branch: the home page has no city to measure from
        size = badge_pct(d)
        if not size:
            continue
        ends = [datetime.combine(r.schedule.until, time(23, 59, 59), tz)] if r.schedule.until else []
        if r.schedule.monthly:
            ends.append(deal.valid_to)               # its one day this month
        out.append(_item(d, "regular", r.brand, size * _trust(d["terms"]) * r.weight,
                         until=min(ends) if ends else None, branches=len(r.chain.locations)))
    return out


def promotion_items(promos: RestaurantPromos, posts: Iterable[Post], now: datetime) -> list[dict]:
    """Restaurant chains' promotions running in the next 7 days, at chains found all over Texas. The offer is read
    from the post's title as regular deals' wording is (a percent, buy one get one, something free)."""
    tz = ZoneInfo(CENTRAL)
    start = now.astimezone(tz)
    end = start + timedelta(days=WINDOW_DAYS)
    out = []
    for p in posts:
        got = promos.offer(p, tz, start, end, Counter())
        if not got:
            continue
        qid, deal = got
        rows = _branches(qid)
        if not statewide(rows):
            continue
        t, o = deal.terms, offer_terms(deal.title)
        t.pct, t.bogo, t.basis, t.hedge = o.pct, o.bogo, o.basis, o.hedge
        t.price, t.regular, t.savings = o.price, o.regular, o.savings
        t.conditions = list(dict.fromkeys(t.conditions + regular_conditions(deal.title)))
        d = deal.to_dict()
        size = badge_pct(d)
        if not size:
            continue
        # A post without dates is kept 3 days after it was posted (RestaurantPromos.offer).
        until = datetime.combine(date.fromisoformat(deal.raw["posted"]) + timedelta(days=3), time(23, 59, 59), tz) \
            if deal.raw["dates"] == "no dates stated" else deal.valid_to
        out.append(_item(d, "promotion", deal.merchant, size * _trust(d["terms"]) * PROMO_TRUST,
                         since=deal.valid_from - timedelta(days=WINDOW_DAYS), until=until, branches=len(rows)))
    return out


def online_items(results: Iterable[OnlineResult], stores: dict) -> list[dict]:
    """Product deals at the registry's online stores, ranked as the Online tab ranks them (its score: the discount,
    what it is measured against, and the conditions it comes with). Only each store's best can be a candidate, so
    only those are kept (the one `candidates` would keep: the highest score, then the first id)."""
    best: dict[str, OnlineDeal] = {}
    for res in results:
        for d in res.all_deals():
            if d.store_key not in stores or not d.discount_pct or d.score <= 0:
                continue
            have = best.get(d.store_key)
            if have is None or (-d.score, d.id) < (-have.score, have.id):
                best[d.store_key] = d
    return [_item(d.to_dict(), "online", stores[k]["name"], d.score, until=d.expires_at) for k, d in best.items()]


def sale_items(res: SalesResult, stores: dict, now: datetime) -> list[dict]:
    """Sales at the registry's online stores, live at `now`, ranked as the Sales tab ranks them. Each can be shown
    for as long as sales.live_reason allows."""
    shown, _ = select(res, ONLINE_IDS, now)
    out = []
    for s in shown:
        if s.store not in stores or s.score <= 0:
            continue
        ends = [s.ends_at] if s.ends_at else []
        if s.posted_at:
            ends.append(s.posted_at + timedelta(days=POSTED_DAYS))
            if not s.ends_at:
                ends.append(s.posted_at + timedelta(days=UNDATED_DAYS))
        out.append(_item(s.to_dict(), "sale", stores[s.store]["name"], s.score,
                         since=s.starts_at - timedelta(days=AHEAD_DAYS) if s.starts_at else None,
                         until=min(ends) if ends else None))
    return out


def _order(d: dict) -> tuple:
    return -d["top"]["rank"], d["top"]["key"], d["id"]


def candidates(now: datetime, regulars: Iterable[Regular] = (), promos: Optional[RestaurantPromos] = None,
               posts: Iterable[Post] = (), online: Iterable[OnlineResult] = (), sales: Optional[SalesResult] = None,
               stores: Optional[dict] = None) -> list[dict]:
    """Every deal the home page could show, best first: the best POOL of each kind, one per brand."""
    stores = stores if stores is not None else stores_payload()
    items = regular_items(regulars, now) + (promotion_items(promos, posts, now) if promos else []) + \
        online_items(online, stores) + (sale_items(sales, stores, now) if sales else [])
    out, kept = [], {k: set() for k in KINDS}
    for d in sorted((d for d in items if d["top"]["rank"] > 0), key=_order):
        t = d["top"]
        if t["key"] in kept[t["kind"]] or len(kept[t["kind"]]) >= POOL:
            continue
        kept[t["kind"]].add(t["key"])
        out.append(d)
    return out


# --- the nine -----------------------------------------------------------------------------------------------------
def live(d: dict, now: datetime) -> bool:
    t = d["top"]
    return (not t["from"] or datetime.fromisoformat(t["from"]) <= now) and \
        (not t["until"] or now <= datetime.fromisoformat(t["until"]))


def pick(pool: Iterable[dict], now: datetime, n: int = TOP_N) -> list[dict]:
    """The `n` biggest deals in `pool` live at `now`: one per brand, and at most PER_KIND of a kind until the other
    kinds run out. Biggest first, except that each group of PAGE takes a kind it doesn't have yet when there is one.
    engine.js has the same steps (pick), for the published site."""
    ranked = sorted((d for d in pool if live(d, now)), key=_order)
    chosen: list[dict] = []
    brands: set[str] = set()
    kinds: Counter = Counter()
    for capped in (True, False):
        for d in ranked:
            t = d["top"]
            if len(chosen) >= n:
                break
            if t["key"] in brands or (capped and kinds[t["kind"]] >= PER_KIND):
                continue
            chosen.append(d)
            brands.add(t["key"])
            kinds[t["kind"]] += 1
    chosen.sort(key=_order)
    out: list[dict] = []
    while chosen:
        page = {d["top"]["kind"] for d in out[len(out) - len(out) % PAGE:]}
        k = next((i for i, d in enumerate(chosen) if d["top"]["kind"] not in page), 0)
        out.append(chosen.pop(k))
    return out


def stores_of(deals: Iterable[dict], stores: Optional[dict] = None) -> dict:
    """The registry entries of the online stores among `deals` (their logos and sites, for the page)."""
    stores = stores if stores is not None else stores_payload()
    keys = {d["store_key"] if d["top"]["kind"] == "online" else d["store"]
            for d in deals if d["top"]["kind"] in ("online", "sale")}
    return {k: stores[k] for k in sorted(keys) if k in stores}


def payload(pool: list[dict], now: datetime) -> dict:
    """The API's /api/v1/top answer: the deals to show at `now`, and their online stores."""
    deals = pick(pool, now)
    return {"generated_at": _iso(now), "deals": deals, "stores": stores_of(deals)}
