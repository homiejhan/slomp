"""The published site (GitHub Pages): what every search needs, read ahead of time and written as JSON files.

    slomp site build --out site

GitHub Pages can't run code on request, so a scheduled workflow (.github/workflows/pages.yml) runs this build and
publishes the files. The page's engine.js answers each search in the browser from them, in the shape of the server's
/api/v1/search. docs/DESIGN-static-site.md has the design.

  weekly ads      every ad running at an anchor ZIP (every Texas city is within ANCHOR_MI of an anchor); each item
                  read, classified and termed once; the leading deals' fine print read for every anchor and radius
  regular deals   the statewide set with its evidence, schedules and branch locations
  promotions      restaurant-chain offers, their dates and the chains' locations
  online deals    the ranked result for each industry
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
import shutil
import time as clock
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Optional
from zoneinfo import ZoneInfo

from . import industries as ind
from .geo import ad_end_local, ad_start_local, miles, parse_time
from .http import FetchError
from .local import DETAIL_ROUNDS, DETAIL_TOP_N, LocalResult, _merge, score
from .models import BASIS_WEIGHT, City, LocalDeal, Merchant, Terms
from .promos import _NOT_A_PROMO, brand_in, promo_dates, recurring_days
from .reference import cities, merchant as merchant_entry, norm
from .regulars import Regular, host_of, status_text
from .service import RADII, SlompService
from .sources.flipp import Flyer, junk_reason
from .sources.stores import MAX_RADIUS_MI, _dataset, _restaurants
from .terms import clean

ANCHOR_MI = 20.0             # every city is within this distance of an anchor ZIP whose ads it uses
ANCHOR_POP = 50_000          # and every city this big is an anchor itself: its own ZIP's ads, as the server reads them
MORE_SEARCHES = 6            # extra searches per merchant for the items of its ads no search has returned yet
WINDOW_DAYS = 8              # one day past the page's 7, so a deal that starts between two builds is there
ONLINE_LIMIT = 48            # online deals per industry: what the page asks the server for
CENTRAL, MOUNTAIN = "America/Chicago", "America/Denver"
ZONES = (CENTRAL, MOUNTAIN)  # Texas's two (El Paso and Hudspeth counties are on Mountain time)
STATIC = Path(__file__).parent / "static"
RETAIL = [i for i in ind.IDS if i not in ind.LOCAL_ONLY]      # the industries weekly ads cover


# --- anchors ---------------------------------------------------------------------------------------------------
def anchors(mi: float = ANCHOR_MI, pop: int = ANCHOR_POP) -> list[City]:
    """Every city of `pop` people or more, then the largest city not yet within `mi` of an anchor, until every city is
    within `mi` of one. Ads cover regions, so a city's nearest anchor lists nearly the same ads as the city itself."""
    ordered = sorted(cities(), key=lambda c: (-(c.population or 0), c.id))
    out = [c for c in ordered if (c.population or 0) >= pop]
    for c in ordered:
        if (c.population or 0) < pop and all(miles(c.lat, c.lon, a.lat, a.lon) > mi for a in out):
            out.append(c)
    return out


def nearest_anchor(c: City, anchor_list: list[City]) -> tuple[City, float]:
    best = min(anchor_list, key=lambda a: miles(c.lat, c.lon, a.lat, a.lon))
    return best, miles(c.lat, c.lon, best.lat, best.lon)


# --- small helpers ----------------------------------------------------------------------------------------------
def _iso(d: Optional[datetime | date]) -> Optional[str]:
    return d.isoformat() if d else None


def _hms(t) -> Optional[str]:
    return t.strftime("%H:%M:%S") if t else None


def _compact(d: dict, defaults: dict) -> dict:
    """Leave out the fields that hold their default value; the page puts them back."""
    return {k: v for k, v in d.items() if k not in defaults or v != defaults[k]}


TERMS_DEFAULTS = Terms().to_dict()


def _zoned_ends(vf: datetime, vt: datetime) -> dict:
    """An ad's or item's first and last moment as the server computes them for a Central-time city, plus the Mountain
    versions where they differ and the moment the source pulls it when that comes first (Flipp ends ads at 11:59 PM
    Eastern)."""
    out = {"vf": ad_start_local(vf, CENTRAL).isoformat(), "vt": ad_end_local(vt, CENTRAL).isoformat()}
    vfm, vtm = ad_start_local(vf, MOUNTAIN), ad_end_local(vt, MOUNTAIN)
    if vfm != ad_start_local(vf, CENTRAL):
        out["vfm"] = vfm.isoformat()
    if vtm != ad_end_local(vt, CENTRAL):
        out["vtm"] = vtm.isoformat()
    if vt < max(ad_end_local(vt, CENTRAL), vtm):
        out["gone"] = vt.isoformat()
    return out


def _live(vf: datetime, vt: datetime, start: datetime, end: datetime) -> bool:
    """Live at some moment in [start, end] in either Texas zone, by the server's rules."""
    return any(min(ad_end_local(vt, z), vt) >= start and ad_start_local(vf, z) <= end for z in ZONES)


# --- weekly ads -------------------------------------------------------------------------------------------------
@dataclass
class Ads:
    start: datetime
    end: datetime
    flyers: dict[int, Flyer] = field(default_factory=dict)           # every ad live at some anchor
    at: dict[str, Optional[list[int]]] = field(default_factory=dict)  # anchor id -> its live ads, in Flipp's order
    out_of_window: Counter = field(default_factory=Counter)           # anchor id -> ads outside the window
    entries: dict[str, Merchant] = field(default_factory=dict)       # Flipp's merchant name -> registry entry
    deals: dict[int, list[LocalDeal]] = field(default_factory=dict)  # ad id -> its deals, in the ad's order
    excluded: dict[int, Counter] = field(default_factory=dict)       # ad id -> its items left out, and why
    hits: dict[str, dict] = field(default_factory=dict)              # Flipp's merchant name -> item id -> search hit
    times: dict[tuple, tuple] = field(default_factory=dict)          # (ad, item) -> (from, to) as the source states
    keys: dict[tuple, str] = field(default_factory=dict)             # (ad, item) -> the server's duplicate test
    stats: Counter = field(default_factory=Counter)


async def build_ads(svc: SlompService, anchor_list: list[City], now: datetime, log=print) -> Ads:
    ld, flipp = svc.local_deals, svc.flipp
    start = now.astimezone(ZoneInfo(CENTRAL)) - timedelta(hours=1)   # an hour back: Mountain time ends an hour later
    end = start + timedelta(days=WINDOW_DAYS, hours=1)
    ads = Ads(start, end)

    async def listed(a: City) -> Optional[list[Flyer]]:
        try:
            return await flipp.flyers(a.zip)
        except FetchError:
            return None
    t0 = clock.time()
    for a, got in zip(anchor_list, await asyncio.gather(*(listed(a) for a in anchor_list))):
        if got is None:
            ads.at[a.id] = None
            continue
        ads.at[a.id] = []
        for f in got:
            if _live(f.valid_from, f.valid_to, start, end):
                ads.flyers.setdefault(f.id, f)
                ads.at[a.id].append(f.id)
            else:
                ads.out_of_window[a.id] += 1
    ads.entries = {f.merchant: merchant_entry(f.merchant) for f in ads.flyers.values()}
    log(f"ads: {len(ads.flyers)} live ads at {sum(v is not None for v in ads.at.values())}/{len(anchor_list)} anchors "
        f"({clock.time() - t0:.0f}s)")

    t0 = clock.time()
    fids = list(ads.flyers)
    listings = dict(zip(fids, await asyncio.gather(*(ld._listing(ads.flyers[f]) for f in fids))))
    items_of = {fid: {i.get("id") for i in listings[fid] if i.get("id") and not junk_reason(i)} for fid in fids}

    # Flipp's item search gives the taxonomy labels and original prices. Item records are the same everywhere, so a
    # merchant is searched at an anchor only when one of its ads there hasn't been searched yet at another.
    covered: dict[str, set[int]] = defaultdict(set)
    hits: dict[str, dict] = defaultdict(dict)
    searched: set[tuple[str, str]] = set()
    where: dict[str, list[tuple]] = defaultdict(list)   # merchant -> (its ads at an anchor, anchor order, ZIP, the ads)
    ads.hits = hits

    async def search(name: str, zip_code: str, expect: Iterable[int] = ()) -> Optional[list[dict]]:
        searched.add((name, zip_code))
        ads.stats["searches"] += 1
        try:
            items = await flipp.merchant_items(zip_code, name, expect)
        except FetchError:
            ads.stats["searches failed"] += 1
            return None
        hits[name].update({i.get("id"): i for i in items if i.get("id")})
        return items
    for k, a in enumerate(anchor_list):
        mine: dict[str, set[int]] = defaultdict(set)
        for fid in ads.at.get(a.id) or []:
            mine[ads.flyers[fid].merchant].add(fid)
        for m, ids in mine.items():
            where[m].append((len(ids), k, a.zip, frozenset(ids)))
        todo = sorted(m for m, ids in mine.items() if not ids <= covered[m])
        found = await asyncio.gather(*(search(m, a.zip, {f for f in mine[m] if items_of[f]}) for m in todo))
        for m, items in zip(todo, found):
            if items is not None:                 # a failed search is tried again at the next anchor with these ads
                covered[m] |= mine[m]

    # A search returns at most ~150 items, and which of a merchant's items it returns differs from ZIP to ZIP with no
    # pattern Slomp can see (Family Dollar: 113 or 123 of one ad's 137 items, by ZIP). So the items still without a
    # result are searched for again at other anchors that have them, in an order that doesn't favor one region, until
    # a few searches in a row turn up nothing new.
    async def complete(m: str) -> None:
        extra = dry = 0
        order = sorted(where[m], key=lambda w: hashlib.sha1(f"{m}|{w[2]}".encode()).hexdigest())
        for _, _, zip_code, ids in order:
            if extra >= MORE_SEARCHES or dry >= 3:
                break
            missing = set().union(*(items_of[f] for f in ids)) - hits[m].keys()
            if (m, zip_code) in searched or not missing:
                continue
            extra += 1
            await search(m, zip_code, {f for f in ids if items_of[f]})
            dry = 0 if missing & hits[m].keys() else dry + 1      # this search found some of them, or none
    await asyncio.gather(*(complete(m) for m in where))
    unsearched = sum(len(items_of[f] - hits[ads.flyers[f].merchant].keys()) for f in fids)
    ads.stats["items without a search result"] = unsearched
    log(f"ads: {ads.stats['searches']} merchant searches; {unsearched} of {sum(map(len, items_of.values()))} items "
        f"have no search result ({clock.time() - t0:.0f}s)")

    t0 = clock.time()
    central = anchor_list[0] if anchor_list[0].tz == CENTRAL else next(c for c in cities() if c.tz == CENTRAL)

    def read(fid: int) -> None:                    # every item of one ad, as LocalDeals.run reads them
        f = ads.flyers[fid]
        m = ads.entries[f.merchant]
        res = LocalResult(central, RETAIL, MAX_RADIUS_MI, start, end)
        out: list[LocalDeal] = []
        for raw_listing in listings[fid]:
            why = junk_reason(raw_listing)
            if why:
                res.excluded[why] += 1
                continue
            d = ld._deal(_merge(raw_listing, hits[f.merchant].get(raw_listing.get("id"))), f, m, central, start, end,
                         res)
            if d is not None:
                ads.times[(fid, d.item_id)] = (parse_time(d.raw.get("valid_from")) or f.valid_from,
                                               parse_time(d.raw.get("valid_to")) or f.valid_to)
                out.append(d)
        ads.deals[fid], ads.excluded[fid] = out, res.excluded
    for fid in fids:
        read(fid)
    # Whether an ad's items come from the retailer's own product feed changes what counts as a saving. The server
    # learns it from the first search that shows the ad and reads the ad's items with it from then on; so does this.
    unknown = [fid for fid in fids if fid not in ld._feed_cache]
    await ld._learn_feeds([d for fid in fids for d in ads.deals[fid]])
    for fid in unknown:
        if ld._feed_cache.get(fid):
            read(fid)
    every = [d for fid in fids for d in ads.deals[fid]]
    log(f"ads: {sum(len(x) for x in listings.values())} items in {len(fids)} ads, {len(every)} deals, "
        f"{sum(bool(ld._feed_cache.get(f)) for f in fids)} ads from retailers' product feeds ({clock.time() - t0:.0f}s)")

    t0 = clock.time()
    await ld._learn_feeds(every)                   # no new reads: marks the feed ads' deals, as the server does
    for d in every:
        d.score = score(d)
        # The server keys duplicates after the ad's feed check and before any fine print is read.
        ads.keys[(d.flyer_id, d.item_id)] = dedupe_key(d)
    await _lead_details(svc, ads, anchor_list, now, log)
    log(f"ads: fine print read for {sum(d.detailed for d in every)} deals ({clock.time() - t0:.0f}s)")
    return ads


def dedupe_key(d: LocalDeal) -> str:
    """The server's test for the same item in two overlapping ads (LocalDeals.run)."""
    return f"{d.merchant}|{norm(d.title)}|{d.terms.price}|{d.terms.pct}"


async def _lead_details(svc: SlompService, ads: Ads, anchor_list: list[City], now: datetime, log=print) -> None:
    """Read the fine print of the deals a search shows first, as the server does for the city it searches: for each
    anchor and radius, the leading DETAIL_TOP_N deals in each industry, in up to DETAIL_ROUNDS rounds (fine print can
    lower a deal, which lets unread ones into the lead)."""
    order = lambda d: (-d.score, -(d.terms.savings or 0), d.title)            # noqa: E731
    leads: list[tuple[list[LocalDeal], dict]] = []
    for a in anchor_list:
        start = now.astimezone(ZoneInfo(a.tz))
        end = start + timedelta(days=svc.settings.window_days)
        seen: dict[str, LocalDeal] = {}
        pool: list[LocalDeal] = []
        for fid in ads.at.get(a.id) or []:
            f = ads.flyers[fid]
            if min(ad_end_local(f.valid_to, a.tz), f.valid_to) < start or ad_start_local(f.valid_from, a.tz) > end:
                continue
            for d in ads.deals[fid]:
                vf, vt = ads.times[(fid, d.item_id)]
                if min(ad_end_local(vt, a.tz), vt) < start or ad_start_local(vf, a.tz) > end:
                    continue
                k = ads.keys[(fid, d.item_id)]
                keep = seen.get(k)
                if keep is None:
                    seen[k] = d
                    pool.append(d)
                elif d.valid_to > keep.valid_to:
                    pool[pool.index(keep)] = d
                    seen[k] = d
        smap = svc.stores.near(a, list({ads.entries[ads.flyers[f].merchant].name: ads.entries[ads.flyers[f].merchant]
                                         for f in ads.at.get(a.id) or []}.values()))
        dist = {}
        for d in pool:
            near = smap.nearest(d.merchant)
            m = merchant_entry(d.merchant)
            dist[id(d)] = near.distance_mi if near else (
                -1.0 if m.map_coverage == "sparse" or (not m.wikidata and not svc.stores.known(m)) else None)
        leads.append((pool, dist))
    for rnd in range(DETAIL_ROUNDS):
        todo: dict[int, LocalDeal] = {}
        for pool, dist in leads:
            ranked = sorted(pool, key=order)
            for r in RADII:
                kept = [d for d in ranked if dist[id(d)] is not None and dist[id(d)] <= r]   # nearby, or unmapped (-1)
                for i in RETAIL:
                    for d in [d for d in kept if i in d.industries][:DETAIL_TOP_N]:
                        if not d.detailed:
                            todo[d.item_id] = d
        if not todo:
            break
        log(f"ads: round {rnd + 1}: reading the fine print of {len(todo)} deals")
        await svc.local_deals.read_details(list(todo.values()))


def ad_files(ads: Ads) -> dict[str, dict]:
    """data/ads/<id>.json for every ad, and data/ads/index.json."""
    files: dict[str, dict] = {}
    merchants: dict[str, dict] = {}
    for fid, f in ads.flyers.items():
        m = ads.entries[f.merchant]
        merchants[m.name] = {"uncertain": m.map_coverage == "sparse" or (not m.wikidata and not _known(m))}
        rows = []
        for d in ads.deals[fid]:
            vf, vt = ads.times[(fid, d.item_id)]
            row = {"id": d.item_id, "title": d.title, "industries": d.industries, "category": d.category,
                   "terms": _compact(d.terms.to_dict(), TERMS_DEFAULTS), **_zoned_ends(vf, vt),
                   "retailer_url": d.retailer_url, "image_url": d.image_url, "feed": d.feed, "detailed": d.detailed,
                   "score": d.score, "dk": ads.keys[(fid, d.item_id)]}
            rows.append({k: v for k, v in row.items() if v not in ("", False, None)})
        files[f"ads/{fid}.json"] = {"id": fid, "merchant": m.name, "excluded": dict(ads.excluded[fid]), "deals": rows}
    flyers = {fid: {"merchant": ads.entries[f.merchant].name, "flipp": f.merchant,
                    **_zoned_ends(f.valid_from, f.valid_to), "n": len(ads.deals[fid])}
              for fid, f in ads.flyers.items()}
    files["ads/index.json"] = {
        "built": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "anchors": {aid: ({"ads": ids, "out": ads.out_of_window[aid]} if ids is not None else
                          {"ads": None, "error": "Flipp could not be read for this area"})
                    for aid, ids in ads.at.items()},
        "flyers": flyers, "merchants": merchants, "stats": dict(ads.stats)}
    return files


def _known(m: Merchant) -> bool:
    return bool(_dataset()["merchants"].get(m.name))


def store_file(ads: Ads) -> dict:
    """Every mapped store of the merchants that advertise: the page finds the nearest one to the city itself."""
    data = _dataset()
    names = sorted({m.name for m in ads.entries.values()})
    return {"built": data.get("built", ""),
            "merchants": {n: data["merchants"][n] for n in names if data["merchants"].get(n)}}


# --- regular deals ----------------------------------------------------------------------------------------------
def _regular(r: Regular, today: date) -> dict:
    s = r.schedule
    t = Terms(**{**r.terms.to_dict(), "conditions": list(r.conditions)})
    live = [e for e in r.evidence if e.live]
    lead = next((e for k in ("official", "rewards", "list", "article", "yours") for e in live if e.kind == k), None)
    weight = BASIS_WEIGHT.get(t.basis, 0.0) * (0.5 if t.hedge else 1.0)          # as Regulars._deal ranks it
    windows = {z: [[_hms(a), _hms(b)] for a, b in s.local_windows(today, ZoneInfo(z))] for z in ZONES}
    out = {
        "id": r.id, "brand": r.brand, "offer": r.offer, "industries": r.industries, "kind": r.kind, "origin": r.origin,
        "terms": _compact(t.to_dict(), TERMS_DEFAULTS), "link": r.link, "image_url": r.image_url, "note": r.note,
        "source_url": (lead.url if lead else "") or r.link,
        "score": round((t.pct or 0.0) * weight * r.weight, 2),
        "status": r.status, "status_text": status_text(r), "evidence": [e.to_dict() for e in r.evidence],
        "off": sorted({d for e in live for d in e.off}),
        "logo": {"url": r.logo["url"], "fit": r.logo.get("fit", "contain")} if r.logo.get("url") else None,
        "schedule": {"days": sorted(set(s.days)), "monthly": s.monthly, "until": _iso(s.until), "since": _iso(s.since),
                     "windows": windows},
        "days_text": s.days_text().replace("Every ", "Some ", t.hedge == "select weeks") +
                     ("s" if t.hedge == "select weeks" and len(s.days) == 1 else ""),
        "time_text": {z: s.time_text(today, ZoneInfo(z)) for z in ZONES},
    }
    if r.places:
        out["places"] = [[float(p["lat"]), float(p["lon"]), str(p.get("name") or r.brand), str(p.get("address") or "")]
                         for p in r.places if p.get("lat") is not None and p.get("lon") is not None]
    else:
        out["chain"] = r.chain.key if r.chain else None
        out["area"] = r.area
    return out


async def regulars_file(svc: SlompService, now: datetime, log=print) -> dict:
    now = now.astimezone(ZoneInfo(CENTRAL))           # "today" is a Texas date, wherever the build runs
    unread: Counter = Counter()
    check = svc.regulars.check

    async def noted(spec: dict, *args, **kwargs):      # which evidence pages couldn't be read here, and why
        ev = await check(spec, *args, **kwargs)
        if not ev.found:
            unread[(host_of(str(spec.get("url") or "")), ev.note or "the page no longer says this")] += 1
        return ev
    svc.regulars.check = noted
    try:
        rset = await svc.regulars.all(now=now)
    finally:
        svc.regulars.check = check
    for (host, why), n in unread.most_common():
        log(f"regular deals: evidence not read at {host}: {why}" + (f" ({n} pages)" if n > 1 else ""))
    today = now.date()
    # Your own file stays on your computer: the published site never shows it.
    shown = [r for r in rset.regulars if r.origin != "yours"]
    rows = [_regular(r, today) for r in shown]
    chains = {}
    for r in shown:
        if not r.places and r.chain and r.chain.key not in chains:
            chains[r.chain.key] = {"name": r.chain.name, "rows": [list(x) for x in r.chain.locations]}
    sources = [s for s in rset.sources if s.get("name") != "Your regular deals"]
    return {"built": now.isoformat(timespec="seconds"), "regulars": rows, "chains": chains,
            "excluded": {k: v for k, v in rset.excluded.most_common() if "(yours)" not in k}, "sources": sources}


# --- restaurant promotions --------------------------------------------------------------------------------------
async def promos_file(svc: SlompService, now: datetime) -> dict:
    """The parts of RestaurantPromos.near that don't depend on the city: which posts are restaurant offers, which
    chain, and the dates each states, read in both Texas zones."""
    posts, sources = await svc.promos.posts()
    excluded: Counter = Counter()
    items, chains = [], {}
    for p in posts:
        if _NOT_A_PROMO.search(p.title):
            excluded["promotion: gift card, subscription, game or merchandise"] += 1
            continue
        qid = None
        if p.seller:
            hit = svc.promos.locator.brand(p.seller)
            qid = hit[0] if hit else None
        qid = qid or brand_in(p.title)
        if not qid:
            excluded["promotion: not a mapped restaurant chain"] += 1
            continue
        text = f"{p.title}. {p.text[:400]}"
        zones = {}
        for z in ZONES:
            tz = ZoneInfo(z)
            posted = (p.posted_at or now).astimezone(tz).date()
            first, last, how = promo_dates(text, posted)
            stated = p.expires_at.astimezone(tz).date() if p.expires_stated and p.expires_at else None
            zones[z] = {"posted": _iso(posted), "first": _iso(first), "last": _iso(last), "how": how,
                        "stated": _iso(stated)}
        items.append({"id": p.id, "title": clean(p.title), "summary": clean(p.title)[:140], "url": p.url,
                      "image": p.image, "qid": qid,
                      "posted_now": p.posted_at is None, "zones": zones, "recur": recurring_days(text),
                      "app": bool(re.search(r"\bapp\b", text, re.I)), "dinein": bool(re.search(r"dine-?in", text, re.I))})
        if qid not in chains:
            b = _restaurants()["brands"][qid]
            chains[qid] = {"name": b["name"], "rows": [list(x) for x in b["locations"]]}
    return {"built": now.isoformat(timespec="seconds"), "items": items, "chains": chains,
            "excluded": dict(excluded.most_common()), "sources": sources}


# --- online deals -----------------------------------------------------------------------------------------------
async def online_files(svc: SlompService, log=print) -> dict[str, dict]:
    files = {}
    for i in ind.IDS:
        if not ind.BY_ID[i].online:
            continue
        t0 = clock.time()
        res = await svc.online(i, ONLINE_LIMIT)
        files[f"online/{i}.json"] = res.to_dict()
        log(f"online: {i}: {len(res.deals.get(i, []))} deals ({clock.time() - t0:.0f}s)")
    return files


# --- the site ---------------------------------------------------------------------------------------------------
def meta_file(anchor_list: list[City], built: datetime, parts: dict) -> dict:
    out = []
    for c in cities():
        a, d = nearest_anchor(c, anchor_list)
        out.append({"id": c.id, "name": c.name, "county": c.county, "population": c.population, "zip": c.zip,
                    "kind": c.kind, "lat": c.lat, "lon": c.lon, "tz": c.tz, "anchor": a.id,
                    "anchor_mi": round(d, 1)})
    return {"built": built.isoformat(timespec="seconds"), "cities": out,
            "industries": [{"id": i.id, "name": i.name, "description": i.description, "online": i.online}
                           for i in ind.INDUSTRIES],
            "radii_mi": list(RADII), "window_days": 7, "anchor_mi": ANCHOR_MI,
            "anchors": {a.id: {"name": a.name, "zip": a.zip} for a in anchor_list}, "parts": parts}


def page_html() -> str:
    """The server's page with the engine loaded first, which switches it to the published site's mode."""
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    marker = '<script>\n"use strict";'
    if marker not in html:
        raise RuntimeError("index.html no longer has the marker the site build inserts engine.js before")
    return html.replace(marker, '<script src="engine.js"></script>\n' + marker, 1)


def write(out: Path, files: dict[str, dict | str]) -> int:
    total = 0
    for rel, content in files.items():
        p = out / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False, separators=(",", ":"))
        p.write_text(text, encoding="utf-8")
        total += len(text.encode())
    return total


async def build(out: Path, now: Optional[datetime] = None, anchor_mi: float = ANCHOR_MI, online: bool = True,
                svc: Optional[SlompService] = None, prune: bool = False, log=print, inspect: Optional[dict] = None) -> dict:
    """Read everything and write the site into `out` (replacing what is there). Returns a summary. `prune` drops
    cached responses more than 3 days past their lifetime (the workflow's cache travels between runs); `inspect`, when
    given, receives what the build read (the parity check uses it)."""
    now = now or datetime.now(timezone.utc)
    own = svc is None
    svc = svc or SlompService()
    anchor_list = anchors(anchor_mi)
    log(f"{len(anchor_list)} anchors within {anchor_mi:g} mi of every Texas city")
    t0 = clock.time()
    try:
        ads_task = asyncio.create_task(build_ads(svc, anchor_list, now, log))
        regs_task = asyncio.create_task(regulars_file(svc, now, log))
        promos_task = asyncio.create_task(promos_file(svc, now))
        online_task = asyncio.create_task(online_files(svc, log)) if online else None
        ads = await ads_task
        if inspect is not None:
            inspect["ads"] = ads
        regs, promos = await regs_task, await promos_task
        onl = await online_task if online_task else {}
        log(f"regular deals: {len(regs['regulars'])}; promotions: {len(promos['items'])} offers")
        files: dict[str, dict | str] = {}
        files.update({f"data/{k}": v for k, v in ad_files(ads).items()})
        files["data/stores.json"] = store_file(ads)
        files["data/regulars.json"] = regs
        files["data/promos.json"] = promos
        files.update({f"data/{k}": v for k, v in onl.items()})
        parts = {"ads": {"ads": len(ads.flyers), "anchors_read": sum(v is not None for v in ads.at.values()),
                         "anchors": len(anchor_list), **dict(ads.stats)},
                 "regulars": len(regs["regulars"]), "promotions": len(promos["items"]),
                 "online": {k.split("/")[1].removesuffix(".json"): len(next(iter(v["deals"].values()), []))
                            for k, v in onl.items()},
                 "seconds": round(clock.time() - t0), "requests": {h: s.get("requests", 0)
                                                                  for h, s in svc.http.stats.items()}}
        files["data/meta.json"] = meta_file(anchor_list, now, parts)
        files["index.html"] = page_html()
        files["engine.js"] = (STATIC / "engine.js").read_text(encoding="utf-8")
        if out.exists():
            shutil.rmtree(out)
        size = write(out, files)
        log(f"wrote {len(files)} files, {size / 1e6:.1f} MB, to {out} ({clock.time() - t0:.0f}s in all)")
        return {**parts, "files": len(files), "bytes": size}
    finally:
        if prune:
            # A source that is briefly down falls back to its last good answer, so expired answers are kept a while.
            log(f"cache: dropped {svc.db.cache_purge(older_than_s=3 * 86400)} expired responses")
        if own:
            await svc.aclose()
