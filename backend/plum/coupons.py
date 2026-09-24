"""Coupon reliability, applicability and ranking.

Reliability = Wilson lower bound of the success rate (so 3/3 is not treated like 300/300),
scaled by how recently the code last worked. Expired codes are 0.
"""
from __future__ import annotations

import math
from dataclasses import replace
from datetime import datetime
from typing import Iterable, Optional

from .models import Coupon, CouponEval, CouponType, Listing, Product, Scope, utcnow
from .textfeatures import compact, norm

RECENCY_HALF_LIFE_DAYS = 14.0
MIN_RELIABILITY_TO_COUNT = 0.5


def wilson_lower(successes: int, attempts: int, z: float = 1.96) -> float:
    if attempts <= 0:
        return 0.0
    p = successes / attempts
    z2 = z * z
    centre = p + z2 / (2 * attempts)
    spread = z * math.sqrt((p * (1 - p) + z2 / (4 * attempts)) / attempts)
    return max(0.0, (centre - spread) / (1 + z2 / attempts))


def reliability(c: Coupon, now: Optional[datetime] = None) -> float:
    now = now or utcnow()
    if c.expires and c.expires < now:
        return 0.0
    age_days = max(0.0, (now - c.last_worked).total_seconds() / 86400) if c.last_worked else 60.0
    recency = 0.5 ** (age_days / RECENCY_HALF_LIFE_DAYS)
    return wilson_lower(c.successes, c.attempts) * (0.55 + 0.45 * recency)


def applies(c: Coupon, listing: Listing, product: Product, now: Optional[datetime] = None) -> tuple[bool, str]:
    now = now or utcnow()
    if c.retailer != listing.retailer:
        return False, "other store"
    if c.expires and c.expires < now:
        return False, "expired"
    if c.scope == Scope.CATEGORY and product.category not in c.categories:
        return False, f"only for {', '.join(c.categories)}"
    if c.scope == Scope.PRODUCT and product.id not in c.categories:
        return False, "different product"
    if any(compact(norm(b)) == compact(norm(product.brand)) for b in c.excludes_brands):
        return False, f"excludes {product.brand}"
    if c.min_spend and listing.price < c.min_spend:
        return False, f"needs a ${c.min_spend:g}+ cart"
    if c.new_only and listing.condition.value != "new":
        return False, "new items only"
    return True, ""


def discount_of(c: Coupon, price: float, shipping: float) -> float:
    if c.type == CouponType.PERCENT:
        d = price * c.value / 100
        return min(d, c.max_discount) if c.max_discount is not None else d
    if c.type == CouponType.FIXED:
        return min(c.value, price)
    if c.type == CouponType.FREESHIP:
        return shipping
    return 0.0


def evaluate(c: Coupon, listing: Listing, product: Product, shipping: float, now: Optional[datetime] = None) -> CouponEval:
    ok, why = applies(c, listing, product, now)
    rel = reliability(c, now)
    disc = discount_of(c, listing.price, shipping) if ok else 0.0
    return CouponEval(c, ok, why, rel, round(disc, 2), round(disc * rel, 2))


def rank(coupons: Iterable[Coupon], listing: Listing, product: Product, shipping: float, now: Optional[datetime] = None) -> list[CouponEval]:
    evals = [evaluate(c, listing, product, shipping, now) for c in coupons if c.retailer == listing.retailer]
    evals.sort(key=lambda e: (not e.applicable, -e.expected))
    return evals


def best_counted(evals: list[CouponEval]) -> Optional[CouponEval]:
    """The code the price is allowed to assume: applicable, saves something, and reliable enough."""
    return next((e for e in evals if e.applicable and e.discount > 0 and e.reliability >= MIN_RELIABILITY_TO_COUNT), None)


def record_outcome(c: Coupon, worked: bool, when: Optional[datetime] = None) -> Coupon:
    """Feed a checkout result back into the stats (crowd + probe signals share one ledger)."""
    c.attempts += 1
    if worked:
        c.successes += 1
        c.last_worked = when or utcnow()
    return c


def dedupe(coupons: Iterable[Coupon]) -> list[Coupon]:
    """Same retailer+code from several feeds -> one record with pooled stats and the latest expiry.

    Returns copies: callers' coupons (e.g. module-level demo data) are never modified, here or by later probes."""
    merged: dict[tuple[str, str], Coupon] = {}
    for c in coupons:
        k = (c.retailer, c.code.upper())
        if k not in merged:
            merged[k] = replace(c)
            continue
        m = merged[k]
        m.attempts += c.attempts
        m.successes += c.successes
        if c.last_worked and (not m.last_worked or c.last_worked > m.last_worked):
            m.last_worked = c.last_worked
        if c.expires and (not m.expires or c.expires > m.expires):
            m.expires = c.expires
        if not m.note and c.note:
            m.note = c.note
    return list(merged.values())
