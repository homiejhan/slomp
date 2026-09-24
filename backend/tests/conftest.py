from datetime import timedelta

import pytest

from plum.identifiers import make_gtin
from plum.models import Condition, Coupon, CouponType, Listing, Product, RetailerPolicy, Scope, utcnow

NOW = utcnow()


@pytest.fixture
def now():
    return NOW


@pytest.fixture
def products():
    return [
        Product("sony-xm5", "Sony", "Sony WH-1000XM5 Wireless Noise Canceling Headphones", "audio", 399.99, make_gtin("02724292350"), "WH1000XM5/B", ("xm5", "1000xm5")),
        Product("airpods-pro-2", "Apple", "Apple AirPods Pro (2nd generation) USB-C", "audio", 249.00, make_gtin("19500266931"), aliases=("airpods",)),
        Product("stanley-40", "Stanley", "Stanley Quencher H2.0 FlowState Tumbler 40 oz", "drinkware", 45.00, make_gtin("04138344010")),
        Product("instant-pot", "Instant Pot", "Instant Pot Duo 7-in-1 Electric Pressure Cooker 6 Quart", "kitchen", 99.99, make_gtin("81021301024")),
    ]


@pytest.fixture
def policies():
    return {
        "amazon": RetailerPolicy("amazon", "Amazon", 35, 5.99, 0.0, 0.95),
        "bestbuy": RetailerPolicy("bestbuy", "Best Buy", 35, 5.99, 0.02, 0.93),
        "walmart": RetailerPolicy("walmart", "Walmart", 35, 6.99, 0.01, 0.92),
        "ebay": RetailerPolicy("ebay", "eBay", 0, 0, 0.01, 0.80),
    }


@pytest.fixture
def listings(products):
    g = products[0].gtin
    return [
        Listing("amz-1", "amazon", "Sony WH-1000XM5 The Best Wireless Noise Canceling Headphones, Black", 328.00, gtin=g, brand="Sony"),
        Listing("bb-1", "bestbuy", "Sony - WH-1000XM5 Wireless Noise-Canceling Over-the-Ear Headphones - Black", 329.99, gtin=g),
        Listing("wm-1", "walmart", "Sony WH1000XM5 Wireless Industry Leading Noise Canceling Headphones, Black", 318.00),
        Listing("wm-2", "walmart", "Sony WH-1000XM4 Wireless Noise Cancelling Headphones, Black", 248.00, gtin=make_gtin("02724291988")),
        Listing("eb-1", "ebay", "Hard Travel Case for Sony WH-1000XM5 Headphones Storage Bag", 24.99),
        Listing("eb-2", "ebay", "Sony WH-1000XM5 Wireless Noise Canceling Headphones Black - Certified Refurbished", 279.95, gtin=g, condition=Condition.REFURBISHED),
        Listing("eb-3", "ebay", "Sony WH-1000XM5 Wireless Headphones, Black", 299.00, gtin="027242923509"),
    ]


@pytest.fixture
def coupons():
    return [
        Coupon("bestbuy", "SAVE15", CouponType.PERCENT, 15, Scope.CATEGORY, ("audio",), max_discount=60, attempts=812, successes=764, last_worked=NOW - timedelta(days=1), expires=NOW + timedelta(days=7), note="15% off audio"),
        Coupon("bestbuy", "BB20OFF", CouponType.FIXED, 20, min_spend=150, attempts=200, successes=40, last_worked=NOW - timedelta(days=35), expires=NOW + timedelta(days=2)),
        Coupon("bestbuy", "FREESHIP", CouponType.FREESHIP, 0, attempts=120, successes=118, last_worked=NOW),
        Coupon("walmart", "WMSAVE5", CouponType.FIXED, 5, min_spend=35, attempts=600, successes=480, last_worked=NOW - timedelta(days=1)),
        Coupon("amazon", "SONYXM5", CouponType.FIXED, 20, Scope.CATEGORY, ("audio",), attempts=210, successes=145, last_worked=NOW - timedelta(days=3)),
        Coupon("ebay", "OLD10", CouponType.PERCENT, 10, attempts=50, successes=49, last_worked=NOW - timedelta(days=1), expires=NOW - timedelta(days=1)),
    ]
