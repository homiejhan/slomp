"""Landed cost: sticker - code - (free shipping) + shipping - cash back."""
from __future__ import annotations

from datetime import datetime
from typing import Iterable, Optional

from . import coupons as C
from .models import CouponType, Listing, MatchResult, Product, Quote, RetailerPolicy


def shipping_cost(policy: RetailerPolicy, listing: Listing) -> float:
    if listing.shipping is not None:
        return listing.shipping
    return 0.0 if listing.price >= policy.free_shipping_over else policy.flat_shipping


def quote(listing: Listing, product: Product, match: MatchResult, policy: RetailerPolicy,
          coupons: Iterable[C.Coupon], verified: bool = False, verified_code: Optional[str] = None,
          now: Optional[datetime] = None) -> Quote:
    """verified=True means a probe ran on this cart: use exactly what worked (verified_code, or nothing)."""
    ship = shipping_cost(policy, listing)
    evals = C.rank(coupons, listing, product, ship, now)
    if verified:
        best = next((e for e in evals if e.coupon.code == verified_code and e.applicable), None) if verified_code else None
    else:
        best = C.best_counted(evals)
    is_ship = best is not None and best.coupon.type == CouponType.FREESHIP
    code_disc = 0.0 if (best is None or is_ship) else best.discount
    ship_cost = 0.0 if is_ship else ship
    subtotal = listing.price - code_disc
    pay_today = round(subtotal + ship_cost, 2)
    cashback = round(subtotal * policy.cashback_rate, 2)
    return Quote(listing, product, match, ship, ship_cost, best, code_disc, pay_today, cashback, round(pay_today - cashback, 2), evals, verified)
