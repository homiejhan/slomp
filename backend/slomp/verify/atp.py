"""AllThePlaces: chains' own store-locator data, used as an independent check on OpenStreetMap store locations.

AllThePlaces runs weekly and some chains' scrapes fail in a given run, so each chain is read from the most recent run
that has data for it. Only stores in and around Texas are kept. Cached under ~/.cache/slomp/atp.
"""
from __future__ import annotations

import json
import urllib.request
from functools import lru_cache
from pathlib import Path
from typing import Optional

CACHE = Path.home() / ".cache" / "slomp" / "atp"
BASE = "https://alltheplaces-data.openaddresses.io"
UA = {"User-Agent": "Mozilla/5.0 (compatible; Slomp/1.0)"}
TX_BBOX = (24.8, -107.7, 37.5, -92.5)          # Texas plus about 60 miles on each side

# Slomp merchant name -> AllThePlaces spider(s).
SPIDERS: dict[str, list[str]] = {
    "Best Buy": ["best_buy"], "Target": ["target_us"], "Walmart": ["walmart_us"], "Academy Sports + Outdoors":
    ["academy_us"], "Dick's Sporting Goods": ["dicks_sporting_goods"], "Old Navy": ["old_navy"], "Kohl's": ["kohls_us"],
    "JCPenney": ["jcpenney"], "ULTA": ["ulta_beauty_us"], "PetSmart": ["petsmart"], "CVS Pharmacy": ["cvs_us"],
    "Walgreens": ["walgreens"], "Home Depot": ["home_depot"], "Office Depot OfficeMax": ["office_depot"],
    "Costco": ["costco_ca_gb_us"], "Sam's Club": ["sams_club"], "Marshalls": ["tjx"], "TJ Maxx": ["tjx"],
    "Five Below": ["five_below_us"], "Dollar General": ["dollar_general"], "Family Dollar": ["family_dollar_us"],
    "Fiesta Mart": ["fiesta_mart_us"], "Sprouts Farmers Market": ["sprouts_farmers_market"],
    "Bath & Body Works": ["bath_and_body_works_us"], "Michaels": ["michaels"], "Hobby Lobby": ["hobby_lobby_us"],
    "Harbor Freight Tools": ["harbor_freight_tools_us"], "Tractor Supply Company": ["tractor_supply"],
    "Cabela's": ["cabelas_us"], "Bass Pro Shops": ["bass_pro_shops"], "Ace Hardware": ["ace_hardware_us"],
    "Kroger": ["kroger_us"], "Albertsons": ["albertsons"], "Big Lots": ["big_lots_us"],
    "Ross Dress for Less": ["ross_dress_for_less_us"], "Burlington": ["burlington_us"], "Macy's": ["macys"],
    "Dillard's": ["dillards"], "Petco": ["petco"], "AutoZone": ["autozone"], "O'Reilly Auto Parts": ["oreilly_auto"],
    "H-E-B": ["h_e_b_us"], "Dollar Tree": ["dollar_tree"],
}
# Brand names inside multi-brand spiders (tjx covers T.J. Maxx, Marshalls, HomeGoods, ...).
BRAND_FILTER = {"Marshalls": "marshalls", "TJ Maxx": "t.j. maxx"}


def _get(url: str, timeout: int = 300) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return r.read()


@lru_cache(maxsize=1)
def recent_runs(n: int = 6) -> list[str]:
    path = CACHE / "history.json"
    CACHE.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_bytes(_get(f"{BASE}/runs/history.json"))
    runs = json.loads(path.read_text())
    return [r["run_id"] for r in runs[-n:]][::-1]


def _stats(run_id: str) -> dict[str, int]:
    path = CACHE / f"stats-{run_id}.json"
    if not path.exists():
        path.write_bytes(_get(f"{BASE}/runs/{run_id}/stats/_results.json"))
    return {r["spider"]: r["features"] for r in json.loads(path.read_text())["results"]}


def _spider_points(spider: str, runs_wanted: int = 3) -> Optional[list[tuple[float, float, str, str]]]:
    """(lat, lon, brand, address) for a spider's stores near Texas: the union of the newest runs that have data
    (any single run's scrape can be partial), deduplicated by location. None if no recent run has data."""
    path = CACHE / f"{spider}.tx.v2.json"
    if path.exists():
        data = json.loads(path.read_text())
        return [tuple(x) for x in data] if data is not None else None
    s, w, n, e = TX_BBOX
    seen: dict[tuple[int, int], tuple[float, float, str, str]] = {}
    used = 0
    for run in recent_runs():
        if used >= runs_wanted:
            break
        if _stats(run).get(spider, 0) <= 0:
            continue
        used += 1
        gj = json.loads(_get(f"{BASE}/runs/{run}/output/{spider}.geojson"))
        for f in gj.get("features") or []:
            g = f.get("geometry") or {}
            if g.get("type") != "Point":
                continue
            lon, lat = g["coordinates"][:2]
            if s <= lat <= n and w <= lon <= e:
                p = f.get("properties") or {}
                addr = ", ".join(x for x in (p.get("addr:street_address") or p.get("addr:full"), p.get("addr:city"))
                                 if x)
                seen.setdefault((round(lat * 300), round(lon * 300)),
                                (lat, lon, str(p.get("brand") or p.get("name") or ""), addr))
    pts = list(seen.values()) if used else None
    path.write_text(json.dumps(pts))
    return pts


def stores(merchant: str) -> Optional[list[tuple[float, float, str, str]]]:
    """The merchant's stores near Texas according to its own store locator, or None when AllThePlaces can't say."""
    spiders = SPIDERS.get(merchant)
    if not spiders:
        return None
    out: list[tuple[float, float, str, str]] = []
    known = False
    for sp in spiders:
        pts = _spider_points(sp)
        if pts is None:
            continue
        known = True
        want = BRAND_FILTER.get(merchant)
        out += [p for p in pts if not want or want in p[2].lower()]
    return out if known else None
