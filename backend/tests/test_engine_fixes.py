"""Regression tests for bugs found while refactoring the product engine."""
import asyncio

from plum import demo_data
from plum.adapters import FixtureAdapter, run_adapters
from plum.adapters.checkout_probe import parse_money
from plum.adapters.retailers import BestBuyAdapter
from plum.cache import TTLCache
from plum.demo_data import build_service
from plum.identifiers import make_gtin, short_gtin
from plum.matching import match
from plum.models import Listing, Product, Tier


async def test_one_failing_store_does_not_open_the_circuit_for_the_others(products):
    broken = FixtureAdapter("walmart", [], fail=True)
    for _ in range(3):
        await run_adapters([broken], products[0])
    healthy = FixtureAdapter("amazon", [Listing("a", "amazon", "Sony WH-1000XM5", 300.0)])
    (out,) = await run_adapters([healthy], products[0])
    assert out.status == "done" and broken.breaker.open and not healthy.breaker.open


async def test_first_search_claims_no_period_low():
    svc = build_service()
    rep = await svc.find("sony xm5")
    assert rep.offers and not any(rep.is_low(q) for q in rep.offers)
    for _ in range(3):                      # three more fetches at the same prices
        svc.cache.invalidate("sony-xm5")
        rep = await svc.find("sony xm5")
    assert all(rep.is_low(q) for q in rep.offers if q.listing.retailer != "bh")    # B&H lists two prices
    assert rep.history["amazon"] == [328.0, 328.0, 328.0]                          # earlier fetches only


async def test_repeat_searches_on_one_fetch_record_prices_once():
    svc = build_service()
    for _ in range(5):
        await svc.find("sony xm5")
    assert svc.history.series("sony-xm5", "amazon", svc.cache.get("sony-xm5").at) == []
    assert len(svc.history._d[("sony-xm5", "amazon")]) == 1


async def test_probing_does_not_mutate_module_level_demo_coupons():
    before = [(c.code, c.attempts, c.successes) for c in demo_data.COUPONS]
    svc = build_service()
    rep = await svc.find("sony xm5")
    await svc.test_codes(rep.best.listing, rep.product)
    assert [(c.code, c.attempts, c.successes) for c in demo_data.COUPONS] == before
    assert sum(c.attempts for c in svc.coupons) > sum(a for _, a, _ in before)


async def test_a_store_without_a_policy_is_skipped_not_fatal():
    svc = build_service()
    svc.adapters.append(FixtureAdapter("newegg", [Listing("n1", "newegg", "Sony WH-1000XM5 Wireless Noise Canceling Headphones", 299.0)]))
    rep = await svc.find("sony xm5")
    assert any(s.listing.id == "n1" and "unknown store" in s.why for s in rep.skipped)
    assert all(q.listing.retailer != "newegg" for q in rep.offers)


def test_features_are_keyed_by_title_not_product_id():
    sony = Product("p1", "Sony", "Sony WH-1000XM5 Headphones", "audio", 399)
    airpods = Product("p1", "Apple", "Apple AirPods Pro 2", "audio", 249)      # same id, different product
    listing = Listing("x", "amazon", "Apple AirPods Pro 2", 189)
    match(sony, listing)
    assert match(airpods, listing).tier == Tier.CONFIDENT


def test_gtins_go_out_at_their_printed_length():
    upc = make_gtin("02724292350")
    assert short_gtin(upc) == upc and len(upc) == 12                   # not the 11-digit 27242923508
    assert short_gtin("4006381333931") == "4006381333931"                # EAN-13
    assert short_gtin("036000291453") is None                            # bad check digit
    assert BestBuyAdapter.query(Product("x", "Sony", "Sony WH-1000XM5 (Black)", "audio", 1, gtin=upc)) == f"(upc={upc})"
    assert BestBuyAdapter.query(Product("x", "Sony", "Sony WH-1000XM5 (Black)", "audio", 1)) == \
        "(search=sony&search=wh-1000xm5&search=black)"


async def test_ttl_cache_single_flight_caches_none_and_honours_zero_ttl():
    cache: TTLCache = TTLCache(ttl_s=60)
    calls = []

    async def fetch():
        calls.append(1)
        await asyncio.sleep(0.01)
        return None

    assert await asyncio.gather(*(cache.get_or_fetch("k", fetch) for _ in range(5))) == [None] * 5
    assert await cache.get_or_fetch("k", fetch) is None and len(calls) == 1 and not cache._locks
    cache.set("z", 1, ttl_s=0)
    assert cache.get("z") is None


def test_cart_totals_parse_the_dollar_amount():
    assert parse_money("Total: $1,234.56 (2 items)") == 1234.56
    assert parse_money("Order total 49.99") == 49.99 and parse_money("") == 0.0
