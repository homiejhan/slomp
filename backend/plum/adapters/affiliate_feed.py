"""Normalise coupon rows from affiliate networks / aggregators (FMTC, CJ, Impact, Rakuten Advertising style).

Feeds disagree on field names and date formats; this maps the common shapes onto Coupon and pools duplicates.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from ..coupons import dedupe
from ..models import Coupon, CouponType, Scope

_DATE_FMTS = ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ", "%m/%d/%Y", "%Y-%m-%d %H:%M:%S")


def parse_date(v: Any) -> Optional[datetime]:
    if not v:
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    s = str(v).strip()
    for fmt in _DATE_FMTS:
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _first(row: dict, *keys: str, default: Any = None) -> Any:
    for k in keys:
        if k in row and row[k] not in (None, ""):
            return row[k]
    return default


def _type_and_value(row: dict) -> tuple[CouponType, float]:
    kind = str(_first(row, "type", "discount_type", "offer_type", default="")).lower()
    raw = str(_first(row, "value", "discount", "amount", default="0")).replace("$", "").replace("%", "").strip()
    try:
        val = float(raw)
    except ValueError:
        val = 0.0
    if "ship" in kind or "ship" in str(_first(row, "title", "name", "description", default="")).lower() and val == 0:
        return CouponType.FREESHIP, 0.0
    if "%" in str(_first(row, "value", "discount", default="")) or kind in ("percent", "percentage", "pct"):
        return CouponType.PERCENT, val
    return CouponType.FIXED, val


def parse_feed_row(row: dict) -> Optional[Coupon]:
    code = _first(row, "code", "coupon_code", "promo_code")
    retailer = _first(row, "retailer", "merchant", "merchant_slug", "advertiser")
    if not code or not retailer:
        return None
    t, v = _type_and_value(row)
    cats = _first(row, "categories", "category", default=())
    if isinstance(cats, str):
        cats = tuple(c.strip().lower() for c in cats.split(",") if c.strip())
    scope = Scope.CATEGORY if cats else Scope.SITEWIDE
    excl = _first(row, "excludes_brands", "exclusions", default=())
    if isinstance(excl, str):
        excl = tuple(e.strip() for e in excl.split(",") if e.strip())
    return Coupon(
        retailer=str(retailer).lower(), code=str(code).strip().upper(), type=t, value=v, scope=scope,
        categories=tuple(cats), excludes_brands=tuple(excl),
        min_spend=float(_first(row, "min_spend", "minimum", "min_order", default=0) or 0),
        max_discount=(lambda x: float(x) if x not in (None, "") else None)(_first(row, "max_discount", "max")),
        attempts=int(_first(row, "attempts", "tests", default=0) or 0),
        successes=int(_first(row, "successes", "passes", default=0) or 0),
        last_worked=parse_date(_first(row, "last_worked", "last_verified", "verified_at")),
        expires=parse_date(_first(row, "expires", "end_date", "expiration")),
        source=str(_first(row, "source", "network", default="affiliate_feed")),
        note=str(_first(row, "title", "name", "description", default="")),
    )


def parse_feed_rows(rows: Iterable[dict]) -> list[Coupon]:
    out = [c for c in (parse_feed_row(r) for r in rows) if c]
    return dedupe(out)
