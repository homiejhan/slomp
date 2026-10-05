"""Build the store-location datasets from OpenStreetMap (Geofabrik's Texas extract):

  plum/data/stores_tx.json        every mapped store of the merchants in plum/data/merchants.json
  plum/data/restaurants_tx.json   every mapped location of US restaurant chains (for restaurant promotions)

Store locations change slowly, so Plum looks them up locally instead of querying a live map API per request (the
public Overpass servers were too slow or blocking for that). Rebuild weekly.

    uv run --no-project --with osmium python scripts/build_stores.py [--pbf PATH]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.request
from collections import Counter
from datetime import date
from pathlib import Path

import osmium

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from plum.reference import merchants, norm  # noqa: E402

PBF_URL = "https://download.geofabrik.de/north-america/us/texas-latest.osm.pbf"
NSI_URL = "https://cdn.jsdelivr.net/npm/name-suggestion-index@latest/dist/nsi.min.json"
CACHE = Path.home() / ".cache" / "plum" / "osm"
DATA = ROOT / "plum" / "data"
UA = {"User-Agent": "Mozilla/5.0 (compatible; Plum/1.0)"}

NOT_A_STORE = {"fuel", "car_wash", "vending_machine", "atm", "charging_station", "parking", "clinic", "doctors",
               "parcel_locker", "bicycle_rental", "fast_food", "cafe", "restaurant", "pharmacy_counter"}
RESTAURANT_AMENITY = {"fast_food", "restaurant", "cafe", "ice_cream", "pub", "bar", "food_court"}
RESTAURANT_SHOP = {"coffee", "bakery", "donut", "pastry", "confectionery"}
NSI_PATHS = ("brands/amenity/fast_food", "brands/amenity/restaurant", "brands/amenity/cafe", "brands/amenity/ice_cream",
             "brands/shop/coffee", "brands/shop/bakery", "brands/shop/donut", "brands/amenity/pub", "brands/amenity/bar")


def fetch(url: str, path: Path) -> Path:
    if not path.exists():
        print(f"downloading {url}")
        path.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=1800) as r:
            path.write_bytes(r.read())
    return path


def restaurant_brands() -> dict[str, dict]:
    """US restaurant brands from the OSM Name Suggestion Index: Wikidata id -> name and aliases."""
    nsi = json.loads(fetch(NSI_URL, CACHE / "nsi.min.json").read_text())["nsi"]
    out: dict[str, dict] = {}
    for path, cat in nsi.items():
        if not path.startswith(NSI_PATHS):
            continue
        for it in cat["items"]:
            tags = it.get("tags", {})
            qid = tags.get("brand:wikidata")
            loc = [str(x).lower() for x in it.get("locationSet", {}).get("include", [])]
            if not qid or not any(x in ("001",) or x.startswith("us") for x in loc):
                continue
            e = out.setdefault(qid, {"name": tags.get("brand") or tags.get("name") or it.get("displayName"),
                                     "aliases": set()})
            e["aliases"].update(n for n in (tags.get("brand"), tags.get("name"), it.get("displayName")) if n)
    return out


def address(tags: dict) -> str:
    street = " ".join(x for x in (tags.get("addr:housenumber"), tags.get("addr:street")) if x)
    return ", ".join(x for x in (street, tags.get("addr:city", "")) if x)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--pbf", type=Path, default=CACHE / "texas-latest.osm.pbf")
    args = ap.parse_args()
    pbf = fetch(PBF_URL, args.pbf)

    reg = merchants()
    by_qid = {q: m for m in reg for q in m.wikidata}
    by_name = {norm(n): m for m in reg for n in m.osm_names}
    rbrands = restaurant_brands()
    r_by_name: dict[str, str] = {}
    for qid, e in rbrands.items():
        for a in e["aliases"]:
            r_by_name.setdefault(norm(a), qid)

    stores: dict[str, list] = {}
    rest: dict[str, list] = {}
    seen: set = set()
    t0, n = time.time(), 0
    fp = (osmium.FileProcessor(str(pbf), osmium.osm.NODE | osmium.osm.WAY)
          .with_locations()
          .with_filter(osmium.filter.KeyFilter("shop", "amenity")))
    for o in fp:
        n += 1
        tags = {t.k: t.v for t in o.tags}
        if o.is_node():
            if not o.location.valid():
                continue
            lat, lon = o.location.lat, o.location.lon
            ref = f"osm:node/{o.id}"
        else:
            pts = [(nd.location.lat, nd.location.lon) for nd in o.nodes if nd.location.valid()]
            if not pts:
                continue
            lat, lon = sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)
            ref = f"osm:way/{o.id}"
        qid = tags.get("brand:wikidata", "")
        amenity, shop = tags.get("amenity", ""), tags.get("shop", "")
        names = [norm(tags.get(k, "")) for k in ("brand", "name")]

        # Restaurants (for restaurant promotions).
        if amenity in RESTAURANT_AMENITY or shop in RESTAURANT_SHOP:
            rq = qid if qid in rbrands else next((r_by_name[x] for x in names if x and x in r_by_name), "")
            if rq:
                rest.setdefault(rq, []).append([round(lat, 6), round(lon, 6), address(tags), ref])
            continue
        # Retail stores of registry merchants.
        if amenity in NOT_A_STORE or shop in ("optician", "car_repair", "tyres"):
            continue
        m = by_qid.get(qid) or next((by_name[x] for x in names if x and x in by_name), None)
        if not m:
            continue
        key = (m.name, round(lat * 500), round(lon * 500))      # node + building outline of one store: keep one
        if key in seen:
            continue
        seen.add(key)
        stores.setdefault(m.name, []).append([round(lat, 6), round(lon, 6), tags.get("name") or m.name,
                                              address(tags), ref])

    built = date.today().isoformat()
    (DATA / "stores_tx.json").write_text(json.dumps(
        {"built": built, "source": "OpenStreetMap contributors (ODbL), Geofabrik Texas extract",
         "fields": ["lat", "lon", "name", "address", "ref"], "merchants": stores}, separators=(",", ":")))
    (DATA / "restaurants_tx.json").write_text(json.dumps(
        {"built": built, "source": "OpenStreetMap contributors (ODbL), Geofabrik Texas extract; brands from the "
                                   "OSM Name Suggestion Index",
         "fields": ["lat", "lon", "address", "ref"],
         "brands": {q: {"name": rbrands[q]["name"], "aliases": sorted(rbrands[q]["aliases"]), "locations": locs}
                    for q, locs in rest.items()}}, separators=(",", ":")))
    print(f"scanned {n:,} shop/amenity objects in {time.time() - t0:.0f}s")
    counts = Counter({k: len(v) for k, v in stores.items()})
    print(f"stores: {sum(counts.values()):,} for {len(counts)} merchants; none for "
          f"{sorted(m.name for m in reg if m.name not in counts)}")
    print("  " + ", ".join(f"{k} {v}" for k, v in counts.most_common()))
    rc = Counter({rbrands[q]["name"]: len(v) for q, v in rest.items()})
    print(f"restaurants: {sum(rc.values()):,} locations of {len(rc)} brands; top: {rc.most_common(12)}")


if __name__ == "__main__":
    main()
