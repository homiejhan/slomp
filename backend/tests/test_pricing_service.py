import asyncio

import pytest

from plum.adapters import FixtureAdapter, SimulatedProbe, parse_feed_rows, run_adapters
from plum.matching import match
from plum.pricing import quote
from plum.ranking import deal_heat, is_period_low, rank_deals
from plum.models import DealPost, utcnow
from plum.service import DealService
from datetime import timedelta


def test_quote_receipt(products, listings, policies, coupons, now):
    sony, bb = products[0], listings[1]
    q = quote(bb, sony, match(sony, bb), policies["bestbuy"], coupons, now=now)
    assert q.best_coupon.coupon.code == "SAVE15"
    assert q.code_discount == 49.5 and q.shipping == 0
    assert q.pay_today == 280.49 and q.cashback == 5.61 and q.net == 274.88


def test_verified_code_overrides_prediction(products, listings, policies, coupons, now):
    sony, bb = products[0], listings[1]
    q = quote(bb, sony, match(sony, bb), policies["bestbuy"], coupons, verified=True, verified_code=None, now=now)
    assert q.verified and q.best_coupon is None and q.pay_today == 329.99


async def test_fan_out_tolerates_slow_and_broken_stores(products, listings):
    adapters = [FixtureAdapter("amazon", listings), FixtureAdapter("bestbuy", listings, delay_s=0.5), FixtureAdapter("walmart", listings, fail=True)]
    out = await run_adapters(adapters, products[0], budget_s=0.15)
    st = {o.retailer: o.status for o in out}
    assert st == {"amazon": "done", "bestbuy": "timeout", "walmart": "error"}


async def test_service_end_to_end(products, listings, policies, coupons):
    adapters = [FixtureAdapter(r, listings) for r in policies]
    svc = DealService(products, policies, adapters, coupons, probe=SimulatedProbe(), budget_s=1.0)
    rep = await svc.find("sony xm5")
    assert rep.product.id == "sony-xm5"
    assert [q.listing.retailer for q in rep.offers][0] == "bestbuy"
    assert {s.listing.id for s in rep.skipped} == {"wm-2", "eb-1", "eb-2"}
    rep2 = await svc.find("sony xm5", include_used=True)
    assert any(q.listing.id == "eb-2" for q in rep2.offers)
    res = await svc.test_codes(rep.best.listing, rep.product)
    assert res.winner in ("SAVE15", "FREESHIP", None)
    rep3 = await svc.find("sony xm5")
    assert rep3.best.verified


def test_feed_parsing_and_dedupe():
    rows = [
        {"merchant": "BestBuy", "coupon_code": "save15", "discount": "15%", "categories": "Audio", "end_date": "2030-01-01", "tests": 10, "passes": 9},
        {"advertiser": "bestbuy", "code": "SAVE15", "type": "percent", "value": 15, "expiration": "2030-02-01", "attempts": 5, "successes": 5, "title": "15% off audio"},
        {"merchant": "target", "code": "SHIPFREE", "type": "free shipping", "value": 0},
        {"merchant": "target"},
    ]
    cs = parse_feed_rows(rows)
    assert len(cs) == 2
    bb = next(c for c in cs if c.retailer == "bestbuy")
    assert bb.attempts == 15 and bb.successes == 14 and bb.categories == ("audio",) and bb.expires.year == 2030 and bb.expires.month == 2
    assert next(c for c in cs if c.code == "SHIPFREE").type.value == "freeship"


def test_deal_heat_and_lows():
    now = utcnow()
    fresh = DealPost("a", "p", "r", 39.99, 100, now - timedelta(hours=2), depth=0.2)
    stale = DealPost("b", "p", "r", 39.99, 300, now - timedelta(hours=48), depth=0.2)
    assert deal_heat(fresh, now) > deal_heat(stale, now)
    assert rank_deals([stale, fresh], now)[0].id == "a"
    assert is_period_low(100, [120, 101, 130]) and not is_period_low(110, [100, 120])
