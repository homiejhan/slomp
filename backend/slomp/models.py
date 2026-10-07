"""Domain objects. Everything a response shows is one of these, serialized by `to_dict`."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Optional

# What a discount is measured against, strongest first, and how much ranking trusts each.
BASIS_WEIGHT = {
    "market": 1.0,           # below the median current price at 2+ other sites Slomp checked itself
    "store_regular": 0.9,    # below the same store's own stated regular / was price
    "editor_compare": 0.8,   # an editor's statement about other stores' prices ("you'd pay $65 elsewhere")
    "claimed_savings": 0.6,  # the ad states a saving but not the regular price it is measured from
    "history": 0.6,          # a price-history claim ("lowest price Amazon has charged")
    "list": 0.5,             # list price, MSRP, compare-at, "value"
    "none": 0.0,             # no reference: a price, not a discount
}
BASIS_TEXT = {
    "market": "vs other stores' current prices (checked by Slomp)",
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
    regular: Optional[dict] = None         # set on regular deals: schedule, next dates, evidence (see regulars.py)
    raw: dict = field(default_factory=dict, repr=False)

    @property
    def kind(self) -> str:
        if self.regular:
            return "regular"
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
    store_check: dict = field(default_factory=dict)      # the seller's live page, when Slomp read it
    store_key: str = ""                 # the seller in the online-store registry (data/online_stores.json), if there
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


@dataclass(frozen=True)
class OnlineStore:
    """A store that sells online and ships anywhere in Texas (data/online_stores.json)."""
    key: str
    name: str
    aliases: tuple[str, ...] = ()
    domains: tuple[str, ...] = ()
    dealnews: str = ""                 # its store feed on dealnews: "318/Target"
    sells: tuple[str, ...] = ()        # industries a store-wide sale there counts for; empty = anything
    site: str = ""
    brand: bool = False                # also a brand other stores sell: its name alone doesn't place a sale
    events: tuple[str, ...] = ()       # sale events only this store runs ("Prime Big Deal Days")

    @property
    def names(self) -> tuple[str, ...]:
        return (self.name, *self.aliases)


@dataclass
class StoreSale:
    """A sale on many products at an online store: store-wide, a category, a brand, or a sale event."""
    id: str
    store: str                          # registry key; "" for a store the registry doesn't know
    store_name: str
    title: str                          # the post's own title
    name: str                           # the sale in a few words, without the store or the offer
    offer: str                          # the offer in words, written from the parts below
    badge: str                          # the offer in one short label: "Up to 60% off", "Extra 20% off"
    badge_soft: bool = False            # the badge is a ceiling or needs a purchase ("Up to 60%", "$15 off")
    pct: Optional[float] = None         # firm percent off
    upto: Optional[float] = None        # a ceiling: "up to 60% off"
    extra: Optional[float] = None       # an extra percent off, usually on sale prices
    extra_upto: Optional[float] = None  # the top of an extra percent that varies ("extra 10% to 35% off")
    off: Optional[float] = None         # dollars off
    off_upto: bool = False              # "up to $260 off"
    min_spend: Optional[float] = None   # "$10 off $30": the order the dollars need
    bogo: str = ""                      # "buy 1 get 1 50% off"
    bogo_pct: Optional[float] = None    # its saving per item when buying the set
    code: str = ""                      # a promo code the post states
    code_note: str = ""                 # what the code is for, when not the discount itself ("for free delivery")
    conditions: list[str] = field(default_factory=list)
    shipping: str = ""                  # "Free shipping on $35+", "Free shipping with Prime"
    sitewide: bool = False
    starts_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None
    ends_how: str = ""                  # where the end comes from: "dealnews gives this end date", "the post says …"
    posted_at: Optional[datetime] = None
    source: str = ""                    # "dealnews", "Hip2Save", ...
    source_url: str = ""
    image_url: str = ""
    industries: list[str] = field(default_factory=list)
    industry_rule: str = ""
    also_posted: list[dict] = field(default_factory=list)
    checked_at: Optional[datetime] = None   # when Slomp last read the post page and found it live
    discount_pct: Optional[float] = None    # what "best deal first" ranks by (docs/DESIGN-online-stores.md 4.5)
    score: float = 0.0
    raw: dict = field(default_factory=dict, repr=False)

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("raw", None)
        d["kind"] = "sale"
        return _clean(d)
