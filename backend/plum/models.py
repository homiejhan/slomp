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
