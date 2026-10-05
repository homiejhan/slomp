"""Where a regular deal's places are: one lookup over the three offline OpenStreetMap datasets.

  restaurants_tx.json   US restaurant chains (brands from the OSM Name Suggestion Index)
  venues_tx.json        cinemas, entertainment venues and Texas chains listed in venue_brands.json
  stores_tx.json        retail merchants (merchants.json)

`find()` resolves a chain's name as a deal page spells it, and `nearest()` gives its closest branch to a city.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional

from ..geo import miles
from ..models import City, Store
from ..reference import DATA, fold, merchants
from .stores import _dataset, _restaurants

KIND_INDUSTRIES = {"restaurant": ("dining",), "cafe": ("dining",), "bar": ("dining",), "cinema": ("entertainment",),
                   "golf": ("entertainment",), "bowling": ("entertainment",), "arcade": ("entertainment",),
                   "museum": ("entertainment",), "zoo": ("entertainment",)}
MIN_PREFIX = 6              # a name this short or shorter must match exactly ("Jack's" is not "Jack's Family Restaurants")
MIN_LOCATIONS_LOOSE = 3     # chains matched loosely need this many mapped places


@dataclass(frozen=True)
class Chain:
    key: str                          # "r:Q1234", "v:cinemark", "s:Kohl's"
    name: str
    kind: str                         # restaurant | cafe | bar | cinema | golf | bowling | museum | zoo | store
    industries: tuple[str, ...]
    locations: tuple                  # rows of (lat, lon, place name, address, ref)


@lru_cache(maxsize=1)
def _venues() -> dict:
    path = DATA / "venues_tx.json"
    return json.loads(path.read_text()) if path.exists() else {"built": "", "venues": {}}


@lru_cache(maxsize=1)
def _spec() -> dict:
    return json.loads((DATA / "venue_brands.json").read_text())


@lru_cache(maxsize=1)
def _unlisted() -> dict[str, frozenset[str]]:
    """Per chain, the mapped branches its own store locator no longer lists (scripts/build_branch_checks.py).
    The map keeps a restaurant long after it closes; the chain's locator does not."""
    path = DATA / "branch_checks.json"
    if not path.exists():
        return {}
    return {name: frozenset(row.get("unlisted") or []) for name, row in json.loads(path.read_text())["chains"].items()
            if row.get("used")}


@lru_cache(maxsize=2)
def _chains(listed_only: bool = True) -> tuple[dict[str, Chain], dict[str, str]]:
    """(chains by key, comparison name -> chain key). Venue names win over restaurants, restaurants over stores.
    `listed_only` leaves out branches the chain's own locator no longer lists."""
    chains: dict[str, Chain] = {}
    names: dict[str, str] = {}

    def claim(name: str, key: str, strong: bool = False) -> None:
        """Two chains can share a name ("Taco Bell" and "Taco Bell Cantina" both answer to "Taco Bell"): the one
        with more mapped places keeps it, unless a venue rule claims it outright."""
        k = fold(name)
        if len(k) >= 2 and (strong or k not in names or len(chains[key].locations) > len(chains[names[k]].locations)):
            names[k] = key

    for m in merchants():
        rows = _dataset()["merchants"].get(m.name) or []
        if rows:
            key = f"s:{m.name}"
            chains[key] = Chain(key, m.name, "store", tuple(m.industries), tuple(tuple(r) for r in rows))
            for n in {m.name, *m.osm_names, *m.flipp}:
                claim(n, key)
    for qid, b in _restaurants()["brands"].items():
        if not b.get("tagged", 1):
            continue                  # every mapped place matched by name alone: likely unrelated places
        key = f"r:{qid}"
        shown = _spec().get("display", {}).get(b["name"], b["name"])
        chains[key] = Chain(key, shown, "restaurant", ("dining",),
                            tuple((lat, lon, shown, addr, ref) for lat, lon, addr, ref in b["locations"]))
        for n in {b["name"], *b.get("aliases", [])}:
            claim(n, key)
    spec = {v["key"]: v for v in _spec()["venues"]}
    for vkey, v in _venues()["venues"].items():
        if not v["locations"]:
            continue
        key = f"v:{vkey}"
        inds = tuple(v.get("industries") or KIND_INDUSTRIES.get(v["kind"], ()))
        chains[key] = Chain(key, v["name"], v["kind"], inds, tuple(tuple(r) for r in v["locations"]))
        for n in {v["name"], *spec.get(vkey, {}).get("names", [])}:
            claim(n, key, strong=True)
    if listed_only:
        gone = _unlisted()
        for key, c in chains.items():
            if gone.get(c.name):
                chains[key] = Chain(c.key, c.name, c.kind, c.industries,
                                    tuple(r for r in c.locations if str(r[4]) not in gone[c.name]))
    return chains, names


class Venues:
    name = "OpenStreetMap venues"

    def built(self) -> str:
        return _venues().get("built", "")

    def get(self, key: str) -> Optional[Chain]:
        return _chains()[0].get(key)

    def find(self, name: str) -> Optional[Chain]:
        """The chain a deal page means by `name`: an exact name or alias, else a known name that starts it
        ("Freebirds World Burrito"), else a known name it starts ("Applebee's")."""
        chains, names = _chains()
        spec = _spec()
        raw = (name or "").replace("’", "'").strip()
        alias = {fold(k): v for k, v in spec["aliases"].items()}
        key = fold(alias.get(fold(raw), raw))
        if not key or fold(raw) in {fold(x) for x in spec["not_these"]}:
            return None
        if key in names:
            return chains[names[key]]
        loose = [k for k in names if len(k) >= MIN_PREFIX and key.startswith(k)]
        if not loose and len(key) >= MIN_PREFIX:
            starts = {names[k] for k in names if k.startswith(key)}
            loose = [k for k in names if k.startswith(key)] if len(starts) == 1 else []
        if loose:
            c = chains[names[max(loose, key=len)]]
            return c if len(c.locations) >= MIN_LOCATIONS_LOOSE else None
        return None

    @staticmethod
    def nearest(chain: Chain, city: City, area: Optional[dict] = None) -> Optional[Store]:
        """The chain's closest mapped place to the city. `area` ({"lat", "lon", "mi"}) limits it to places a regional
        operator runs (Goodwill Central Texas is not Goodwill Houston)."""
        best, best_d = None, 0.0
        for row in chain.locations:
            if area and miles(area["lat"], area["lon"], row[0], row[1]) > area["mi"]:
                continue
            d = miles(city.lat, city.lon, row[0], row[1])
            if best is None or d < best_d:
                best, best_d = row, d
        if best is None:
            return None
        lat, lon, place, address, ref = best
        return Store(merchant=chain.name, name=place or chain.name, lat=lat, lon=lon, address=address,
                     distance_mi=round(best_d, 1), source="osm", ref=ref)
