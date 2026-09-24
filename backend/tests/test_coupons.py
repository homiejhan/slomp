from datetime import timedelta

import pytest

from plum.coupons import applies, best_counted, dedupe, discount_of, rank, record_outcome, reliability, wilson_lower
from plum.models import Coupon, CouponType, Listing


def test_wilson_penalises_small_samples():
    assert wilson_lower(3, 3) < wilson_lower(300, 300)
    assert abs(wilson_lower(764, 812) - 0.922) < 0.005
    assert wilson_lower(0, 0) == 0


def test_reliability_recency_and_expiry(coupons, now):
    by = {c.code: c for c in coupons}
    assert reliability(by["SAVE15"], now) > 0.85
    assert reliability(by["BB20OFF"], now) < 0.15
    assert reliability(by["OLD10"], now) == 0.0


def test_applicability(coupons, products, listings, now):
    sony, bb = products[0], listings[1]
    by = {c.code: c for c in coupons}
    assert applies(by["SAVE15"], bb, sony, now) == (True, "")
    assert applies(by["WMSAVE5"], bb, sony, now)[1] == "other store"
    cheap = Listing("z", "bestbuy", "x", 100)
    assert "cart" in applies(by["BB20OFF"], cheap, sony, now)[1]


def test_discount_caps():
    c = Coupon("bestbuy", "P", CouponType.PERCENT, 15, max_discount=60)
    assert discount_of(c, 329.99, 0) == pytest.approx(49.4985)
    assert discount_of(c, 1000, 0) == 60
    assert discount_of(Coupon("x", "F", CouponType.FIXED, 20), 10, 0) == 10
    assert discount_of(Coupon("x", "S", CouponType.FREESHIP, 0), 10, 5.99) == 5.99


def test_rank_and_best_counted(coupons, products, listings, now):
    evals = rank(coupons, listings[1], products[0], 0.0, now)
    assert evals[0].coupon.code == "SAVE15"
    best = best_counted(evals)
    assert best and best.coupon.code == "SAVE15" and round(best.discount, 2) == 49.5


def test_record_and_dedupe(now):
    a = Coupon("bb", "SAVE15", CouponType.PERCENT, 15, attempts=10, successes=9, expires=now)
    b = Coupon("bb", "save15", CouponType.PERCENT, 15, attempts=5, successes=1, expires=now + timedelta(days=3), note="feed B")
    merged = dedupe([a, b])
    assert len(merged) == 1 and merged[0].attempts == 15 and merged[0].successes == 10 and merged[0].note == "feed B"
    record_outcome(merged[0], True)
    assert merged[0].attempts == 16 and merged[0].successes == 11 and merged[0].last_worked is not None
