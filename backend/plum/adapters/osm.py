"""Store locations from OpenStreetMap (Overpass API): is there actually a <merchant> near this place?

OSM is community-mapped. National chains are well covered; some regional chains are only partly mapped (La Michoacana
Meat Market has Austin stores that aren't on the map). So a merchant with no mapped store nearby is reported as
unmapped or far, never as "no store", and nothing is dropped on that basis unless the caller asks for it.

Matching is strict: a salon named "Belk Beauty" is not a Belk department store, and a "La Michoacana" ice-cream shop is
not La Michoacana Meat Market. A map feature counts only if its brand or name *is* the merchant, optionally followed by
store-type words ("Walmart Neighborhood Market", "H-E-B plus!") or a store number.
"""
from __future__ import annotations

import math
import re
from typing import Iterable, Optional

from ..geo import haversine_km
from ..models import Place, Presence, Store, StorePresence
from ..net import HttpClient, HttpError

# The public Overpass servers are volunteer-run and often busy; try the next one rather than hammering one.
OVERPASS_MIRRORS = ("https://overpass-api.de/api/interpreter",
                    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
                    "https://overpass.private.coffee/api/interpreter")
TTL_S = 7 * 86400                      # stores open and close slowly
TIMEOUT_S = 120.0                      # the query itself allows the server 90 s
WIDE_KM = 160.0                        # second look for merchants with nothing in range: "mapped but far" vs unmapped

# Weekly-ad merchant name -> other names its stores carry on the map.
ALIASES = {
    "cvs pharmacy": ("cvs",),
    "health mart pharmacy": ("health mart",),
    "home depot": ("the home depot",),
    "jcpenney": ("jc penney", "jcp"),
    "michaels usa": ("michaels",),
    "office depot officemax": ("office depot", "officemax"),
    "sprouts farmers market": ("sprouts",),
    "tractor supply company": ("tractor supply",),
    "ulta": ("ulta beauty",),
    "harbor freight tools": ("harbor freight",),
    "costco": ("costco wholesale",),
    "lowe's": ("lowe's home improvement",),
    "coastal farm": ("coastal farm & ranch", "coastal farm supply", "coastal farm & home supply"),
}
# Words that may follow a merchant's name on the same business's store.
STORE_WORDS = {"store", "stores", "supercenter", "superstore", "neighborhood", "market", "marketplace", "plus", "express",
               "outlet", "pharmacy", "garden", "center", "centre", "tire", "tires", "auto", "care", "wholesale",
               "warehouse", "liquor", "grocery", "supermarket", "mercado", "home", "improvement", "fresh", "no"}
NOT_A_STORE = {"fuel", "charging_station", "car_wash", "atm", "parking", "vending_machine", "parcel_locker"}
# Parts of a store mapped as their own pins ("H-E-B Pharmacy", "Walmart Tire and Lube"): same place, not another store.
DEPARTMENTS = {"pharmacy", "garden", "tire", "tires", "auto", "liquor", "vision", "optical", "photo", "fuel", "gas"}
_KINDS = ("shop", "amenity", "building", "healthcare", "office", "craft", "brand")


def words(s: str) -> list[str]:
    """Apostrophes split words ("Kohl's" -> kohl, s) so the map regex tolerates Kohl's / Kohl’s / Kohls alike."""
    return re.findall(r"[a-z0-9]+", (s or "").lower().replace("&", " and "))


def compact(s: str) -> str:
    return "".join(words(s))


def names_for(merchant: str) -> list[str]:
    key = " ".join(words(merchant))
    return [merchant, *ALIASES.get(merchant.lower().strip(), ALIASES.get(key, ()))]


def is_merchant(value: str, merchant_names: Iterable[str], extra_words: frozenset[str] = frozenset(),
                brand: bool = False) -> bool:
    """`value` names this merchant: its first words spell the merchant and the rest are store words or numbers.

    A `brand` tag names a chain, so any continuation counts there ("Coastal Farm & Ranch" is Coastal Farm); a free-text
    name needs the strict rule ("Belk Beauty" is a salon)."""
    ws = words(value.split(" - ")[0].split("(")[0])
    for name in merchant_names:
        target = compact(name)
        for k in range(1, len(ws) + 1):
            if "".join(ws[:k]) == target:
                rest = ws[k:]
                if brand or all(w in STORE_WORDS or w in extra_words or w.isdigit() for w in rest):
                    return True
                break
            if len("".join(ws[:k])) >= len(target):
                break
    return False


def _pattern(name: str) -> str:
    """Overpass (POSIX) regex matching the name however it's punctuated: H-E-B / HEB, Kohl's / Kohls, & / and."""
    parts = ["(and|&)" if w == "and" else w for w in words(name)]
    return "[^a-zA-Z0-9]*".join(parts)


def bbox(lat: float, lon: float, radius_km: float) -> tuple[float, float, float, float]:
    """(south, west, north, east) enclosing the circle. Overpass answers box queries several times faster than
    `around:` ones (12 s vs 80 s for Austin); true distances are checked afterwards."""
    dlat = radius_km / 111.32
    dlon = radius_km / (111.32 * max(math.cos(math.radians(lat)), 0.01))
    return lat - dlat, lon - dlon, lat + dlat, lon + dlon


def overpass_query(merchants: Iterable[str], box: tuple[float, float, float, float], *, names: bool = True) -> str:
    """Features whose brand (and optionally name) starts like a merchant's. Name matching is what finds unbranded
    features such as Austin's Restaurant Depot, but it is slow over large areas, so wide searches skip it."""
    alts = "|".join(sorted({_pattern(n) for m in merchants for n in names_for(m) if words(n)}))
    where = "({:.5f},{:.5f},{:.5f},{:.5f})".format(*box)
    by_name = f'nwr["name"~"^({alts})",i]{where};' if names else ""
    return f'[out:json][timeout:90];(nwr["brand"~"^({alts})",i]{where};{by_name});out center tags;'


def _is_department(s: Store) -> bool:
    return bool(set(words(s.name)) & DEPARTMENTS)


def main_store(stores: list[Store]) -> Store:
    """The nearest store, preferring the building itself over its pharmacy or garden-center pin next door."""
    first = stores[0]
    if not _is_department(first):
        return first
    twin = next((s for s in stores[1:] if not _is_department(s)
                 and haversine_km(first.lat, first.lon, s.lat, s.lon) <= 0.3), None)
    return twin or first


def _address(tags: dict) -> str:
    street = " ".join(p for p in (tags.get("addr:housenumber"), tags.get("addr:street")) if p)
    return ", ".join(p for p in (street, tags.get("addr:city")) if p)


class StoreLocator:
    name = "OpenStreetMap store locations"

    def __init__(self, http: HttpClient, urls: tuple[str, ...] = OVERPASS_MIRRORS):
        self.http, self.urls = http, urls

    async def _elements(self, merchants: list[str], place: Place, radius_km: float, *, names: bool = True) -> list[dict]:
        if not merchants:
            return []
        query = {"data": overpass_query(merchants, bbox(place.lat, place.lon, radius_km), names=names)}
        err: Optional[HttpError] = None
        for url in self.urls:
            try:
                data = await self.http.post_json(url, query, ttl_s=TTL_S, timeout_s=TIMEOUT_S, retries=2)
                return list((data or {}).get("elements") or [])
            except HttpError as e:
                err = e
        raise err or HttpError("no Overpass server configured")

    def _stores(self, elements: list[dict], merchants: list[str], place: Place) -> dict[str, list[Store]]:
        extra = frozenset(words(place.name))           # "Harbor Freight Tools Austin"
        names = {m: names_for(m) for m in merchants}
        found: dict[str, list[Store]] = {m: [] for m in merchants}
        seen: set[tuple[str, str]] = set()
        for el in elements:
            tags = el.get("tags") or {}
            if tags.get("amenity") in NOT_A_STORE or tags.get("shop") in NOT_A_STORE or not any(k in tags for k in _KINDS):
                continue
            label = tags.get("name") or tags.get("brand") or ""
            m = next((m for m in merchants if any(is_merchant(tags[k], names[m], extra, brand=k == "brand")
                                                  for k in ("brand", "name") if tags.get(k))), None)
            key = f"{el.get('type')}/{el.get('id')}"
            if m is None or (m, key) in seen:
                continue
            seen.add((m, key))
            lat = el.get("lat", (el.get("center") or {}).get("lat"))
            lon = el.get("lon", (el.get("center") or {}).get("lon"))
            if lat is None or lon is None:
                continue
            found[m].append(Store(m, label, lat, lon, _address(tags), round(haversine_km(place.lat, place.lon, lat, lon), 2),
                                  f"https://www.openstreetmap.org/{key}"))
        for stores in found.values():
            stores.sort(key=lambda s: s.distance_km)
        return found

    async def presence(self, place: Place, merchants: Iterable[str], radius_km: float) -> dict[str, StorePresence]:
        ms = sorted(set(merchants))
        found = self._stores(await self._elements(ms, place, radius_km), ms, place)
        missing = [m for m in ms if not any(s.distance_km <= radius_km for s in found[m])]
        if missing:
            wide = self._stores(await self._elements(missing, place, max(WIDE_KM, radius_km * 2), names=False),
                                missing, place)
            for m in missing:
                found[m] = sorted(found[m] + wide[m], key=lambda s: s.distance_km)
        out: dict[str, StorePresence] = {}
        for m in ms:
            in_range = [s for s in found[m] if s.distance_km <= radius_km]
            if in_range:
                stores = sum(not _is_department(s) for s in in_range) or len(in_range)
                out[m] = StorePresence(m, Presence.CONFIRMED, main_store(in_range), stores)
            else:
                nearest: Optional[Store] = found[m][0] if found[m] else None
                out[m] = StorePresence(m, Presence.FAR if nearest else Presence.UNMAPPED, nearest)
        return out
