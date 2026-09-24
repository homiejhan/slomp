"""Where is the shopper? A city or ZIP -> coordinates plus the ZIP code weekly ads are published for.

Geocoding uses OpenStreetMap's Nominatim (keyless; usage policy: identify yourself, <= 1 request/s, cache results).
"""
from __future__ import annotations

import math
import re
from typing import Any, Optional

from .models import Place
from .net import HttpClient

NOMINATIM = "https://nominatim.openstreetmap.org"
KM_PER_MILE = 1.609344
_TTL_S = 30 * 86400                     # places don't move
_ZIP = re.compile(r"\d{5}(?:-\d{4})?")
_SETTLEMENTS = {"city", "town", "village", "hamlet", "municipality", "suburb", "borough", "neighbourhood"}


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371.0088 * math.asin(math.sqrt(a))


def _zip5(raw: Any) -> Optional[str]:
    m = re.search(r"\d{5}", str(raw or ""))
    return m.group(0) if m else None


def _label(row: dict) -> str:
    a = row.get("address") or {}
    town = next((a[k] for k in ("city", "town", "village", "hamlet", "municipality") if a.get(k)), None)
    parts = [p for p in (town, a.get("state")) if p]
    return ", ".join(parts) or row.get("display_name", "")


class Geocoder:
    def __init__(self, http: HttpClient):
        self.http = http

    async def resolve(self, where: str) -> Place:
        where = " ".join(where.split())
        if not where:
            raise LookupError("say where: a city like 'Austin, TX' or a ZIP code")
        if _ZIP.fullmatch(where):
            return await self._zip(where[:5])
        return await self._city(where)

    async def _city(self, q: str) -> Place:
        rows = await self.http.get_json(f"{NOMINATIM}/search", {
            "q": q, "countrycodes": "us", "format": "jsonv2", "addressdetails": 1, "limit": 5}, ttl_s=_TTL_S)
        if not rows:
            raise LookupError(f"couldn't find a US place called {q!r}")
        # "Austin" should mean the city, not Austin County or a street; fall back to the top hit otherwise.
        row = next((r for r in rows if r.get("addresstype") in _SETTLEMENTS), rows[0])
        lat, lon = float(row["lat"]), float(row["lon"])
        zip_code = _zip5((row.get("address") or {}).get("postcode")) or await self._zip_at(lat, lon)
        return Place(q, _label(row), lat, lon, zip_code)

    async def _zip_at(self, lat: float, lon: float) -> str:
        row = await self.http.get_json(f"{NOMINATIM}/reverse", {
            "lat": f"{lat:.6f}", "lon": f"{lon:.6f}", "format": "jsonv2", "addressdetails": 1, "zoom": 18}, ttl_s=_TTL_S)
        z = _zip5(((row or {}).get("address") or {}).get("postcode"))
        if not z:
            raise LookupError("couldn't find a ZIP code for that place; pass a ZIP instead")
        return z

    async def _zip(self, z: str) -> Place:
        rows = await self.http.get_json(f"{NOMINATIM}/search", {
            "postalcode": z, "countrycodes": "us", "format": "jsonv2", "addressdetails": 1, "limit": 1}, ttl_s=_TTL_S)
        if not rows:
            raise LookupError(f"unknown US ZIP code {z}")
        row = rows[0]
        return Place(z, _label(row), float(row["lat"]), float(row["lon"]), z)
