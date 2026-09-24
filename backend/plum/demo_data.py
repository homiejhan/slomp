"""Same catalog, listings and codes the frontend uses, so both halves tell the same story."""
from __future__ import annotations

from datetime import timedelta

from .identifiers import make_gtin
from .models import Condition, Coupon, CouponType, DealPost, Listing, Product, RetailerPolicy, Scope, StoreEvent, utcnow

NOW = utcnow()
d = lambda n: NOW + timedelta(days=n)  # noqa: E731

POLICIES = {
    "amazon": RetailerPolicy("amazon", "Amazon", 35, 5.99, 0.00, 0.95),
    "walmart": RetailerPolicy("walmart", "Walmart", 35, 6.99, 0.01, 0.92),
    "bestbuy": RetailerPolicy("bestbuy", "Best Buy", 35, 5.99, 0.02, 0.93),
    "target": RetailerPolicy("target", "Target", 35, 5.99, 0.01, 0.92),
    "ebay": RetailerPolicy("ebay", "eBay", 0, 0, 0.01, 0.80),
    "bh": RetailerPolicy("bh", "B&H Photo", 49, 7.49, 0.02, 0.90),
    "dyson": RetailerPolicy("dyson", "Dyson.com", 0, 0, 0.05, 0.95),
    "nike": RetailerPolicy("nike", "Nike.com", 50, 8, 0.04, 0.95),
    "lego": RetailerPolicy("lego", "LEGO.com", 35, 5.99, 0.03, 0.95),
    "zappos": RetailerPolicy("zappos", "Zappos", 0, 0, 0.03, 0.93),
}

PRODUCTS = [
    Product("sony-xm5", "Sony", "Sony WH-1000XM5 Wireless Noise Canceling Headphones", "audio", 399.99, make_gtin("02724292350"), "WH1000XM5/B", ("xm5", "1000xm5", "sony headphones"), glyph="🎧"),
    Product("airpods-pro-2", "Apple", "Apple AirPods Pro (2nd generation) USB-C", "audio", 249.00, make_gtin("19500266931"), "MTJV3AM/A", ("airpods pro 2", "airpods"), glyph="🎵"),
    Product("dyson-v15", "Dyson", "Dyson V15 Detect Cordless Vacuum", "home", 749.99, make_gtin("88554702116"), "447922-01", ("v15", "dyson vacuum"), glyph="🧹"),
    Product("switch-2", "Nintendo", "Nintendo Switch 2 Console", "gaming", 449.99, make_gtin("04549680900"), "HEG-001", ("switch 2", "nintendo"), glyph="🎮"),
    Product("instant-pot", "Instant Pot", "Instant Pot Duo 7-in-1 Electric Pressure Cooker 6 Quart", "kitchen", 99.99, make_gtin("81021301024"), "IP-DUO60", ("instapot", "pressure cooker"), glyph="🍲"),
    Product("pegasus-41", "Nike", "Nike Pegasus 41 Men's Road Running Shoes", "shoes", 140.00, make_gtin("19696771108"), "FD2722-001", ("pegasus", "nike running shoes"), glyph="👟"),
    Product("lego-bonsai", "LEGO", "LEGO Icons Bonsai Tree 10281 Building Set", "toys", 49.99, make_gtin("67341917140"), "10281", ("lego bonsai", "bonsai"), glyph="🌳"),
    Product("kindle-pw", "Amazon", "Kindle Paperwhite 16 GB 2024", "reading", 159.99, make_gtin("84026859771"), "B0CFPJYX7P", ("kindle", "paperwhite"), glyph="📖"),
    Product("stanley-40", "Stanley", "Stanley Quencher H2.0 FlowState Tumbler 40 oz", "drinkware", 45.00, make_gtin("04138344010"), "10-09131", ("stanley cup", "quencher"), glyph="🥤"),
    Product("ninja-creami", "Ninja", "Ninja CREAMi Ice Cream Maker NC301", "kitchen", 229.99, make_gtin("62235631008"), "NC301", ("creami", "ninja ice cream"), glyph="🍦"),
]
_G = {p.id: p.gtin for p in PRODUCTS}
_n = [0]


def L(q, r, price, title, gtin=None, cond=Condition.NEW, brand=None):
    _n[0] += 1
    return (q, Listing(f"{r}-{_n[0]}", r, title, price, url=f"https://{r}.example/{_n[0]}", gtin=gtin, brand=brand, condition=cond))


RAW = [
    L("sony-xm5", "amazon", 328.00, "Sony WH-1000XM5 The Best Wireless Noise Canceling Headphones with Auto Noise Canceling Optimizer, Black", _G["sony-xm5"], brand="Sony"),
    L("sony-xm5", "bestbuy", 329.99, "Sony - WH-1000XM5 Wireless Noise-Canceling Over-the-Ear Headphones - Black", _G["sony-xm5"]),
    L("sony-xm5", "walmart", 318.00, "Sony WH1000XM5 Wireless Industry Leading Noise Canceling Headphones, Black"),
    L("sony-xm5", "target", 349.99, "Sony WH-1000XM5 Bluetooth Wireless Noise-Canceling Headphones - Black", _G["sony-xm5"]),
    L("sony-xm5", "ebay", 279.95, "Sony WH-1000XM5 Wireless Noise Canceling Headphones Black - Certified Refurbished", _G["sony-xm5"], Condition.REFURBISHED),
    L("sony-xm5", "ebay", 24.99, "Hard Travel Case for Sony WH-1000XM5 Headphones Storage Bag"),
    L("sony-xm5", "walmart", 248.00, "Sony WH-1000XM4 Wireless Noise Cancelling Headphones, Black", make_gtin("02724291988")),
    L("sony-xm5", "bh", 328.00, "Sony WH-1000XM5 Noise-Canceling Wireless Over-Ear Headphones (Black)", _G["sony-xm5"]),
    L("airpods-pro-2", "amazon", 189.00, "Apple AirPods Pro 2 Wireless Earbuds, Active Noise Cancellation, USB-C Charging", _G["airpods-pro-2"], brand="Apple"),
    L("airpods-pro-2", "bestbuy", 189.99, "Apple - AirPods Pro 2 (2nd generation) with MagSafe Case (USB-C) - White", _G["airpods-pro-2"]),
    L("airpods-pro-2", "walmart", 189.00, "Apple AirPods Pro 2nd Generation USB-C"),
    L("airpods-pro-2", "ebay", 149.99, "Apple AirPods Pro 2nd Gen USB-C - Open Box, Excellent", _G["airpods-pro-2"], Condition.OPEN_BOX),
    L("airpods-pro-2", "amazon", 22.99, "Silicone Case for AirPods Pro 2nd Generation, Shockproof Cover with Keychain"),
    L("dyson-v15", "dyson", 549.99, "Dyson V15 Detect Cordless Vacuum (Yellow/Nickel)", _G["dyson-v15"], brand="Dyson"),
    L("dyson-v15", "amazon", 569.99, "Dyson V15 Detect Cordless Vacuum Cleaner, Yellow/Nickel", _G["dyson-v15"]),
    L("dyson-v15", "walmart", 599.00, "Dyson V15 Detect Cordless Vacuum Cleaner, Yellow Nickel"),
    L("dyson-v15", "amazon", 429.99, "Dyson V11 Extra Cordless Vacuum Cleaner, Blue", make_gtin("88554700301")),
    L("switch-2", "amazon", 449.99, "Nintendo Switch 2 Console", _G["switch-2"], brand="Nintendo"),
    L("switch-2", "walmart", 449.00, "Nintendo Switch 2 System"),
    L("switch-2", "target", 499.99, "Nintendo Switch 2 + Mario Kart World Bundle", make_gtin("04549680901")),
    L("instant-pot", "amazon", 79.95, "Instant Pot Duo 7-in-1 Electric Pressure Cooker, Slow Cooker, Rice Cooker, Steamer, 6 Quart", _G["instant-pot"]),
    L("instant-pot", "walmart", 69.00, "Instant Pot Duo 7-in-1 Electric Pressure Cooker, Slow Cooker, Rice Cooker, 6 Quart"),
    L("instant-pot", "amazon", 129.95, "Instant Pot Duo Plus 9-in-1 Electric Pressure Cooker, 6 Quart", make_gtin("81021301033")),
    L("pegasus-41", "nike", 140.00, "Nike Pegasus 41 Men's Road Running Shoes", _G["pegasus-41"], brand="Nike"),
    L("pegasus-41", "zappos", 140.00, "Nike Pegasus 41 (Black/White) Men's Running Shoes", _G["pegasus-41"]),
    L("pegasus-41", "walmart", 109.99, "Nike Air Zoom Pegasus 41 Mens Road Running Shoes Black"),
    L("pegasus-41", "nike", 104.97, "Nike Pegasus 40 Men's Road Running Shoes", make_gtin("19696759906")),
    L("lego-bonsai", "lego", 49.99, "LEGO Icons Bonsai Tree 10281", _G["lego-bonsai"], brand="LEGO"),
    L("lego-bonsai", "target", 39.99, "LEGO Icons Bonsai Tree Building Kit 10281", _G["lego-bonsai"]),
    L("lego-bonsai", "amazon", 59.99, "LEGO Icons Flower Bouquet 10280 Building Set", make_gtin("67341917139")),
    L("kindle-pw", "amazon", 129.99, "Amazon Kindle Paperwhite (16 GB) – Our fastest Kindle ever, 2024 release", _G["kindle-pw"], brand="Amazon"),
    L("kindle-pw", "bestbuy", 159.99, "Amazon - Kindle Paperwhite (2024) 16GB E-Reader - Black", _G["kindle-pw"]),
    L("kindle-pw", "amazon", 34.99, "Kindle Paperwhite Fabric Cover (2024 release)"),
    L("stanley-40", "amazon", 35.00, "Stanley Quencher H2.0 FlowState Stainless Steel Vacuum Insulated Tumbler 40oz", _G["stanley-40"], brand="Stanley"),
    L("stanley-40", "walmart", 45.00, "Stanley Quencher H2.0 FlowState Tumbler 40 oz, Charcoal"),
    L("stanley-40", "walmart", 35.00, "Stanley Quencher H2.0 FlowState Tumbler 30 oz, Fog"),
    L("ninja-creami", "amazon", 179.99, "Ninja NC301 CREAMi Ice Cream Maker, 7 One-Touch Programs", _G["ninja-creami"], brand="Ninja"),
    L("ninja-creami", "walmart", 169.00, "Ninja CREAMi Ice Cream Maker, 7 One-Touch Programs, NC301"),
    L("ninja-creami", "amazon", 229.99, "Ninja CREAMi Deluxe 11-in-1 Ice Cream Maker NC501", make_gtin("62235631077")),
    L("sony-xm5", "bh", 299.00, "Sony WH-1000XM5 Wireless Headphones, Black", "027242923509"),
    L("airpods-pro-2", "target", 189.99, "Apple AirPods Pro (2nd generation) USB-C - White", _G["airpods-pro-2"]),
    L("airpods-pro-2", "walmart", 129.00, "Apple AirPods 4 with Active Noise Cancellation", "195002776111"),
    L("dyson-v15", "bestbuy", 569.99, "Dyson - V15 Detect Cordless Vacuum with 8 accessories - Yellow/Nickel", _G["dyson-v15"]),
    L("dyson-v15", "target", 649.99, "Dyson V15 Detect Cordless Stick Vacuum", _G["dyson-v15"]),
    L("switch-2", "bestbuy", 449.99, "Nintendo - Switch 2 Console", _G["switch-2"]),
    L("switch-2", "target", 449.99, "Nintendo Switch 2 Console", _G["switch-2"]),
    L("switch-2", "ebay", 419.99, "Nintendo Switch 2 Console - Used, Excellent Condition", _G["switch-2"], cond=Condition.USED),
    L("switch-2", "walmart", 299.99, "Nintendo Switch OLED Model White", "045496807009"),
    L("instant-pot", "target", 89.99, "Instant Pot Duo 7-in-1 6qt Pressure Cooker", _G["instant-pot"]),
    L("instant-pot", "bestbuy", 89.99, "Instant Pot - Duo 6-Quart 7-in-1 Electric Pressure Cooker - Stainless", _G["instant-pot"]),
    L("pegasus-41", "amazon", 119.97, "Nike Men's Pegasus 41 Running Shoe", _G["pegasus-41"]),
    L("pegasus-41", "ebay", 89.99, "Nike Air Zoom Pegasus 41 Mens Running Shoes Size 10 - New with box", _G["pegasus-41"]),
    L("lego-bonsai", "amazon", 39.99, "LEGO Icons Bonsai Tree 10281 Building Set for Adults", _G["lego-bonsai"]),
    L("lego-bonsai", "walmart", 44.99, "LEGO Icons Bonsai Tree Building Set 10281", None),
    L("kindle-pw", "target", 159.99, "Amazon Kindle Paperwhite 16GB 2024", _G["kindle-pw"]),
    L("stanley-40", "target", 45.00, "Stanley 40 oz Quencher H2.0 FlowState Tumbler", _G["stanley-40"]),
    L("stanley-40", "ebay", 29.99, "Stanley Quencher H2.0 FlowState 40oz Tumbler Rose Quartz - New", "041383440113"),
    L("ninja-creami", "bestbuy", 199.99, "Ninja - CREAMi Ice Cream Maker - Silver NC301", _G["ninja-creami"]),
    L("ninja-creami", "target", 199.99, "Ninja CREAMi Ice Cream Maker NC301", _G["ninja-creami"]),
]


def listings_for(product_id: str) -> list[Listing]:
    return [l for q, l in RAW if q == product_id]


def C(r, code, t, v, **kw):
    base = dict(scope=Scope.SITEWIDE, attempts=100, successes=90, last_worked=d(-1), expires=d(30), source="affiliate_feed")
    base.update(kw)
    return Coupon(r, code, t, v, **base)


COUPONS = [
    C("bestbuy", "SAVE15", CouponType.PERCENT, 15, scope=Scope.CATEGORY, categories=("audio",), max_discount=60, attempts=812, successes=764, expires=d(7), note="15% off headphones and speakers"),
    C("bestbuy", "LABORDAY10", CouponType.PERCENT, 10, excludes_brands=("Apple", "Nintendo"), attempts=340, successes=301, last_worked=d(-0.2), expires=d(6), note="10% off, brand exclusions", source="store"),
    C("bestbuy", "FREESHIP", CouponType.FREESHIP, 0, attempts=120, successes=118, note="Free shipping on any order"),
    C("bestbuy", "BB20OFF", CouponType.FIXED, 20, min_spend=150, attempts=200, successes=40, last_worked=d(-35), expires=d(2), note="$20 off $150", source="community"),
    C("target", "CIRCLE5", CouponType.PERCENT, 5, excludes_brands=("Apple", "Nintendo"), attempts=1200, successes=1150, note="5% off with Circle", source="store"),
    C("target", "LDHOME20", CouponType.PERCENT, 20, scope=Scope.CATEGORY, categories=("home", "kitchen", "drinkware"), attempts=410, successes=377, expires=d(6), note="20% off home & kitchen"),
    C("walmart", "WMSAVE5", CouponType.FIXED, 5, min_spend=35, attempts=600, successes=480, note="$5 off $35"),
    C("walmart", "TRIPLE10", CouponType.PERCENT, 10, scope=Scope.CATEGORY, categories=("kitchen", "home"), max_discount=25, attempts=150, successes=121, note="10% off kitchen, up to $25"),
    C("amazon", "SONYXM5", CouponType.FIXED, 20, scope=Scope.CATEGORY, categories=("audio",), attempts=210, successes=145, last_worked=d(-3), note="$20 clip coupon on Sony audio"),
    C("ebay", "LABORDAY15", CouponType.PERCENT, 15, min_spend=25, max_discount=50, attempts=2100, successes=1890, last_worked=d(-0.1), expires=d(6), note="15% off sitewide, max $50", source="store"),
    C("dyson", "DYSON50", CouponType.FIXED, 50, min_spend=300, attempts=80, successes=74, note="$50 off $300"),
    C("nike", "LABOR25", CouponType.PERCENT, 25, scope=Scope.CATEGORY, categories=("shoes",), max_discount=100, attempts=980, successes=905, last_worked=d(-0.3), expires=d(7), note="25% off select shoes", source="store"),
    C("zappos", "ZAPPOS10", CouponType.PERCENT, 10, attempts=330, successes=280, note="10% off first order"),
    C("lego", "VIP5", CouponType.PERCENT, 5, attempts=200, successes=188, note="5% off with Insiders"),
    C("bh", "BHAUDIO25", CouponType.FIXED, 25, scope=Scope.CATEGORY, categories=("audio",), min_spend=300, attempts=60, successes=52, note="$25 off audio over $300"),
]


EVENTS = [
    StoreEvent("target", "Labor Day: up to 40% off home & kitchen", d(6), "LDHOME20"),
    StoreEvent("bestbuy", "Labor Day sale on TVs, laptops and audio", d(6), "LABORDAY10"),
    StoreEvent("nike", "25% off select shoes", d(7), "LABOR25"),
    StoreEvent("ebay", "15% off sitewide, up to $50", d(6), "LABORDAY15"),
    StoreEvent("dyson", "$200 off V15 Detect, no code needed", d(8)),
    StoreEvent("amazon", "Labor Day deals on Kindle and Echo devices", d(5)),
    StoreEvent("walmart", "Rollbacks across kitchen and back-to-school", d(12)),
    StoreEvent("zappos", "Free expedited shipping through the weekend", d(4)),
]

_LIST = {p.id: p.list_price for p in PRODUCTS}


def _deal(pid, r, price, votes, hours_ago, note):
    l = next((x for q, x in RAW if q == pid and x.retailer == r and x.price == price), None)
    return DealPost(f"{pid}-{r}", pid, r, price, votes, NOW - timedelta(hours=hours_ago), note, round(1 - price / _LIST[pid], 3),
                    l.id if l else None, l.condition.value if l else "new")


DEALS = [
    _deal("kindle-pw", "amazon", 129.99, 610, 6, "Labor Day price, all colors"),
    _deal("sony-xm5", "walmart", 318.00, 522, 14, "Lowest new price we've seen this month"),
    _deal("airpods-pro-2", "ebay", 149.99, 380, 9, "Open box, seller warranty"),
    _deal("dyson-v15", "dyson", 549.99, 301, 26, "Stacks with DYSON50"),
    _deal("instant-pot", "walmart", 69.00, 240, 30, "Rollback"),
    _deal("lego-bonsai", "target", 39.99, 214, 5, "20% off, in stock most stores"),
    _deal("ninja-creami", "walmart", 169.00, 156, 3, "Rollback, new low"),
    _deal("stanley-40", "ebay", 29.99, 98, 2, "Rose Quartz only"),
    _deal("pegasus-41", "ebay", 89.99, 77, 1, "Limited sizes"),
    _deal("switch-2", "ebay", 419.99, 64, 40, "Used, excellent"),
]


def build_service(budget_s: float = 1.4):
    """Demo wiring: one fixture adapter per store, simulated checkout probe, in-memory everything."""
    from .adapters import FixtureAdapter, SimulatedProbe
    from .service import DealService
    by_product: dict[str, list[Listing]] = {}
    for q, l in RAW:
        by_product.setdefault(q, []).append(l)
    adapters = [FixtureAdapter(r, [], delay_s=0.03 * i, by_product=by_product) for i, r in enumerate(POLICIES)]
    svc = DealService(PRODUCTS, POLICIES, adapters, COUPONS, probe=SimulatedProbe(), budget_s=budget_s)
    svc.events, svc.deals = list(EVENTS), list(DEALS)
    return svc
