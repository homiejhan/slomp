"""The demo data must tell one story: every community deal points at a listing the adapters can return."""
from plum.demo_data import DEALS, EVENTS, COUPONS, RAW, PRODUCTS


def test_every_deal_has_a_listing():
    for d in DEALS:
        assert d.listing_id, f"{d.id} has no listing"
        l = next(l for _, l in RAW if l.id == d.listing_id)
        assert l.retailer == d.retailer and l.price == d.price and l.condition.value == d.condition


def test_every_event_code_exists():
    codes = {(c.retailer, c.code) for c in COUPONS}
    for e in EVENTS:
        if e.code:
            assert (e.retailer, e.code) in codes, e


def test_every_product_has_a_new_listing_somewhere():
    for p in PRODUCTS:
        assert any(q == p.id and l.condition.value == "new" for q, l in RAW), p.id
