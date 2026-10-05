"""One test per bug the live verification found. The comment on each names the iteration and the failing test."""
import socket

import pytest

from slomp import cli, industries as ind
from slomp.identity import identify, model_query
from slomp.online import exact_price, multi_qty
from slomp.terms import ad_terms, bogo_of, conditions_of


def test_it01_headline_percent_is_not_turned_into_a_regular_price():
    # it01 L-MATH: Dollar General "28%" headline -> Slomp showed savings $2.04; the record says $2.00
    t = ad_terms({"current_price": "5.25", "discount": 28}, feed=False)
    assert t.pct == 28.0 and t.regular is None and t.savings is None


def test_it01_rounded_title_price_uses_exact_text_price():
    # it01 O-FID: dealnews "$51" (page: $50.99); Slickdeals "$26.40" (post: "= $26.39")
    assert exact_price("Target offers the LEGO set for $50.99. That's a $13 low.", 51.0) == 50.99
    assert exact_price("on sale for $47.99 - 45% (automatically applied at checkout) = $26.39 .", 26.4) == 26.39
    assert exact_price("for $12.99 and up", 49.0) == 49.0


def test_it01_multibuy_online_is_per_unit():
    # it01 O-MER: "12-Pack for 3 for $15" was shown as $15 for one 12-pack (Amazon: $6.97 each)
    assert multi_qty("Pepsi Zero Sugar 12-oz. Can 12-Pack for 3 for $15 via Sub. & Save", 15.0) == 3
    assert multi_qty("Sony WH-1000XM6 for $398", 398.0) == 1


def test_it01_checkout_discount_is_a_condition():
    # it01 O-MER: Fanttik X8 "$72 when you add it to cart and proceed for an extra 10% off in checkout"
    assert "discount applied in cart" in conditions_of("is $72 when you add it to cart for an extra 10% off in checkout")


def test_it01_lego_identity_is_the_set_number():
    # it01 O-CMP: "LEGO Icons Williams Racing FW14B" keyed on the car's name, not set 10353
    assert identify("LEGO Icons Williams Racing FW14B & Nigel Mansell").model == ""
    assert identify("799-pc LEGO Icons Williams Racing FW14B (10353)").key == "lego|10353"


def test_it01_product_lines_and_accessories_are_not_compared():
    # it01 O-CMP: "Ultimate365" polo lines and a "case for Nintendo Switch 2" were compared as products
    assert identify("adidas Men's Ultimate365 Solid Golf Polo Shirt").model == ""
    assert model_query(identify("20-in-1 Bundle Case for Nintendo Switch 2 (Black)")) is None


def test_it01_industry_judge_disagreements():
    # it01 L-IND: KT therapy tape (Personal Care) is health; O-IND: vitamins in a beauty feed; cat-print tees
    assert ind.classify_ad_item("Health & Beauty", "Personal Care", "KT Kinesiology Therapy Tape", "", []).industries == ["health"]
    assert ind.from_text("VitaUp Men's 20-In-1 Vitamins 90-Count").industries == ["health"]
    assert ind.from_text("Women's Cat Christmas Tees from $7.69").industries == ["fashion"]
    assert ind.from_text("Purina Pro Plan Dog Food 30 lb").industries == ["pets"]


def test_it03_industry_judge_disagreements():
    # it03 L-IND: "Apothic Red" at Walgreens fell back to the pharmacy's health/beauty prior; it's wine
    assert ind.classify_ad_item(None, None, "Apothic Red", "", []).industries == ["grocery"]
    assert ind.from_text("Josh Cellars Cabernet Sauvignon").industries == ["grocery"]
    # it03 O-IND: Hip2Save's kids feed put drawstring bags in Baby & Kids; they're bags
    assert ind.from_text("Walmart Drawstring Bags Just $5 (Reg. $13) | Cute Hearts & Gingham Print").industries == ["fashion"]


def test_it04_landing_pages_are_not_store_pages():
    # it04 L-RET: Dollar General's "store page" for Febreze was its coupons landing page
    from slomp.sources.flipp import is_product_link
    assert not is_product_link("https://www.dollargeneral.com/deals/coupons?ab=Circular_AdsPromos", [])
    assert is_product_link("https://www.petsmart.com/cat/furniture/whisker-city-plush-mansion-12345.html", [])


def test_it04_price_with_space_after_dollar_sign():
    # it04 O-FID (test bug): Slickdeals wrote "= $ 18.60"
    from slomp.verify.pages import has_price
    assert has_price("40% off with code ADIDAS40 = $ 18.60 . Shipping", 18.6)
    assert not has_price("$118.60", 18.6)


def test_it04_industry_judge_disagreements():
    # it04 L-IND: "Diamond Mesh Gate" at Kroger was jewelry (bare "diamond"); it's a safety gate
    assert "fashion" not in ind.from_text("Diamond Mesh Gate").industries
    assert "baby" in ind.from_text("Diamond Mesh Gate").industries
    assert "fashion" in ind.from_text("1 Ct. T.W. Lab-Grown Diamond Ring").industries
    # it04 L-IND: a reptile terrarium at PetSmart was Home (taxonomy: Decor); a pet-only store decides
    c = ind.classify_ad_item("Home & Garden", "Decor", "Thrive Acrylic Reptile Terrarium", "", ["pets"], exclusive=True)
    assert c.industries == ["pets"]


def test_it04_audit_keyword_collisions():
    # found by auditing iteration 4's keyword-labelled items, before a judge test hit them
    assert ind.from_text("Liz Claiborne Signature Plush Solid Bath Towel").industries == ["home"]      # not toys
    assert ind.from_text("Linden Street Cotton Flannel Queen Sheet Set").industries[0] == "home"        # not fashion
    assert ind.from_text("Bosch 800 Series Espresso, Coffee and Cold Brew Machine").industries[0] == "home"
    assert ind.from_text("Manscaped The Lawn Mower 5.0 Ultra Essentials kit").industries[0] == "beauty"
    assert "fashion" not in ind.from_text("Wingstop Watch Party Bundle").industries
    assert ind.from_text("Apple Watch Series 11 GPS 42mm").industries == ["tech"]
    assert ind.from_text("Citizen watches").industries == ["fashion"]


def test_it05_gardening_gloves_are_home():
    # it05 L-IND: Miracle-Gro floral crinkle gloves at Tractor Supply were Fashion (taxonomy: Clothing Accessories)
    c = ind.classify_ad_item("Apparel & Accessories", "Clothing Accessories",
                             "Miracle-Gro Women's Polyester Floral Crinkle Gloves, 1-Pair", "", ["home", "pets"])
    assert c.industries == ["home"]
    assert ind.classify_ad_item("Apparel & Accessories", "Clothing Accessories", "Women's Knit Gloves", "", []).industries == ["fashion"]


def test_it05_audit_online_labels():
    # found by auditing iteration 5's online labels
    assert ind.from_text("MAREE Toner Pads Just $7 Shipped on Amazon").industries == ["beauty"]
    assert ind.from_text("Always Discreet Pads or Underwear").industries[0] == "health"
    assert ind.from_text("Egg Night Light Only $9.99 | Up to 100-Hour Battery").industries == ["home"]
    assert ind.from_text("Creativity for Kids Mini Garden Terrariums from $5").industries[0] == "toys"
    assert ind.from_text("Zoo Med Reptile Terrarium 20 Gallon").industries == ["pets"]
    assert "tech" in ind.from_dealnews("Drones").industries


def test_it06_industry_judge_disagreements():
    # it06 L-IND: a Ring indoor security cam at Best Buy was Home (taxonomy: Home Security); judge: Tech
    c = ind.classify_ad_item("Home & Garden", "Home Security", "Ring - Pan-Tilt Indoor Security Cam", "Ring", ["tech"])
    assert "tech" in c.industries
    # it06 L-IND: a pintle hook at Tractor Supply was Home (taxonomy: Hardware); judge: Automotive
    c = ind.classify_ad_item("Hardware", "Hardware Accessories", "bROK WARRIOR 15t Capacity Warrior Bolt-On Pintle Hook",
                             "", ["home", "pets"])
    assert c.industries == ["auto"]


def test_it06_audit_taxonomy_labels():
    # found by auditing taxonomy-labelled items from iterations 4-6
    assert ind.classify_ad_item("Business & Industrial", "Material Handling", "20 Ton Hydraulic Low-Profile Bottle Jack", "", []).industries == ["auto"]
    assert ind.classify_ad_item("Hardware", "Plumbing", "Tubeless Tire Repair Kit, 9-Piece", "", []).industries == ["auto"]
    assert ind.classify_ad_item("Sporting Goods", "Outdoor Recreation", "Threshold™ throws", "", []).industries == ["home"]
    assert ind.classify_ad_item("Hardware", "Adhesives, Coatings & Sealants", "Elmer's® Washable School Glue, 1 Gal", "", []).industries == ["office"]
    assert ind.classify_ad_item("Electronics", "Electronics Accessories", "V20 3Ah Advanced Battery Starter Kit", "", []).industries == ["home"]
    assert "fashion" in ind.classify_ad_item("Business & Industrial", "Signage", "Cat & Jack kids' clothing", "", []).industries
    assert ind.classify_ad_item("Health & Beauty", None, "Dr Teal's Lotion 18 oz., Foaming Bath or Epsom Salt Soak", "", []).industries == ["beauty", "health"]
    from slomp.sources.flipp import junk_reason
    assert junk_reason({"display_type": 1, "name": "Must be an ExtraCare cardholder and present card at checkout"})
    assert not junk_reason({"display_type": 1, "name": "Limited Edition Holiday Mug"})


def test_it08_industry_judge_disagreements():
    # it08 L-IND: "Body Wash ... with Hyaluronic Acid & Vitamin B3" was Health (an ingredient); judge: Beauty
    t = "Caress Black Orchid & Patchouli Oil Moisturizing Body Wash, Body Soap with Hyaluronic Acid & Vitamin B3"
    assert ind.classify_ad_item("Health & Beauty", None, t, "Caress", []).industries == ["beauty"]
    assert ind.from_text(t).industries[0] == "beauty"
    assert ind.from_text("Aveeno Daily Moisturizing Lotion with Oat").industries[0] == "beauty"
    # it08 L-IND: a Funko plush at GameStop, filed by Flipp under Baby Toys, was Baby & Kids; judge: Toys
    c = ind.classify_ad_item("Baby & Toddler", "Baby Toys", "Funko Jurassic Park 6-in Mini Beanbag Plush", "Funko", ["tech"])
    assert c.industries == ["toys"]
    c = ind.classify_ad_item("Baby & Toddler", "Baby Toys", "Itzy Ritzy Itzy Bitzy Spiral Stroller Toy", "", [])
    assert "baby" in c.industries


def test_it09_implausible_savings_are_named():
    # it09 L-REC: GameStop's ad lists a $4.99 plush at $0.02 ("100% off"); Slomp rejected the saving but recorded
    # it as "no saving stated"
    t = ad_terms({"current_price": "0.02", "original_price": 4.99, "discount": 100}, feed=False)
    assert t.basis == "none" and t.rejected.startswith("99.6% off")


def test_it09_industry_judge_disagreements():
    # it09 L-IND: Michaels scrapbooks and photo albums were Grocery (taxonomy: Household Supplies); judge: Home, Toys
    c = ind.classify_ad_item("Home & Garden", "Household Supplies", "ALL Scrapbook & Photo Albums", "", ["toys", "home"])
    assert "grocery" not in c.industries and c.industries[0] in ("toys", "home")
    assert ind.classify_ad_item("Home & Garden", "Household Supplies", "Charmin Ultra Soft Toilet Paper", "", []).industries == ["grocery"]
    assert ind.classify_ad_item("Home & Garden", "Household Supplies", "Sterilite 66 Qt. Storage Tote", "", []).industries == ["home"]
    # it09 O-IND: a Perler fuse-bead kit (Hip2Save kids feed) was Baby & Kids; judge: Toys
    assert ind.from_text("Perler Harry Potter Fuse Bead Kit Only $8 on Amazon").industries == ["toys"]


def test_it10_removed_posts_and_late_night_ad_ends():
    from datetime import datetime, timezone
    from slomp.sources.feeds import post_gone
    # it10 O-FID: dealnews' feed linked an ended deal straight to its Amazon store listing page (no redirect)
    u = "https://www.dealnews.com/s313/Amazon/22242953.html"
    assert post_gone(u, u, "<h1>Amazon Deals</h1>", "Hudson Baby Long-Sleeve Fleece Sleeping Bag for $11")
    live = "https://www.dealnews.com/Hudson-Baby-Sleeping-Bag-for-11/22242953.html"
    assert not post_gone(live, live, "<h1>Hudson Baby Long-Sleeve Fleece Sleeping Bag for $11</h1>",
                         "Hudson Baby Long-Sleeve Fleece Sleeping Bag for $11")
    # it10 L-FID: "through Oct 4" is 11:59 PM Eastern at Flipp, which pulls the item at 10:59 PM Central
    from slomp.geo import ad_end_local
    vt = datetime.fromisoformat("2026-10-04T23:59:59-04:00")
    now = datetime(2026, 10, 4, 23, 9, tzinfo=timezone.utc).replace(hour=4, day=5)    # 11:09 PM CDT, Oct 4
    assert min(ad_end_local(vt, "America/Chicago"), vt) < now < ad_end_local(vt, "America/Chicago")


def test_final_check_filing_is_office_only_with_office_nouns():
    # found in the final UI check: "Gain Plus Super Filings ... Laundry Detergent" (an ad typo for Flings) was Office
    assert ind.from_text("Gain Plus Super Filings 45 ct. or Liquid Laundry Detergent 134 Load").industries == ["grocery"]
    assert ind.from_text("Bankers Box Filing Cabinet Folders").industries == ["office"]


def test_ui_review_labels_stay_within_what_the_store_sells():
    # found while adding pictures: the source filed these under Food or Beverages
    from slomp.reference import merchant

    def label(store, l1, l2, title):
        m = merchant(store)
        return ind.classify_ad_item(l1, l2, title, "", m.industries, m.exclusive, m.sells, m.food).industries

    food = ("Food, Beverages & Tobacco", "Food Items")
    assert label("JCPenney", *food, "3-5/8 ct. t.w. lab-grown diamond; 2-3/4 ct. center stone") == ["fashion"]
    assert label("Best Buy", *food, "Ninja - CREAMi Deluxe 11-in-1 Ice Cream and Frozen Treat Maker") == ["home"]
    assert label("Lowe's", "Food, Beverages & Tobacco", "Beverages", "100-Pack Carbon Steel Utility Razor Blades") == ["home"]
    assert label("Kohl's", *food, "Itzy Ritzy Rainbow Ritzy Rings") == ["baby"]
    assert label("JCPenney", None, None, "Martha Stewart 4-Pc. Wine Glass Set") == ["home"]
    # real food stays food, and a hardware store's barbecue sauce is real
    assert label("H-E-B", *food, "Jumbo Raw White Shrimp") == ["grocery"]
    assert label("Walmart", *food, "Doritos Nacho Cheese Tortilla Chips") == ["grocery"]
    assert label("Ace Hardware", *food, "Sauces, Seasonings & Rubs") == ["grocery"]
    assert label("Ace Hardware", "Home & Garden", "Household Supplies", "Glad ForceFlex Trash Bags") == ["grocery"]


def test_ui_review_bogo_punctuation_and_ranking():
    # found while adding pictures: the ad picture said "BUY ONE, GET ONE 50% OFF" but the card said "50% off"
    assert bogo_of("BUY ONE. GET ONE 50% OFF regular retail of equal or lesser value") == ("buy 1 get 1 50% off", 25.0)
    assert bogo_of("Buy 1 get 1 50%* off with myWalgreens") == ("buy 1 get 1 50% off", 25.0)
    assert bogo_of("Buy 1 get 1 50% off*") == ("buy 1 get 1 50% off", 25.0)
    t = ad_terms({"current_price": "", "percent_off": 50.0, "sale_story": "Buy 1 get 1 50%* off with myWalgreens"}, feed=False)
    assert (t.bogo, t.pct, t.basis) == ("buy 1 get 1 50% off", 25.0, "store_regular")     # ranked, not zero-weighted


def test_ui_review_bogo_glued_and_ordinal():
    assert bogo_of("Buy 1 get 150% OFF* WITH CARD") == ("buy 1 get 1 50% off", 25.0)        # CVS: missing space
    assert bogo_of("Buy 2 get 3rd FREE* WITH CARD") == ("buy 2 get 1 free", 33.3)           # the third one is free
    assert bogo_of("BUY 2 GET 3 FREE") == ("buy 2 get 3 free", 60.0)                        # Randalls: really three
    assert bogo_of("Buy 1, get 50% off the second") == ("buy 1 get 1 50% off", 25.0)
    assert bogo_of("Buy 1 get 1 FREE*") == ("buy 1 get 1 free", 50.0)


def test_a_second_item_for_half_off_is_not_free():
    # regular deals audit: "buy 1, get 1 for 50% off individual meals" (Whole Foods) was read as buy one get one free
    assert bogo_of("Tuesdays: $2 off Rotisserie Chicken; buy 1, get 1 for 50% off individual meals") == ("buy 1 get 1 50% off", 25.0)
    assert bogo_of("Buy one, get one at half price") == ("buy 1 get 1 50% off", 25.0)
    assert bogo_of("Buy 1 get 1 for $1") == ("", None)                     # a second one for a dollar is not a free one
    assert bogo_of("Buy 1 get 1 FREE*") == ("buy 1 get 1 free", 50.0)


def test_it11_industry_judge_disagreements():
    # it11 L-IND: a hair cream with only a top-level "Health & Beauty" label was shown under Health too
    t = "SheaMoisture Silk Press Prep Hair Cream with Plant-Derived Straightening Complex"
    assert ind.classify_ad_item("Health & Beauty", None, t, "", []).industries == ["beauty"]
    # it11 L-IND: bladder control pads filed under Personal Care were Beauty; judge: Health
    t = "Composure Bladder Control Pads 24-66 ct. or Male Guard 52 ct."
    assert ind.classify_ad_item("Health & Beauty", "Personal Care", t, "", []).industries == ["health"]


def test_it12_industry_judge_disagreements():
    from slomp.online import classify_post
    from slomp.sources.feeds import Post
    # it12 L-IND: a can cooler at Cabela's, filed under Kitchen & Dining, was shown under Home; judge: Sports
    t = "Puffin Drinkwear The Hoodie Can Cooler with Bass Pro Shops Logo - Black"
    assert ind.classify_ad_item("Home & Garden", "Kitchen & Dining", t, "", ["sports"]).industries == ["sports"]
    assert ind.classify_ad_item("Home & Garden", "Kitchen & Dining", "Igloo 52 qt. Cooler", "", []).industries == ["home"]
    # it12 L-IND: a makeup setting spray with only a top-level "Health & Beauty" label was shown under Health too
    t = "Milani Make It Last Charcoal Jumbo XL Setting Spray, Matte Finish, Long Lasting"
    assert ind.classify_ad_item("Health & Beauty", None, t, "", []).industries == ["beauty"]
    # it12 O-IND: bubble wands from Hip2Save's kids feed were shown under Baby & Kids; judge: Toys
    p = Post(source="hip2save", id="hip2save:1", url="https://hip2save.com/x", text="", feeds=["hip2save sales-deals/kids"],
             title="Halloween Mini Bubble Wands 30-Pack Only $4.79 on Amazon (Reg. $10)", feed_industries=["baby", "toys"])
    assert classify_post(p).industries == ["toys"]
    assert ind.from_text("Scrubbing Bubbles Bathroom Cleaner").industries == ["grocery"]
    # it12 O-IND: "tote" made a six-pack of storage totes Fashion; judge: Home
    assert ind.from_text("Foldable Storage Tote 6-Pack Only $9.99 on Amazon (Reg. $33) – Organize Your Closet").industries == ["home"]
    assert ind.from_text("Women's Canvas Tote Only $12 at Target").industries == ["fashion"]


def test_serve_explains_a_busy_port(capsys, monkeypatch):
    # a second `slomp serve` beside a running one died with "[Errno 48] ... address already in use" and no way forward
    import uvicorn
    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: pytest.fail("must not start on a port that is taken"))
    with socket.socket() as taken:
        taken.bind(("127.0.0.1", 0))
        taken.listen()
        port = taken.getsockname()[1]
        assert cli.main(["serve", "--port", str(port)]) == 1
    err = capsys.readouterr().err
    assert f"Port {port} is already in use" in err and "Ctrl+C" in err and f"slomp serve --port {port + 1}" in err


def test_serve_starts_on_a_free_port(monkeypatch):
    import uvicorn
    started = []
    monkeypatch.setattr(uvicorn, "run", lambda app, **k: started.append((app, k)))
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    assert cli.main(["serve", "--port", str(port)]) == 0 and started == [("slomp.api:app", {"port": port})]


def test_a_site_whose_certificate_cannot_be_verified_is_a_failed_read_not_a_crash(tmp_path):
    # regular deals research: older httpcore let ssl.SSLCertVerificationError through, which stopped a whole search
    import asyncio
    import ssl
    from slomp.config import Settings
    from slomp.db import Store
    from slomp.http import FetchError, PoliteClient

    class Broken:
        calls = 0

        async def get(self, *a, **k):
            Broken.calls += 1
            raise ssl.SSLCertVerificationError(1, "[SSL: CERTIFICATE_VERIFY_FAILED] unable to get local issuer certificate")

    client = PoliteClient(Store(tmp_path / "slomp.db"), Settings(cache_dir=tmp_path))
    client._client = Broken()
    with pytest.raises(FetchError) as err:
        asyncio.run(client.get("https://example.test/page", ttl_s=60))
    assert "certificate" in err.value.reason and Broken.calls == 1          # no retries: a retry can't fix a certificate



def test_robots_rules_addressed_to_ai_assistants_are_seen(tmp_path):
    # regular deals, run 1: three sites let ordinary readers in but tell Anthropic's agents, by name, to keep out
    import asyncio
    import time
    from slomp.config import Settings
    from slomp.db import Store
    from slomp.http import PoliteClient, Response

    robots = {
        "https://zoo.test": "User-agent: GPTBot\nUser-agent: Claude-Code\nUser-agent: ClaudeBot\nDisallow: /\n\n"
                            "User-agent: *\nDisallow: /admin/\n",
        "https://open.test": "User-agent: GPTBot\nDisallow: /\n\nUser-agent: *\nDisallow: /search\n",
        "https://shut.test": "User-agent: *\nDisallow: /\n",
    }
    client = PoliteClient(Store(tmp_path / "slomp.db"), Settings(cache_dir=tmp_path))

    async def fake_get(url, *a, **k):
        origin = url[:url.index("/", 8)]
        return Response(url, url, 200, "text/plain", robots[origin].encode(), time.time())
    client.get = fake_get
    ask = lambda u: (asyncio.run(client.allowed(u)), asyncio.run(client.turns_away_ai(u)))      # noqa: E731
    assert ask("https://zoo.test/plan-a-visit") == (True, True)       # Slomp may read it; an AI assistant may not
    assert ask("https://open.test/deals") == (True, False)            # only another company's bot is named
    assert ask("https://shut.test/deals") == (False, False)           # closed to everyone: the ordinary rule covers it
