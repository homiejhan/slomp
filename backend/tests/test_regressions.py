"""One test per bug the live verification found. The comment on each names the iteration and the failing test."""
import socket
from datetime import datetime, timezone

import pytest

from slomp import cli, industries as ind
from slomp.identity import identify, model_query
from slomp.online import OnlineDeals, OnlineResult, exact_price, multi_qty
from slomp.sources.feeds import Post, parse_9to5toys
from slomp.terms import ad_terms, bogo_of, conditions_of, post_reference, title_price


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

    # assistant=False: with SLOMP_ASSISTANT set, the client would first read robots.txt through the same broken client
    client = PoliteClient(Store(tmp_path / "slomp.db"), Settings(cache_dir=tmp_path, assistant=False))
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


# --- the manual comparison of Oct 13, 2026 ---------------------------------------------------------------------------
def test_oct13_a_saving_in_a_title_is_not_its_price():
    # "$199 off" was read as a $19 price, and "$1,100 under the Pro model" as the price
    assert title_price("Clearance deal on Black Titanium Apple Watch Ultra 3 with Milanese Loop live again at $199 off")[0] is None
    assert title_price("Segway’s more advanced GT3 electric superscooter at $1,100 under the Pro model, now at $1,400 low "
                       "(Reg. $1,700)")[0] == 1400
    assert title_price("Apple AirPods Pro 3 see $50 discount to $199")[0] == 199
    assert title_price("Save $50 on Beats Studio Pro, now $199")[0] == 199
    assert title_price("Colgate Toothpaste Only 49¢ at Walgreens (Reg. $5)")[0] == 0.49        # Hip2Save's style; not $5
    assert title_price('Sony 65" TV for $1,299.99 + free shipping')[0] == 1299.99
    # titles from the recorded runs: no price, where one was made up from a saving or an order size
    assert title_price("Welax S3 Ergonomic Office Chair: $45 OFF + free shipping")[0] is None             # was $4
    assert title_price("Official fall Prime Day AirPods deals now live at up to $120 off")[0] is None     # was $12
    assert title_price("Macy's Star Deals Week: Up to 80% off + free shipping w/ $39")[0] is None         # was $39
    assert title_price("Household Essentials at Amazon for $15 off $50 + free shipping")[0] is None
    assert title_price("Fanatics Men's Speed Goes Pro Hoodie for $9 + free shipping w/ $49")[0] == 9
    assert title_price("First Autoship Order: 50-Pk 0.5-Oz Catit Creamy Lickable Cat Treats (Salmon) $8.55 + Free S&H "
                       "on $49+")[0] == 8.55


def test_oct13_9to5toys_titles_state_the_saving():
    def deal(title, text):
        xml = (f"<rss><channel><item><title>{title}</title><link>https://9to5toys.com/2026/10/13/x/</link>"
               f"<pubDate>Tue, 13 Oct 2026 14:00:00 +0000</pubDate><description>{text}</description></item></channel></rss>")
        return OnlineDeals(None, None)._deal(parse_9to5toys(xml.encode(), "9to5toys", [])[0],
                                             datetime(2026, 10, 13, 20, tzinfo=timezone.utc), OnlineResult(["tech"]))
    d = deal("Nothing's 2026 Headphone (a) in black hit one of the lowest prices ever today at $119 (40% off)",
             "Amazon is now offering the Nothing Headphone (a) for $119 shipped.")
    assert (d.price, d.pct, d.basis) == (119.0, 40.0, "store_regular")
    d = deal("New ORICO 8-in-1 45W USB-C Power Strip with tilted design plunges to $20 (Save 46%)",
             "Amazon now offers the ORICO power strip for $19.99.")
    assert d.pct == 46.0 and d.industries == ["tech"]
    d = deal("Greenworks' 80V 20-inch cordless electric pole hedge trimmer hits new $243 2026 low ($107 off)",
             "Amazon is now offering the Greenworks 80V pole hedge trimmer for $243 shipped.")
    assert (d.price, d.reference_price) == (243.0, 350.0)


def test_oct13_the_stores_usual_price_in_9to5toys_words():
    assert post_reference("This one normally fetches $37 at Amazon.", 20.0)[:2] == (37.0, "store_regular")
    assert post_reference("That's down from the usual $70 price tag.", 56.0)[:2] == (70.0, "store_regular")
    assert post_reference("Regularly fetching $399, it's now $299.", 299.0)[:2] == (399.0, "store_regular")


def test_oct13_a_drugstore_rewards_scenario_is_not_an_online_product():
    # shown under Beauty in three runs: several products, paid partly in CVS rewards to spend in the store later
    now = datetime(2026, 10, 13, 20, tzinfo=timezone.utc)
    res = OnlineResult(["beauty"])
    p = Post(source="hip2save", id="hip2save:1", url="https://hip2save.com/deals/cvs-best-digital-coupons/",
             title="WOW! Over $68 of Beauty Products Just $4.52 After CVS Rewards", text="", posted_at=now,
             reference=68.0, feed_industries=["beauty"])
    assert OnlineDeals(None, None)._deal(p, now, res) is None
    assert res.excluded["an in-store rewards scenario or a bundle of products"] == 1


def test_oct13_thin_industries_keywords():
    # car gear the keyword rules filed under Tech or Grocery, or nowhere
    assert ind.from_text("iZEEKER 4K+1080P Wireless Dash Camera Front and Rear").industries == ["auto", "tech"]
    assert ind.from_text("Febreze Car Air Freshener Vent Clips, Leather, 2-Count").industries == ["auto"]
    assert ind.from_text("VEVOR Electric Winch 13500 lb w/ 92 ft synthetic rope").industries == ["auto"]
    assert ind.from_text("Autel OBD2 Scanner").industries == ["auto"]
    assert ind.from_text("Opti-Free Puremoist Multi-Purpose Disinfecting Solution with Lens Case, 2-Pack").industries[0] == "health"
    assert ind.from_text("ORICO 8-in-1 45W USB-C Power Strip").industries == ["tech"]
    assert ind.from_text("Chamberlain B4613T Smart Garage Door Opener").industries == ["home"]
    assert ind.from_text("Glade Air Freshener Spray 6-pack").industries == ["grocery"]        # not every freshener is a car's


# --- the third manual comparison (Oct 15, 2026): 79 single-product posts, none read at a wrong price ----------------
def _post9(title, text):
    xml = (f"<rss><channel><item><title>{title}</title><link>https://9to5toys.com/2026/10/15/x/</link>"
           f"<pubDate>Thu, 15 Oct 2026 14:00:00 +0000</pubDate><description>{text}</description></item></channel></rss>")
    return OnlineDeals(None, None)._deal(parse_9to5toys(xml.encode(), "9to5toys", [])[0],
                                         datetime(2026, 10, 15, 20, tzinfo=timezone.utc), OnlineResult(["tech"]))


def test_oct15_a_9to5toys_saving_with_the_price_in_the_post():
    d = _post9("AirPods Pro 3 currently $50 off at Amazon, AirPods Max 2 $120 off",
               "Amazon is still offering them down at $199 right now. That's a solid $50 off the list price.")
    assert (d.price, d.reference_price, d.industries) == (199.0, 249.0, ["tech"])
    d = _post9("Apple's 2026 Mac Studio still $200 off (Amazon all-time low), Mac mini up to $150 off",
               "Amazon is currently offering the most affordable 2026 Mac Studio down at $2,299 shipped.")
    assert (d.price, d.reference_price) == (2299.0, 2499.0)
    # an "up to" saving is no reference, and a body with no price gives none
    assert _post9("Nothing Phone (3) up to $280 off original price for today only at Best Buy",
                  "Amazon has matched its fall Prime Day pricing.") is None


def test_oct15_the_inventory_states_its_percent_in_the_title():
    from slomp.sources.feeds import parse_theinventory
    xml = ("<rss><channel><item><title>Spyder Golf Polo Just $8 on Amazon (60% Off)</title>"
           "<link>https://theinventory.com/x</link><pubDate>Thu, 15 Oct 2026 14:00:00 +0000</pubDate>"
           "<description>A golf polo.</description></item></channel></rss>")
    assert parse_theinventory(xml.encode(), "theinventory", [])[0].pct_stated == 60


def test_oct15_more_goods_get_their_industry():
    assert ind.from_text("Greenworks 40V 12-Inch Brushless Snow Shovel 4.0Ah Battery and Charger").industries == ["home"]
    assert ind.from_text("Bluetti 900Wh Pioneer Na(Sodium) station").industries == ["home"]
    assert ind.from_text("DIY Squishy Making Kit").industries == ["toys"]
    assert ind.from_text("Kids Fairy Potion Kit").industries == ["toys"]
    assert ind.from_text("TP-Link's tiny portable router").industries == ["tech"]
    assert ind.from_text("Zesty Paws Salmon Oil for Dogs & Cats").industries == ["pets"]
    assert ind.from_text("CAP Barbell 25 lb Hex Dumbbell").industries == ["sports"]
    assert ind.from_text("Apple's 2026 Mac Studio").industries == ["tech"]
    assert "fashion" in ind.from_text("Nike Dri-FIT Golf Cap").industries


# --- the fourth manual comparison (Oct 17, 2026) ---------------------------------------------------------------------
def _inventory(title, text):
    from slomp.sources.feeds import parse_theinventory
    xml = (f"<rss><channel><item><title>{title}</title><link>https://theinventory.com/x</link>"
           f"<pubDate>Fri, 16 Oct 2026 14:00:00 +0000</pubDate><description>{text}</description>"
           "</item></channel></rss>")
    return OnlineDeals(None, None)._deal(parse_theinventory(xml.encode(), "theinventory", [])[0],
                                         datetime(2026, 10, 16, 20, tzinfo=timezone.utc), OnlineResult(["home"]))


def test_oct17_the_inventory_gives_the_price_in_the_post_when_its_title_gives_the_saving():
    # The post's own sentence (round 3's evidence): the title said only "$30 Off", so the post was left with no price
    d = _inventory("12-in-1 Air Fryer Toaster Oven Combo $30 Off on Amazon",
                   "The current Amazon price of $129.98 represents a $30 discount from the $159.99 regular price.")
    assert (d.price, d.reference_price, d.basis) == (129.98, 159.99, "store_regular")
    # a percent in the title, and a list price in the post: the post's words say which kind of price it is
    d = _inventory("98-Inch TCL Mini-LED 4K TV Deal: 45% Off at Amazon",
                   "Amazon has it for $2,197.99, while the list price is $3,999.99.")
    assert (d.price, d.reference_price, d.basis) == (2197.99, 3999.99, "list")
    # amounts that don't agree with the title's saving are not taken for the price
    assert _inventory("Hauslane 30-Inch Wall Mount Range Hood $50 Off on Amazon",
                      "Free shipping on orders over $35. The hood is $449.99.") is None


def test_oct17_a_regular_price_named_after_its_amount():
    assert post_reference("It's $129.98, a $30 discount from the $159.99 regular price.", 129.98)[:2] == \
        (159.99, "store_regular")


def test_oct17_goods_and_sales_without_an_industry():
    assert ind.from_text("Aospenice 19-Quart Cold Therapy Knee Ice Machine").industries == ["health"]
    assert ind.from_text("Argo Books Lifetime Accounting Software").industries == ["tech"]
    assert ind.from_text("Cricut Maker 3 with Design Space software").industries == []      # not every software
    assert ind.from_text("Countertop Ice Machine").industries == []                      # an ice maker isn't therapy
    assert ind.from_text("Apple Outlet Deals at Best Buy").industries == ["tech"]
    assert ind.from_text("Carhartt, Dickies, Workwear & More Deals at Woot").industries == ["fashion"]
    assert ind.from_text("Woot Pest Prevention Deals").industries == ["home"]
    assert ind.from_text("Woot Wellness Aisle Clearance").industries == ["health"]
    assert ind.from_text("Wellness CORE Grain-Free Dry Dog Food").industries == ["pets"]    # the pet food brand
    assert "beauty" in ind.from_text("Target Oral Care & Sanitizing Essentials Deals").industries


def test_oct17_sales_at_brands_slomp_did_not_know():
    from collections import Counter

    from slomp.sales import StoreSales
    now = datetime(2026, 10, 17, 17, tzinfo=timezone.utc)
    for title, seller, store, inds in (("Wilson Fall Sale: Up to 50% off + free shipping w/ $75", "Wilson", "Wilson",
                                        ["sports"]),
                                       ("Dearfoams Semi-Annual Friends & Family Sale: 20% off sitewide", "Dearfoams",
                                        "Dearfoams", ["fashion"])):
        p = Post(source="dealnews", id="dealnews:1", url="https://www.dealnews.com/x/1.html", title=title, text="",
                 seller=seller, deal_type="sale", posted_at=now)
        s = StoreSales(None, None).sale(p, now, Counter())
        assert (s.store_name, s.industries) == (store, inds)


# --- the fifth manual comparison (Oct 20, 2026) ----------------------------------------------------------------------
def test_oct20_woot_category_sales_get_their_industry():
    assert ind.from_text("Auto Parts & Accessories Sell Out Deals at Woot").industries == ["auto"]
    assert ind.from_text("Auto Deals Market Sale at Woot").industries == ["auto"]
    assert ind.from_text("Sports Overstock Clearance Deals at Woot").industries == ["sports"]
    assert ind.from_text("Gloves & Safety Wear Sale at Woot").industries == ["home"]
    assert ind.from_text("Gatorade Sports Drink 24-pack").industries == ["grocery"]      # not every "sports"
