from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Condition(str, Enum):
    NEW = "new"
    REFURBISHED = "refurbished"
    OPEN_BOX = "open box"
    USED = "used"


class CouponType(str, Enum):
    PERCENT = "percent"
    FIXED = "fixed"
    FREESHIP = "freeship"


class Scope(str, Enum):
    SITEWIDE = "sitewide"
    CATEGORY = "category"
    PRODUCT = "product"


class Tier(str, Enum):
    EXACT = "exact"          # shared, valid GTIN
    CONFIDENT = "confident"  # model code + strong word overlap
    LIKELY = "likely"        # good overlap, worth showing with a caveat
    REJECTED = "rejected"


@dataclass(frozen=True)
class RetailerPolicy:
    id: str
    name: str
    free_shipping_over: float
    flat_shipping: float
    cashback_rate: float = 0.0
    trust: float = 0.9          # 0..1; used only as a tiebreaker, never to reorder by commission
    timeout_ms: int = 1200


@dataclass
class Product:
    id: str
    brand: str
    title: str
    category: str
    list_price: float
    gtin: Optional[str] = None
    mpn: Optional[str] = None
    aliases: tuple[str, ...] = ()
    glyph: str = ""


@dataclass
class Listing:
    id: str
    retailer: str
    title: str
    price: float
    url: str = ""
    gtin: Optional[str] = None
    mpn: Optional[str] = None
    brand: Optional[str] = None
    condition: Condition = Condition.NEW
    shipping: Optional[float] = None    # None -> derive from retailer policy
    in_stock: bool = True
    seller: Optional[str] = None
    fetched_at: datetime = field(default_factory=utcnow)


@dataclass
class Coupon:
    retailer: str
    code: str
    type: CouponType
    value: float
    scope: Scope = Scope.SITEWIDE
    categories: tuple[str, ...] = ()
    excludes_brands: tuple[str, ...] = ()
    min_spend: float = 0.0
    max_discount: Optional[float] = None
    new_only: bool = False
    attempts: int = 0
    successes: int = 0
    last_worked: Optional[datetime] = None
    expires: Optional[datetime] = None
    source: str = "affiliate_feed"
    note: str = ""


@dataclass
class MatchResult:
    score: float
    tier: Tier
    reasons: list[str]


@dataclass
class CouponEval:
    coupon: Coupon
    applicable: bool
    why: str
    reliability: float
    discount: float
    expected: float   # discount * reliability


@dataclass
class Quote:
    listing: Listing
    product: Product
    match: MatchResult
    shipping: float            # store's shipping before any code
    ship_cost: float           # what is actually charged after a free-shipping code
    best_coupon: Optional[CouponEval]
    code_discount: float
    pay_today: float
    cashback: float
    net: float
    coupon_evals: list[CouponEval]
    verified: bool = False


@dataclass
class DealPost:
    id: str
    product_id: str
    retailer: str
    price: float
    votes: int
    posted: datetime
    note: str = ""
    depth: float = 0.0   # 1 - price/list
    listing_id: Optional[str] = None
    condition: str = "new"


@dataclass
class StoreEvent:
    retailer: str
    title: str
    ends: datetime
    code: Optional[str] = None


@dataclass
class ProbeStep:
    code: str
    ok: bool
    discount: float
    why: str = ""


@dataclass
class ProbeResult:
    listing_id: str
    steps: list[ProbeStep]
    winner: Optional[str]
    discount: float


# --- Local deals: weekly-ad offers at stores near a place ----------------------------------------------------------


@dataclass(frozen=True)
class Place:
    """A resolved location. Weekly ads are published per ZIP code, so a place always carries one."""
    query: str
    name: str
    lat: float
    lon: float
    postal_code: str
    source: str = "OpenStreetMap Nominatim"


@dataclass(frozen=True)
class Store:
    """One physical store location."""
    merchant: str
    name: str
    lat: float
    lon: float
    address: str
    distance_km: float
    url: str = ""                  # where the location comes from (an openstreetmap.org link)


class Presence(str, Enum):
    CONFIRMED = "confirmed"        # a store is mapped within the search radius
    FAR = "far"                    # the merchant is mapped, but no store within the radius
    UNMAPPED = "unmapped"          # no mapped store found (maps miss some regional chains)
    UNCHECKED = "unchecked"        # the store lookup itself failed


@dataclass
class StorePresence:
    merchant: str
    status: Presence
    nearest: Optional[Store] = None
    count: int = 0                 # stores within the radius


@dataclass(frozen=True)
class Flyer:
    id: int
    merchant: str
    merchant_id: int
    valid_from: datetime
    valid_to: datetime
    categories: tuple[str, ...] = ()
    postal_code: str = ""

    def active(self, now: datetime) -> bool:
        return self.valid_from <= now <= self.valid_to


@dataclass(frozen=True)
class DealTerms:
    """What an ad actually promises, normalised. `price` and `was` cover `quantity` items ("2 for $8": price 8, quantity 2)."""
    price: Optional[float] = None
    quantity: int = 1
    unit: str = ""                 # "lb", "each", "case"; "" when the ad doesn't say
    was: Optional[float] = None    # regular price for the same quantity, when stated or exactly derivable
    pct_off: Optional[float] = None       # effective saving: "buy 1 get 1 50% off" is 25%, not 50%
    dollars_off: Optional[float] = None   # for the same quantity
    hedge: str = ""                # "up to" / "starting at": the numbers are a ceiling or a floor, not a promise
    offer: str = ""                # the ad's own wording of the deal, when it has one
    conditions: tuple[str, ...] = ()      # what the price needs: "loyalty card", "coupon", "online price", "buy 6+"

    @property
    def unit_price(self) -> Optional[float]:
        return None if self.price is None else self.price / self.quantity


@dataclass
class LocalDeal:
    id: str                        # "<source>:<item id>"
    merchant: str
    title: str
    terms: DealTerms
    valid_from: datetime
    valid_to: datetime
    flyer_id: Optional[int] = None
    source: str = "flipp"
    source_url: str = ""           # public page showing the ad itself
    product_url: str = ""          # the retailer's own product page, when the ad links one
    image_url: str = ""
    brand: str = ""
    category: str = ""
    detailed: bool = False         # terms read from the full item record, not just the flyer index
    store: Optional[Store] = None  # nearest mapped store within the radius
    flags: list[str] = field(default_factory=list)
