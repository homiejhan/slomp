"""Where the stores are: OpenStreetMap, from a Texas dataset built weekly by scripts/build_stores.py.

Store locations change slowly, and the public Overpass servers were too slow or blocking to query per request, so
lookups are local: the nearest mapped store of each merchant to the city's census internal point.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Iterable, Optional

from ..geo import miles
from ..models import City, Merchant, Store
from ..reference import DATA, norm

MAX_RADIUS_MI = 50.0


@lru_cache(maxsize=1)
def _dataset() -> dict:
    path = DATA / "stores_tx.json"
    return json.loads(path.read_text()) if path.exists() else {"built": "", "merchants": {}}


@lru_cache(maxsize=1)
def _restaurants() -> dict:
    path = DATA / "restaurants_tx.json"
    return json.loads(path.read_text()) if path.exists() else {"built": "", "brands": {}}


@lru_cache(maxsize=1)
def _restaurant_names() -> dict[str, str]:
    out: dict[str, str] = {}
    for qid, b in _restaurants()["brands"].items():
        for a in [b["name"], *b.get("aliases", [])]:
            out.setdefault(norm(a), qid)
    return out


@dataclass
class StoreMap:
    """Mapped stores near a city, nearest first, by merchant name."""
    stores: dict[str, list[Store]] = field(default_factory=dict)
    source_ok: bool = True
    built: str = ""
    error: str = ""

    def nearest(self, merchant: str) -> Optional[Store]:
        found = self.stores.get(merchant) or []
        return found[0] if found else None


def _store(merchant: str, row: list, city: City, source: str = "osm") -> Store:
    lat, lon, name, address, ref = row
    return Store(merchant=merchant, name=name, lat=lat, lon=lon, address=address,
                 distance_mi=round(miles(city.lat, city.lon, lat, lon), 1), source=source, ref=ref)


class StoreLocator:
    name = "OpenStreetMap stores"

    def built(self) -> str:
        return _dataset().get("built", "")

    def near(self, city: City, merchants: Iterable[Merchant], max_mi: float = MAX_RADIUS_MI) -> StoreMap:
        data = _dataset()["merchants"]
        if not data:
            return StoreMap({}, False, "", "store dataset missing: run scripts/build_stores.py")
        out: dict[str, list[Store]] = {}
        for m in merchants:
            rows = data.get(m.name) or []
            found = [s for s in (_store(m.name, r, city) for r in rows) if s.distance_mi <= max_mi]
            if found:
                out[m.name] = sorted(found, key=lambda s: s.distance_mi)
        return StoreMap(out, True, self.built())

    def known(self, merchant: Merchant) -> bool:
        """Whether the map has any store of this merchant at all (in or near Texas)."""
        return bool(_dataset()["merchants"].get(merchant.name))


class RestaurantLocator:
    name = "OpenStreetMap restaurants"

    def built(self) -> str:
        return _restaurants().get("built", "")

    def brand(self, name: str) -> Optional[tuple[str, str]]:
        """(wikidata id, canonical name) for a restaurant chain named in a promotion, if the map knows it."""
        key = norm(name)
        qid = _restaurant_names().get(key)
        if not qid:
            # "Wingstop restaurants", "Chuy's Tex-Mex": try the longest known brand name the text starts with.
            for k, q in sorted(_restaurant_names().items(), key=lambda kv: -len(kv[0])):
                if len(k) >= 4 and key.startswith(k):
                    qid = q
                    break
        if not qid:
            return None
        return qid, _restaurants()["brands"][qid]["name"]

    def nearest(self, qid: str, city: City) -> Optional[Store]:
        b = _restaurants()["brands"].get(qid)
        if not b:
            return None
        best: Optional[Store] = None
        for lat, lon, address, ref in b["locations"]:
            d = miles(city.lat, city.lon, lat, lon)
            if best is None or d < best.distance_mi:
                best = Store(merchant=b["name"], name=b["name"], lat=lat, lon=lon, address=address,
                             distance_mi=round(d, 1), source="osm", ref=ref)
        return best
