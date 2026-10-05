"""Domain objects. Everything a response shows is one of these, serialized by `to_dict`."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Optional

# What a discount is measured against, strongest first, and how much ranking trusts each.
BASIS_WEIGHT = {
    "market": 1.0,           # below the median current price at 2+ other sites Plum checked itself
    "store_regular": 0.9,    # below the same store's own stated regular / was price
    "editor_compare": 0.8,   # an editor's statement about other stores' prices ("you'd pay $65 elsewhere")
    "claimed_savings": 0.6,  # the ad states a saving but not the regular price it is measured from
    "history": 0.6,          # a price-history claim ("lowest price Amazon has charged")
    "list": 0.5,             # list price, MSRP, compare-at, "value"
    "none": 0.0,             # no reference: a price, not a discount
}
BASIS_TEXT = {
    "market": "vs other stores' current prices (checked by Plum)",
    "store_regular": "vs the store's own regular price",
    "editor_compare": "vs other stores, per the deal's editor",
    "claimed_savings": "saving stated by the ad; no regular price given",
    "history": "vs this product's own price history",
    "list": "vs list price / MSRP",
    "none": "no regular price given",
}


def _iso(v: Any) -> Any:
    return v.isoformat() if isinstance(v, datetime) else v


def _clean(d: Any) -> Any:
    if isinstance(d, dict):
        return {k: _clean(v) for k, v in d.items()}
    if isinstance(d, list):
        return [_clean(v) for v in d]
    return _iso(d)


@dataclass
class City:
    id: str
    name: str
    kind: str
    county: str
    county_fips: str
    lat: float
    lon: float
    population: Optional[int]
    zip: str
    nearby_zips: list[str]
    tz: str
    geoid: str = ""
    state: str = "TX"

    @property
    def label(self) -> str:
        return f"{self.name}, TX"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Merchant:
    name: str
    flipp: list[str]
    wikidata: list[str]
    osm_names: list[str]
    domains: list[str]
    industries: list[str]
    membership: str = ""
    map_coverage: str = ""      # "sparse": the map misses many of this chain's stores, so absence proves nothing
    exclusive: bool = False     # sells one kind of thing (PetSmart, Ulta, AutoZone): its items are that industry
    sells: list[str] = field(default_factory=list)   # industries the store plausibly sells; empty = anything
    food: bool = True           # False: a "Food" label on its ad items is a mislabel unless the words agree


@dataclass
class Store:
    merchant: str
    name: str
    lat: float
    lon: float
    address: str
    distance_mi: float
    source: str                 # "osm" or "atp"
    ref: str                    # "osm:way/123" or "atp:target_us:638"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Terms:
    """What a deal promises, per unit, after reading all of its text."""
    price: Optional[float] = None          # per-unit price the deal gives (multi-buys divided out)
    regular: Optional[float] = None        # per-unit reference price the saving is measured from
    savings: Optional[float] = None        # per-unit dollars saved
    pct: Optional[float] = None            # effective percent saved
    basis: str = "none"
    qty: int = 1                           # "2 for $8" -> 2
    bundle_price: Optional[float] = None   # "2 for $8" -> 8.0
    bogo: str = ""                         # "buy 1 get 1 free", "buy 2 get 1 50% off"
    hedge: str = ""                        # "up to", "starting at", "from", "select items"
    unit: str = ""                         # "lb", "oz", "ea"
    conditions: list[str] = field(default_factory=list)
    promo: bool = False                    # a percent- or dollars-off promotion without one firm item price
    summary: str = ""
    rejected: str = ""                     # why a stated saving wasn't believed ("99.6% off: likely an ad error")

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class LocalDeal:
    id: str
    item_id: int
    flyer_id: int
    title: str
    merchant: str
    brand: str
    industries: list[str]
    industry_rule: str
    category: str
    terms: Terms
    valid_from: datetime
    valid_to: datetime
    source_url: str
    retailer_url: str = ""
    image_url: str = ""
    store: Optional[Store] = None
    store_status: str = "unknown"          # nearby | unmapped | far
    feed: bool = False                     # from the retailer's own product feed (its ad picture is a product card)
    detailed: bool = False
    score: float = 0.0
    starts_in_days: int = 0
    ends_in_days: int = 0
    raw: dict = field(default_factory=dict, repr=False)

    @property
    def kind(self) -> str:
        return "promotion" if (self.terms.promo or self.terms.hedge or self.terms.bogo) else "deal"

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("raw", None)
        d["kind"] = self.kind
        d["basis_text"] = BASIS_TEXT.get(self.terms.basis, "")
        return _clean(d)


@dataclass
class Identity:
    brand: str = ""
    model: str = ""
    gtin: str = ""
    attrs: dict[str, str] = field(default_factory=dict)   # screen, storage, size, pack, condition
    accessory: bool = False

    @property
    def key(self) -> str:
        if self.gtin:
            return f"gtin:{self.gtin}"
        return f"{self.brand.lower()}|{self.model}" if self.brand and self.model else ""

    def to_dict(self) -> dict:
        return {**asdict(self), "key": self.key}


@dataclass
class PricePoint:
    site: str
    price: float
    url: str
    title: str
    match: str                 # "gtin" | "model"
    observed_at: datetime
    regular_price: Optional[float] = None
    in_stock: Optional[bool] = None
    via: str = ""              # how it was found: "amazon search", "flipp weekly ad", "feed post", ...

    def to_dict(self) -> dict:
        return _clean(asdict(self))


@dataclass
class OnlineDeal:
    id: str
    source: str                         # "dealnews" | "slickdeals"
    source_url: str
    title: str
    seller: str
    price: float
    industries: list[str]
    industry_rule: str
    category: str = ""
    reference_price: Optional[float] = None
    basis: str = "none"
    basis_text: str = ""                # the post's own words for its reference ("That's a $65 savings")
    pct: Optional[float] = None         # discount vs the post's own reference
    product: Identity = field(default_factory=Identity)
    comparisons: list[PricePoint] = field(default_factory=list)
    market_median: Optional[float] = None
    verified_pct: Optional[float] = None
    conditions: list[str] = field(default_factory=list)
    posted_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    merchant_url: str = ""
    image_url: str = ""
    also_posted: list[dict] = field(default_factory=list)
    store_check: dict = field(default_factory=dict)      # the seller's live page, when Plum read it
    score: float = 0.0
    raw: dict = field(default_factory=dict, repr=False)

    @property
    def discount_pct(self) -> Optional[float]:
        return self.verified_pct if self.verified_pct is not None else self.pct

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("raw", None)
        d["product"] = self.product.to_dict()
        d["discount_pct"] = self.discount_pct
        d["basis_label"] = BASIS_TEXT.get(self.basis, "")
        return _clean(d)
