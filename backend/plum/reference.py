"""The fixed inputs: Texas cities (built from Census data by scripts/build_texas_cities.py) and the merchant registry."""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Optional

from .models import City, Merchant

DATA = Path(__file__).parent / "data"


def norm(text: str) -> str:
    """Comparison key for names: lowercase, '&' as 'and', letters and digits only."""
    return re.sub(r"[^a-z0-9]", "", (text or "").lower().replace("&", "and"))


@lru_cache(maxsize=1)
def cities() -> tuple[City, ...]:
    rows = json.loads((DATA / "texas_cities.json").read_text())
    return tuple(City(**r) for r in rows)


@lru_cache(maxsize=1)
def _city_index() -> dict[str, City]:
    return {c.id: c for c in cities()}


def city(city_id: str) -> Optional[City]:
    return _city_index().get((city_id or "").strip().lower())


def find_cities(query: str, limit: int = 10) -> list[City]:
    """Prefix matches first, then substring matches; larger places first within each group."""
    q = norm(re.sub(r",?\s*(tx|texas)$", "", query.strip(), flags=re.I))
    if not q:
        return list(cities()[:limit])
    prefix = [c for c in cities() if norm(c.name).startswith(q)]
    inner = [c for c in cities() if q in norm(c.name) and c not in prefix]
    return (prefix + inner)[:limit]


@lru_cache(maxsize=1)
def merchants() -> tuple[Merchant, ...]:
    rows = json.loads((DATA / "merchants.json").read_text())
    return tuple(Merchant(**r) for r in rows)


@lru_cache(maxsize=1)
def _merchant_index() -> dict[str, Merchant]:
    idx: dict[str, Merchant] = {}
    for m in merchants():
        for n in [m.name, *m.flipp]:
            idx[norm(n)] = m
    return idx


def merchant(name: str) -> Merchant:
    """The registry entry for a merchant name as Flipp spells it. Unknown merchants get a name-only entry, so they
    still work (exact-name store matching) and can be added to the registry later."""
    found = _merchant_index().get(norm(name))
    if found:
        return found
    clean = (name or "").strip()
    return Merchant(name=clean, flipp=[clean], wikidata=[], osm_names=[clean], domains=[], industries=[])


ONLINE_STORES = {
    "amazon.com": "Amazon", "woot.com": "Woot", "ebay.com": "eBay", "newegg.com": "Newegg", "bhphotovideo.com": "B&H",
    "adorama.com": "Adorama", "aliexpress.com": "AliExpress", "aliexpress.us": "AliExpress", "temu.com": "Temu",
    "nike.com": "Nike", "adidas.com": "adidas", "wayfair.com": "Wayfair", "chewy.com": "Chewy", "zappos.com": "Zappos",
    "nordstrom.com": "Nordstrom", "nordstromrack.com": "Nordstrom Rack", "rei.com": "REI", "lenovo.com": "Lenovo",
    "dell.com": "Dell", "hp.com": "HP", "apple.com": "Apple", "samsung.com": "Samsung", "microcenter.com": "Micro Center",
    "staples.com": "Staples", "sephora.com": "Sephora", "gap.com": "Gap", "llbean.com": "L.L.Bean", "vevor.com": "VEVOR",
    "ashford.com": "Ashford", "menswearhouse.com": "Men's Wearhouse", "jomashop.com": "Jomashop", "dsw.com": "DSW",
}


def store_from_domain(domain: str) -> str:
    """'www.amazon.com' -> 'Amazon'; registry merchants by their domains; otherwise the domain itself."""
    d = (domain or "").lower().strip().removeprefix("www.")
    if not d:
        return ""
    for m in merchants():
        if any(d == x or d.endswith("." + x) for x in m.domains):
            return m.name
    for k, v in ONLINE_STORES.items():
        if d == k or d.endswith("." + k):
            return v
    return d
