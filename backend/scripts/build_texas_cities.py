"""Build plum/data/texas_cities.json: the fixed list of Texas cities users choose from.

Sources (US Census Bureau, public, keyless):
  * 2026 Gazetteer, Texas places: every incorporated place and CDP with its internal point
  * Vintage 2025 population estimates: incorporated places, with their county parts
  * ACS 2024 5-year table B01003: total population for every place, including CDPs
  * 2026 Gazetteer ZCTAs: ZIP code tabulation area centroids, for each city's representative ZIP
  * 2026 Gazetteer counties and the 2020 ZCTA-to-county relationship file: county names, and counties for CDPs

Kept: every incorporated city, town and village, plus CDPs with at least 10,000 people.

    python scripts/build_texas_cities.py [--cache DIR]
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import math
import re
import urllib.request
import zipfile
from collections import defaultdict
from pathlib import Path

GAZ = "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2026_Gazetteer"
URLS = {
    "places": f"{GAZ}/2026_gaz_place_48.txt",
    "counties": f"{GAZ}/2026_gaz_counties_48.txt",
    "zctas": f"{GAZ}/2026_Gaz_zcta_national.zip",
    "pep": "https://www2.census.gov/programs-surveys/popest/datasets/2020-2025/cities/totals/sub-est2025_48.csv",
    "acs": "https://www2.census.gov/programs-surveys/acs/summary_file/2024/table-based-SF/data/5YRData/"
           "acsdt5y2024-b01003.dat",
    "zcta_county": "https://www2.census.gov/geo/docs/maps-data/data/rel2020/zcta520/tab20_zcta520_county20_natl.txt",
}
OUT = Path(__file__).resolve().parents[1] / "plum" / "data" / "texas_cities.json"
KINDS = {"25": "city", "43": "town", "47": "village", "57": "cdp"}
CDP_MIN_POP = 10_000
MOUNTAIN_COUNTIES = {"48141", "48229"}      # El Paso and Hudspeth observe Mountain time; the rest of Texas is Central
NEARBY_MI = 5.0


def fetch(name: str, cache: Path) -> bytes:
    path = cache / URLS[name].rsplit("/", 1)[1]
    if not path.exists():
        print(f"downloading {URLS[name]}")
        req = urllib.request.Request(URLS[name], headers={"User-Agent": "Mozilla/5.0 (compatible; Plum/1.0)"})
        with urllib.request.urlopen(req, timeout=300) as r:
            path.write_bytes(r.read())
    return path.read_bytes()


def table(raw: bytes, delimiter: str) -> list[dict]:
    text = raw.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    return [{(k or "").strip(): (v or "").strip() for k, v in row.items()} for row in reader]


def miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 3958.8 * 2 * math.asin(math.sqrt(a))


def display_name(census_name: str) -> str:
    """'Austin city' -> 'Austin', 'Hilshire Village city' -> 'Hilshire Village', 'The Woodlands CDP' -> 'The Woodlands'."""
    return re.sub(r"\s+(city|town|village|CDP)$", "", census_name).strip()


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower().replace("'", "")).strip("-")


def texas_zcta(code: str) -> bool:
    return code[:2] in {"75", "76", "77", "78", "79"} or code.startswith("885")


def build(cache: Path) -> list[dict]:
    cache.mkdir(parents=True, exist_ok=True)
    places = table(fetch("places", cache), "|")
    counties = {r["GEOID"]: r["NAME"] for r in table(fetch("counties", cache), "|")}

    with zipfile.ZipFile(io.BytesIO(fetch("zctas", cache))) as z:
        zctas = [r for r in table(z.read(z.namelist()[0]), "|") if texas_zcta(r["GEOID"])]
    zpts = [(r["GEOID"], float(r["INTPTLAT"]), float(r["INTPTLONG"])) for r in zctas]

    # Population: Vintage 2025 estimates for incorporated places; ACS 2024 5-year for CDPs and any gaps.
    pep_total, pep_parts = {}, defaultdict(list)
    for r in table(fetch("pep", cache), ","):
        if r["SUMLEV"] == "162":
            pep_total[r["PLACE"]] = int(r["POPESTIMATE2025"])
        elif r["SUMLEV"] == "157" and r["PLACE"] != "00000":
            pep_parts[r["PLACE"]].append((int(r["POPESTIMATE2025"]), "48" + r["COUNTY"]))
    acs = {}
    for line in fetch("acs", cache).decode("utf-8", errors="replace").splitlines():
        if line.startswith("1600000US48"):
            geo, est, *_ = line.split("|")
            acs[geo[-5:]] = int(est) if est.lstrip("-").isdigit() and int(est) >= 0 else None

    # County for places without estimate parts (CDPs): the county holding most of the nearest ZCTA's land.
    zcta_county: dict[str, tuple[int, str]] = {}
    for r in table(fetch("zcta_county", cache), "|"):
        z, c = r.get("GEOID_ZCTA5_20", ""), r.get("GEOID_COUNTY_20", "")
        if z and c.startswith("48"):
            land = int(r.get("AREALAND_PART") or 0)
            if land > zcta_county.get(z, (-1, ""))[0]:
                zcta_county[z] = (land, c)

    rows = []
    for p in places:
        kind = KINDS.get(p["LSAD"])
        if not kind:
            continue
        place = p["GEOID"][2:]
        pop = pep_total.get(place) if kind != "cdp" else None
        pop = pop if pop is not None else acs.get(place)
        if kind == "cdp" and (pop or 0) < CDP_MIN_POP:
            continue
        lat, lon = float(p["INTPTLAT"]), float(p["INTPTLONG"])
        ranked = sorted((miles(lat, lon, zl, zo), z) for z, zl, zo in zpts)
        zip_code = ranked[0][1]
        nearby = [z for d, z in ranked[1:4] if d <= NEARBY_MI]
        parts = sorted(pep_parts.get(place, []), reverse=True)
        county_fips = parts[0][1] if parts else zcta_county.get(zip_code, (0, ""))[1]
        rows.append({
            "name": display_name(p["NAME"]), "state": "TX", "kind": kind, "geoid": p["GEOID"],
            "lat": round(lat, 6), "lon": round(lon, 6), "population": pop,
            "county": counties.get(county_fips, ""), "county_fips": county_fips,
            "zip": zip_code, "nearby_zips": nearby,
            "tz": "America/Denver" if county_fips in MOUNTAIN_COUNTIES else "America/Chicago",
        })

    # Ids: name slugs, disambiguated by county when two places share a name (Texas has two Renos).
    by_slug = defaultdict(list)
    for r in rows:
        by_slug[slug(r["name"])].append(r)
    for s, group in by_slug.items():
        for r in group:
            r["id"] = s if len(group) == 1 else f"{s}-{slug(r['county'])}"
    rows.sort(key=lambda r: (-(r["population"] or 0), r["name"]))
    return [{"id": r.pop("id"), **r} for r in rows]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--cache", type=Path, default=Path.home() / ".cache" / "plum" / "census")
    args = ap.parse_args()
    rows = build(args.cache)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("[\n" + ",\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n]\n")   # one city per line
    kinds = defaultdict(int)
    for r in rows:
        kinds[r["kind"]] += 1
    print(f"wrote {len(rows)} places to {OUT}: {dict(kinds)}")
    missing = [r["id"] for r in rows if r["population"] is None]
    print(f"without population: {len(missing)} {missing[:10]}")


if __name__ == "__main__":
    main()
