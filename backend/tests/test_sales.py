"""Online stores' sales (slomp/sales.py, slomp/stores_online.py): which posts are sales, at which store, the offer,
the code, the dates and what is shown when. Titles and texts are real posts read on Oct 6, 2026."""
from collections import Counter
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from slomp.models import StoreSale
from slomp.sales import (SalesResult, StoreSales, code_of, dedupe, live_reason, not_a_sale, offer_text, parse_offer,
                         rank_pct, sale_dates, sale_name, select, shipping_of, to_payload)
from slomp.sources.feeds import Post, dealnews_stated, parse_dealnews
from slomp.sales import find_store
from slomp.stores_online import by_key, store_named, stores_in

CT = ZoneInfo("America/Chicago")
NOW = datetime(2026, 10, 6, 21, 0, tzinfo=CT)


def post(title, text="", source="dealnews", seller="", deal_type="sale", posted=NOW - timedelta(hours=3), **kw):
    return Post(source=source, id=f"{source}:{abs(hash(title))}", url=f"https://example.com/{abs(hash(title))}",
                title=title, text=text, seller=seller, deal_type=deal_type, posted_at=posted, **kw)


def offer(title):
    return offer_text(parse_offer(title))


# --- dealnews end dates ---------------------------------------------------------------------------------------------
def test_a_dealnews_expiry_is_real_unless_it_is_the_placeholder():
    posted = datetime(2026, 10, 6, 17, 6, 1, tzinfo=timezone(timedelta(hours=-4)))
    assert not dealnews_stated(datetime(2027, 1, 4, 16, 6, 1, tzinfo=timezone(timedelta(hours=-5))), posted)  # +90 d
    assert not dealnews_stated(posted + timedelta(days=30, hours=1, seconds=-10), posted)    # +30 d, a clock change
    assert not dealnews_stated(posted + timedelta(days=7, seconds=-3), posted)
    # an editor's ends: midnight Pacific, 1 AM Eastern, 11:59 PM
    assert dealnews_stated(datetime(2026, 10, 12, 2, 59, tzinfo=timezone(timedelta(hours=-4))), posted)
    assert dealnews_stated(datetime(2026, 10, 7, 1, 0, tzinfo=timezone(timedelta(hours=-4))), posted)
    assert dealnews_stated(datetime(2026, 10, 8, 23, 59, tzinfo=timezone(timedelta(hours=-4))), posted)
    assert not dealnews_stated(None, posted)


def test_parse_dealnews_marks_an_editors_end_as_stated():
    xml = b"""<rss xmlns:dealnews="https://www.dealnews.com/ns/rss/1.0.htm"><channel>
    <item><title>Best Buy Techtober Headphones Deals: Up to 68% off + free shipping</title>
      <link>https://www.dealnews.com/x/22249980.html?iref=rss</link><pubDate>Tue, 06 Oct 2026 14:22:21 -0400</pubDate>
      <dealnews:expires>2026-10-12T02:59:00-04:00</dealnews:expires><dealnews:dealType>Sale</dealnews:dealType>
      <dealnews:retailer>Best Buy</dealnews:retailer></item>
    <item><title>Insignia 65" TV for $260 + free shipping</title>
      <link>https://www.dealnews.com/x/22249990.html</link><pubDate>Tue, 06 Oct 2026 17:06:01 -0400</pubDate>
      <dealnews:expires>2027-01-04T16:06:01-05:00</dealnews:expires><dealnews:dealType>Product</dealnews:dealType></item>
    </channel></rss>"""
    sale, tv = parse_dealnews(xml, "f", [])
    assert sale.expires_stated and sale.deal_type == "sale" and sale.seller == "Best Buy"
    assert not tv.expires_stated


# --- the store ------------------------------------------------------------------------------------------------------
def test_stores_by_the_names_deal_sites_use():
    assert store_named("Woot! An Amazon Company").key == "woot"
    assert store_named("Kohls").key == "kohls"
    assert store_named("Macy’s").key == "macys"
    assert store_named("ShopSimon.com").key == "shopsimon"
    assert store_named("Amazon After Rebate").key == "amazon"      # Hip2Save's store field runs on
    assert store_named("www.bestbuy.com").key == "bestbuy"
    assert store_named("Great Clips") is None


def test_a_store_in_text_is_a_whole_name_with_a_capital():
    assert [s.key for _, s, _ in stores_in("Kohl's Deal Days at Kohl's")] == ["kohls"]
    assert stores_in("a targeted ad") == [] and stores_in("hit the target") == []
    assert [s.key for _, s, _ in stores_in("Up to 60% off at GAP Factory")] == ["gapfactory"]   # not Gap


def test_where_a_sale_is():
    hip = dict(source="hip2save", deal_type="")
    assert find_store(post("Up to 55% Off Sony Headphones & Earbuds on Amazon + FREE Shipping", **hip))[0].key == "amazon"
    birk = post("*RARE* Up to 45% Off Birkenstock Sandals + FREE Shipping!",
                "Head to QVC.com where they are offering rare savings on select Birkenstock styles!", **hip)
    assert find_store(birk)[0].key == "qvc"                          # the brand is not the store
    assert find_store(post("Samsonite luggage drops as low as $64 for Prime Day (Up to 64% off)",
                           source="9to5toys", deal_type=""))[0].key == "amazon"
    assert find_store(post("Kohl's Deal Days Sale: Up to 60% off", seller="Kohl's"))[0].key == "kohls"
    assert find_store(post("High Test Gummies Sitewide Sale: Extra 20% off", seller="High Test Gummies")) == (None, "")


# --- is it a sale -------------------------------------------------------------------------------------------------
def test_what_is_and_is_not_a_store_sale():
    def why(title, **kw):
        return not_a_sale(post(title, **kw), parse_offer(title))
    assert why("Kohl's Deal Days Sale: Up to 60% off + extra 25% off + free shipping") == ""
    assert why("40% Off Target Handbags = Styles from $9", source="hip2save", deal_type="") == ""
    assert why("Trident Original Sugar Free Chewing Gum 14-Piece Pack: 41 cents + free shipping w/ Prime") == \
        "no discount stated"
    assert why("50% Off Beet Root Capsules on Amazon | Supports Heart Health", source="hip2save", deal_type="") == \
        "one product, not a sale"
    assert why("Dell 27 Plus Monitor for $170 + free shipping", deal_type="product") == "one product, not a sale"
    assert why("$100 Uber Gift Card for $80", deal_type="deal") == "a gift card"
    assert why("Costco 1-Year Gold Star Membership for $65 w/ $20 Costco Shop Card", deal_type="deal") == "a membership"
    assert why("Walgreens Seniors Day Savings: 20% off + free shipping w/ $35") == "a discount for a group of people"
    assert why("Baked Snacks at Target: Buy 1, get 1 50% off + pickup") == "pickup only"
    assert why("PlayStation Store Autumn Adventures Sale: Up to 75% off") == "digital, not shipped"
    assert why("Best Target Sales This Week | Clothing, Beauty, Home", source="hip2save", deal_type="") == \
        "a roundup of other deals"


# --- the offer ----------------------------------------------------------------------------------------------------
def test_offers_read_from_titles():
    assert offer("Kohl's Deal Days Sale: Up to 60% off + extra 25% off + free shipping") == \
        ("Up to 60% off + extra 25% off", "Extra 25%", False)
    assert offer("LEGO Deal Days Event at Kohl's: 40% off everything + free shipping") == ("40% off", "40% off", False)
    assert offer("Target Circle Deal Days Sale: 30% to 40% off most items + free shipping w/ $35")[:2] == \
        ("30–40% off", "30–40% off")
    assert offer("Fanatics MLB Deals: Up to 89% off + 10% to 35% off + shipping varies")[:2] == \
        ("Up to 89% off + extra 10–35% off", "Extra 10–35%")
    assert offer("Macy's Star Deals Week: Up to 80% off + free shipping w/ $39") == ("Up to 80% off", "Up to 80%", True)
    assert offer("Household Essentials at Amazon for $15 off $50 + free shipping") == ("$15 off $50+", "$15 off", True)
    assert offer("Apple Deal Days at Target: Up to $100 off + free shipping w/ $35")[:2] == ("Up to $100 off", "Up to $100")


def test_bogo_offers_are_not_also_a_percent_off_everything():
    assert offer("Target Candle Deals: Buy 1, Get 1 50% Off + free shipping w/ $35")[:2] == \
        ("Buy 1 get 1 50% off", "BOGO 50%")
    assert rank_pct(parse_offer("Target Candle Deals: Buy 1, Get 1 50% Off")) == 25.0
    assert offer("K-Cup Deals at Staples: Buy 1, get extra 75% off 2nd + free shipping")[:2] == \
        ("Buy 1 get 1 75% off", "BOGO 75%")
    o = parse_offer("Walgreens Halloween Weekly Deals: BOGO & More + free shipping w/ $35")
    assert o.bogo == "buy one, get one deals" and rank_pct(o) is None     # which kind isn't said


def test_ranking_counts_ceilings_at_half():
    assert rank_pct(parse_offer("Sale: 40% off everything")) == 40.0
    assert rank_pct(parse_offer("Sale: Up to 80% off")) == 40.0
    assert rank_pct(parse_offer("Sale: Up to 60% off + extra 25% off")) == 47.5     # 25 firm, 70 at most
    assert rank_pct(parse_offer("Sale: 60% off + extra 25% off")) == 70.0
    assert rank_pct(parse_offer("Sale: $15 off $50")) == 15.0
    assert rank_pct(parse_offer("Sale: Up to $1,600 off")) is None


def test_shipping_is_not_the_offer():
    assert shipping_of("Macy's Star Deals Week: Up to 80% off + free shipping w/ $39") == "Free shipping on $39+"
    assert shipping_of("Woot Toy Clearance: Up to 69% off + free shipping w/ Prime") == "Free shipping with Prime"
    assert shipping_of("Nautica Sitewide Sale: Up to 60% Off + Free S&H on $60+") == "Free shipping on $60+"
    assert shipping_of("Dick's Fall Deal Drop Sale: Up to 91% off + shipping varies") == "Shipping varies"


# --- the code -------------------------------------------------------------------------------------------------------
def test_codes_come_from_the_post_and_its_own_sentence_decides():
    day = NOW.date()
    assert code_of("Woot Wootober Promo Code: Extra 22% off", 'Today only, use the promo code "WOOTOBER" to cut an extra '
                   "22% off everything.", by_key()["woot"], day, day)[0] == "WOOTOBER"
    assert code_of("Sale", "Plus, use promo code GFEXTRA for free shipping + 15% off other sale styles.")[0] == "GFEXTRA"
    assert code_of("Sale", "No promo code needed! Prices as marked.")[0] == ""
    # a code for cardholders is not the sale's code
    assert code_of("J.Crew Friends & Family Sale", 'J.Crew Credit Card holders can stack an extra 20% off with code '
                   '"CARDLOVE". The sale ends on October 12.')[0] == ""
    # a code for another store, or for a day that has passed
    qvc = 'Plus, today, October 3rd only, new QVC customers can score an extra 20% off with promo code JOLLYQ20 at checkout!'
    assert code_of("Birkenstock Sandals", qvc, by_key()["birkenstock"], day - timedelta(days=3), day)[0] == ""
    assert code_of("Birkenstock Sandals", qvc, by_key()["qvc"], day - timedelta(days=3), day)[0] == ""
    code, note, conds = code_of("Birkenstock Sandals", qvc, by_key()["qvc"], day - timedelta(days=3), day - timedelta(days=3))
    assert code == "JOLLYQ20" and conds == ["the code is for new customers"]
    # a code that only buys delivery says so
    assert code_of("Up to 40% Off Hair Care at Sephora", "Plus, score FREE Same-Day Delivery, where available, with "
                   "promo code DELIVERED through October 7th.")[:2] == ("DELIVERED", "for free delivery")


# --- dates ----------------------------------------------------------------------------------------------------------
def test_end_dates_from_the_source_or_the_post():
    stated = post("Best Buy Techtober Headphones Deals: Up to 68% off",
                  expires_at=datetime(2026, 10, 12, 2, 59, tzinfo=timezone(timedelta(hours=-4))), expires_stated=True)
    assert sale_dates(stated, NOW)[1] == datetime(2026, 10, 12, 2, 59, tzinfo=timezone(timedelta(hours=-4)))
    hip = post("Kohl's Today-Only Deals", "Through October 8th, Kohl's Deal Days is bringing four huge days", source="hip2save")
    assert sale_dates(hip, NOW)[1] == datetime(2026, 10, 8, 23, 59, 59, tzinfo=CT)
    ended = post("Best Buy Labor Day Sale: Up to 70% off", "This sale ends September 7.",
                 posted=datetime(2026, 9, 5, 3, 37, tzinfo=CT))
    assert sale_dates(ended, NOW)[1] == datetime(2026, 9, 7, 23, 59, 59, tzinfo=CT)
    sd = post("Select Tools Extra 22% Off", "Valid through 10/13/26 at 11:58pm CT, or while supplies last.", source="slickdeals")
    assert sale_dates(sd, NOW)[1].date().isoformat() == "2026-10-13"
    assert sale_dates(post("Woot Docking Stations Sale", "Today only, use the promo code"), NOW)[1].date() == NOW.date()
    assert sale_dates(post("Up to 75% Off Vans Sale", "While supplies last, hurry over to Zappos"), NOW)[1] is None


def test_what_is_shown_when():
    s = StoreSale(id="x", store="kohls", store_name="Kohl's", title="t", name="n", offer="o", badge="b",
                  posted_at=NOW - timedelta(days=2), ends_at=NOW + timedelta(days=1))
    assert live_reason(s, NOW) == ""
    assert live_reason(s, NOW + timedelta(days=2)) == "sale: ended"
    undated = StoreSale(id="y", store="", store_name="X", title="t", name="n", offer="o", badge="b",
                        posted_at=NOW - timedelta(days=8))
    assert live_reason(undated, NOW) == "sale: no end date and posted over 7 days ago"
    old = StoreSale(id="z", store="", store_name="X", title="t", name="n", offer="o", badge="b",
                    posted_at=NOW - timedelta(days=40), ends_at=NOW + timedelta(days=80))
    assert live_reason(old, NOW) == "sale: posted over 30 days ago"       # evergreen coupon posts


# --- names, industries, duplicates ------------------------------------------------------------------------------------
def test_sale_names_drop_the_store_the_offer_and_the_asides():
    kohls = by_key()["kohls"]
    assert sale_name("Kohl's Deal Days Shoe Sale: Up to 60% off + extra 25% off + free shipping", kohls, "Kohl's") == \
        "Deal Days Shoe Sale"
    assert sale_name("LEGO Deal Days Event at Kohl's: 40% off everything + free shipping", kohls, "Kohl's") == \
        "LEGO Deal Days Event"
    assert sale_name("WOW! Up to 85% Off Kohl's Clearance Clothing & Shoes + FREE Shipping", kohls, "Kohl's") == \
        "Clearance Clothing & Shoes"
    assert sale_name("EXTRA 50% Off GAP Factory + Free Shipping | Styles from $2.99", by_key()["gapfactory"],
                     "Gap Factory") == "Sale"
    assert sale_name("OVER 60% Off Baublebar Jewelry + Free Shipping for Prime Members", by_key()["amazon"],
                     "Amazon") == "Baublebar Jewelry"


def _run_one(p):
    excluded = Counter()
    return StoreSales(None, None).sale(p, NOW, excluded), excluded


KOHLS_TEXT = ("Kohl's Deal Days event is now live with the promo code \"TAKE25\" taking an extra 25% off nearly everything "
              "across the store. The coupon applies to thousands of already-discounted items, including brands like "
              "Sephora, Levi's, Nike, and Samsonite, with prices on things like bath towels starting under $2. The sale "
              "ends on October 8.")


def test_a_store_wide_event_counts_for_the_goods_its_post_names():
    s, _ = _run_one(post("Kohl's Deal Days Sale: Up to 60% off + extra 25% off + free shipping", KOHLS_TEXT,
                         seller="Kohl's", category="Clothing & Accessories"))
    assert s.store == "kohls" and s.code == "TAKE25" and s.industry_rule == "a store-wide event: the goods its post names"
    assert {"fashion", "home"} <= set(s.industries) <= set(by_key()["kohls"].sells)
    bare, _ = _run_one(post("Kohl's Deal Days Sale: Up to 60% off + extra 25% off", "", seller="Kohl's"))
    assert bare.industries == ["fashion", "home"]                     # it names nothing: the store's main line
    # a store that sells everything: only what the post names (run 1 filed this under Pets and Auto)
    costco, _ = _run_one(post("Costco Member Appreciation Deals: Up to $1,200 off + free shipping w/ select items",
                              "Costco's Member Appreciation sale spans electronics, furniture, and gift cards. A Dell 15.6\" "
                              "touchscreen laptop is $699. Members will also find savings on robot vacuums and mattresses.",
                              seller="Costco", category="Home & Garden"))
    assert "pets" not in costco.industries and "auto" not in costco.industries and {"tech", "home"} <= set(costco.industries)
    lego, _ = _run_one(post("LEGO Deal Days Event at Kohl's: 40% off everything + free shipping", seller="Kohl's",
                            category="Toys & Hobbies"))
    assert lego.industries == ["toys"] and "sitewide" not in lego.conditions      # everything LEGO, not the store
    brand, _ = _run_one(post("Harry's Prime Big Deals at Amazon: Up to 43% off + free shipping", seller="Amazon",
                             category="Shaving & Grooming"))
    assert brand.industries == ["beauty"]


def test_a_store_the_registry_doesnt_know_must_say_it_ships():
    s, _ = _run_one(post("High Test Gummies Sitewide Sale: Extra 20% off + free shipping w/ $50", seller="High Test Gummies",
                         category="Supplements"))
    assert s and s.store == "" and s.store_name == "High Test Gummies"
    none, why = _run_one(post("Great Clips Haircut Coupon: $5 off", seller="Great Clips"))
    assert none is None and why["not a store sale: a local service"] == 1


def test_the_same_sale_posted_twice_is_one_card():
    def sale(source, title, name):
        return StoreSale(id=f"{source}:{name}", store="kohls", store_name="Kohl's", title=title, name=name,
                         offer="Up to 60% off", badge="Up to 60%", source=source, ends_at=NOW + timedelta(days=2),
                         posted_at=NOW)
    excluded = Counter()
    kept = dedupe([sale("Hip2Save", "Kohl's Deal Days: Up to 60% Off", "Deal Days"),
                   sale("dealnews", "Kohl's Deal Days Sale: Up to 60% off", "Deal Days Sale"),
                   sale("dealnews", "Kohl's Shoe Sale: Up to 60% off", "Shoe Sale")], excluded)
    assert [k.name for k in kept] == ["Deal Days Sale", "Shoe Sale"] and kept[0].also_posted[0]["source"] == "Hip2Save"
    assert excluded["sale: same sale posted elsewhere"] == 1


def test_select_and_payload_filter_by_industry_and_time():
    a = StoreSale(id="a", store="kohls", store_name="Kohl's", title="t", name="n", offer="o", badge="b",
                  industries=["fashion"], posted_at=NOW, ends_at=NOW + timedelta(hours=1), score=10)
    b = StoreSale(id="b", store="bestbuy", store_name="Best Buy", title="t", name="n", offer="o", badge="b",
                  industries=["tech"], posted_at=NOW, score=30)
    res = SalesResult(sales=[a, b])
    shown, excluded = select(res, ["fashion", "tech"], NOW)
    assert [s.id for s in shown] == ["b", "a"]
    shown, excluded = select(res, ["fashion"], NOW + timedelta(hours=2))
    assert shown == [] and excluded["sale: ended"] == 1 and excluded["sale: other industry"] == 1
    out = to_payload(res, ["tech"], NOW)
    assert [s["id"] for s in out["sales"]] == ["b"] and out["counts"] == {"sales": 1, "stores": 1}
    assert out["sales"][0]["kind"] == "sale" and out["stores"]["bestbuy"]["name"] == "Best Buy"


def test_a_range_later_in_the_post_does_not_beat_the_sales_own_end():
    p = post("Kohl's Today-Only Deals: Up to 60% Off + RARE Free Shipping", "Through October 8th, Kohl's Deal Days is "
             "here. Plus, earn $15 Kohl's Cash for every $50 spent, redeemable 10/9-10/19.", source="hip2save")
    start, end, how = sale_dates(p, NOW)
    assert start is None and end.date().isoformat() == "2026-10-08" and how == "the post says “Through October 8th”"
    titled = post("Kohl's Deal Days Sale Is Back Oct. 5-8: Get 25% Off Plus Kohl's Cash", "", source="kcl")
    assert sale_dates(titled, NOW)[1].date().isoformat() == "2026-10-08"


def test_tech_deals_are_not_a_store_wide_event():
    from slomp.sales import is_store_event
    assert is_store_event("Deal Days Sale") and is_store_event("Star Deals Week") and is_store_event("Friends & Family Sale")
    assert not is_store_event("Tech Deals") and not is_store_event("Harry's Prime Big Deals")


def test_judged_industry_slips_in_run_1():
    from slomp import industries as ind
    assert ind.from_text("OVER 50% Off Highly Rated Nutramax Cosequin Supplements on Amazon").industries == ["pets"]
    assert ind.from_text("Up to 40% Off ZURU My Mini Baby Sets w/ Amazon Prime").industries == ["toys"]
    wayfair, _ = _run_one(post("Life-Size Horror Characters Cardboard Standups at Wayfair: Up to 25% off + free shipping",
                               seller="Wayfair", category="Party Supplies"))
    assert wayfair.industries == ["home"]                  # the post's category is outside Wayfair's line: its own line


def test_judged_slips_in_run_2():
    # one bottle at one price, whatever the title's plural says
    cosequin = post("OVER 50% Off Highly Rated Nutramax Cosequin Supplements on Amazon",
                    "Head over to Amazon where you can score a 132-count bottle of Nutramax Cosequin Joint Supplement for "
                    "Dogs for just $15.71 shipped when you clip the digital coupon and opt to Subscribe & Save! Nutramax "
                    "Cosequin Joint Supplement for Dogs 132-Count $34.91", source="hip2save", deal_type="")
    assert not_a_sale(cosequin, parse_offer(cosequin.title)) == "one product, not a sale"
    handbags = post("40% Off Target Handbags = Styles from $9", "Target is offering 40% off handbags! Crossbody $10.80 "
                    "(reg. $18), Tote $14.99 (reg. $24.99), Wallet $9 (reg. $15)", source="hip2save", deal_type="")
    assert not_a_sale(handbags, parse_offer(handbags.title)) == ""
    # an unnamed store-wide event counts for the store's main line, not every department
    gap, _ = _run_one(post("EXTRA 50% Off GAP Factory + Free Shipping | Styles from $2.99", "Through October 7th, head to "
                           "GAP Factory where you can score an extra 50% off clearance!", source="hip2save",
                           feed_industries=["baby", "fashion"]))
    assert gap.industries == ["fashion"]
    kohls, _ = _run_one(post("Kohl's Today-Only Deals: Up to 60% Off + RARE Free Shipping & Earn Kohl's Cash!",
                             "Through October 8th, Kohl's Deal Days is bringing four huge days packed with up to 60% off.",
                             source="hip2save", feed_industries=["home", "baby", "fashion"]))
    assert kohls.industries == ["fashion", "home"]


def test_a_brands_shop_on_a_marketplace_is_the_marketplace():
    # run 3: "Up to 60% Off Crocs" at "the official Crocs eBay Store" was shown as a Crocs sale
    p = post("Up to 60% Off Crocs + FREE Shipping | Styles from $16.99 Shipped", "For a limited time, hop over to the "
             "official Crocs eBay Store, where they are offering HOT deals on select Crocs + free shipping!",
             source="hip2save", deal_type="")
    assert find_store(p)[0].key == "ebay"
    alone = post("Up to 65% Off Crocs + FREE Shipping = Styles from $17.50", "Through October 7th, RUN to Crocs.com",
                 source="hip2save", deal_type="")
    assert find_store(alone)[0].key == "crocs"


def test_a_deal_site_is_not_a_store_and_one_chair_is_not_a_sale():
    # run 3's judge noticed dealnews' own roundup listed under the store "DealNews"
    roundup = post("The Best Amazon Prime Big Deal Days Deals: Up to 80% off + free shipping w/ Prime",
                   "Amazon's Prime Big Deal Days event is here! Prime members can take advantage of savings.",
                   seller="DealNews")
    assert find_store(roundup)[0].key == "amazon"
    s, _ = _run_one(roundup)
    assert s.store == "amazon" and s.store_name == "Amazon"
    chair = post("Welax S3 Ergonomic Office Chair: $45 OFF + free shipping", seller="Welax")
    assert not_a_sale(chair, parse_offer(chair.title)) == "one product, not a sale"
    ladders = post("Lowe's Ladders & Scaffolding Deals: Up to $100 off + free shipping", seller="Lowe's")
    assert not_a_sale(ladders, parse_offer(ladders.title)) == ""


def test_several_items_priced_in_whole_dollars_are_a_sale():
    p = post("OVER 60% Off Baublebar Jewelry + Free Shipping for Prime Members", "Through October 7th, hop on over to "
             "Amazon where Prime members can score deals on Baublebar jewelry! Earrings Only $12 shipped (reg. $44)! "
             "Charm Necklace Only $15 shipped (reg. $48)!", source="hip2save", deal_type="")
    assert not_a_sale(p, parse_offer(p.title)) == ""
