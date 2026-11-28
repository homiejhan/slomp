"""Online stores' sales (slomp/sales.py, slomp/stores_online.py): which posts are sales, at which store, the offer,
the code, the dates and what is shown when. Titles and texts are real posts read on Oct 6, 2026."""
from collections import Counter
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from slomp import industries as ind
from slomp.models import StoreSale
from slomp.sales import (SalesResult, StoreSales, code_of, conditions_of, dedupe, is_store_event, live_reason, not_a_sale,
                         offer_text, parse_offer, rank_pct, sale_dates, sale_name, select, shipping_of, to_payload)
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


# --- the manual comparison of Oct 13, 2026 --------------------------------------------------------------------------
# What a manual, cross-checked search of that week's sales showed Slomp missing (docs/VERIFICATION.md). The dealnews
# titles are as the posts' URLs give them; the rest are written the way the deal sites write theirs.
def test_a_code_after_a_capitalized_cue_is_read():
    # Slickdeals and Hip2Save write "w/ Code", "Promo Code"; only "code" was read, so these codes were lost
    assert code_of("Lands' End: 50% Off Sitewide + Extra 65% Off Sale & Clearance w/ Code HAYRIDE50", "",
                   store_named("Lands' End"))[0] == "HAYRIDE50"
    assert code_of("Extra $10 Off $50 Kohl's Home Purchase w/ Promo Code 10HOME", "", store_named("Kohl's"))[0] == "10HOME"
    assert code_of("Nike: Extra 25% Off Sale Styles", "Use Code: EXTRA25 at checkout.", store_named("Nike"))[0] == "EXTRA25"
    # ...and the capitals around it are still not codes
    assert code_of("Kohl's: Extra 30% Off w/ Promo Code TODAY ONLY", "", store_named("Kohl's"))[0] == ""
    assert code_of("Gap: 40% Off w/ Code At Checkout", "", store_named("Gap"))[0] == ""


def test_instant_credits_and_savings_are_dollars_off():
    assert offer("Samsung Monitor Deals: Up to $150 in instant credits + free shipping") == \
        ("Up to $150 off", "Up to $150", True)
    assert offer("LG OLED TV Sale: $500 instant savings") == ("$500 off", "$500 off", True)
    assert offer("Samsung TV Deals: Save up to $1,000 + free shipping") == ("Up to $1,000 off", "Up to $1,000", True)
    o = parse_offer("Samsung Monitor Deals: Up to $150 in instant credits + free shipping")
    assert not_a_sale(post("Samsung Monitor Deals: Up to $150 in instant credits + free shipping", seller="Samsung"), o) == ""


def test_a_sale_named_for_a_holiday_is_the_whole_stores():
    # "Columbus Day" read as goods left the sale without an industry when the post's category named none
    s = StoreSales(None, None).sale(post("Macy's Columbus Day Sale: Up to 60% off + extra 20% off w/ code + free shipping",
                                         seller="Macy's"), NOW, Counter())
    assert s is not None and s.industries and set(s.industries) <= set(store_named("Macy's").sells)


def test_this_weeks_dealnews_sales_keep_their_ends_and_codes():
    now = datetime(2026, 10, 13, 18, 0, tzinfo=CT)
    posted = datetime(2026, 10, 12, 8, 0, tzinfo=CT)
    cases = [
        ("Wayfair Holiday Deal Week Sale: Up to 80% off + free shipping w/ $35", "Wayfair", "Home & Garden",
         "This deal ends October 18.", "Up to 80% off", "", "2026-10-18"),
        ("adidas Fall Favorites Sale: Up to 50% off + extra 30% off + Free shipping", "adidas", "Clothing & Accessories",
         'Coupon code "FALL" takes an extra 30% off eligible items. This deal ends October 19.',
         "Up to 50% off + extra 30% off", "FALL", "2026-10-19"),
        ("Michael Kors Outlet Extra Savings Sale: Up to 85% off + extra 10% off + free shipping", "Michael Kors",
         "Clothing & Accessories", 'Coupon code "EXTRA10" takes an extra 10% off. This deal ends October 15.',
         "Up to 85% off + extra 10% off", "EXTRA10", "2026-10-15"),
    ]
    for title, seller, cat, text, want, code, end in cases:
        s = StoreSales(None, None).sale(post(title, text, seller=seller, category=cat, posted=posted), now, Counter())
        assert (s.offer, s.code, s.ends_at.date().isoformat()) == (want, code, end), title


def test_an_end_given_as_a_weekday_or_with_a_time_is_read():
    # an end the post states but Slomp didn't read is shown as no end, for 7 days after the post (S-END fails it)
    now = datetime(2026, 10, 14, 12, 0, tzinfo=CT)                  # a Wednesday
    def end(text):
        _, e, _ = sale_dates(post("Up to 50% Off Fall Sale", text, source="hip2save",
                                  posted=datetime(2026, 10, 14, 8, 0, tzinfo=CT)), now)
        return e and e.date().isoformat()
    assert end("Sale runs through Sunday.") == "2026-10-18"
    assert end("Hurry, ends Monday!") == "2026-10-19"
    assert end("Ends Wednesday.") == "2026-10-14"                   # the day it was posted
    assert end("Valid through Sunday, 10/19.") == "2026-10-19"
    assert end("Ends at 11:59pm PT on 10/19.") == "2026-10-19"
    assert end("New deals drop Monday through Friday.") is None     # a span of weekdays, not an end


def test_a_quoted_code_is_a_code_and_a_percent_off_an_order_keeps_its_size():
    # Oct 14, 2026 (dealnews): Old Navy's code is the word EXTRA, which a title's capitals never are
    assert code_of("Old Navy Clearance Sale: Up to 87% off + extra 20% off",
                   'Code "EXTRA" takes an extra 20% off. The coupon expires on October 15.', store_named("Old Navy"))[0] == "EXTRA"
    assert code_of("Kohl's: Extra 30% Off w/ Promo Code TODAY ONLY", "", store_named("Kohl's"))[0] == ""
    o = parse_offer("New Balance Sale: 25% off $125 + free shipping")
    assert offer_text(o)[:2] == ("25% off $125+", "25% off") and o.min_spend == 125
    assert conditions_of(o, "New Balance Sale: 25% off $125 + free shipping", "") == ["on orders of $125+"]


def test_more_sale_events_and_goods_are_named():
    # "Macy's Biggest Fall Sale Event", Woot's "Markdown Mania Clearance": the whole store's (Oct 14, 2026, dealnews)
    assert is_store_event("Biggest Fall Sale Event") and is_store_event("Markdown Mania Clearance")
    assert ind.from_text("Home & Kitchen Deals Under $30 Sale at Woot: Up to 77% off").industries == ["home"]
    assert ind.from_text("Fall Gardening Sale at Woot: Up to 76% off").industries == ["home"]
    assert ind.from_text("Glad Kitchen Bags 80-ct").industries == ["grocery"]


def test_a_coupon_in_quotes_a_prime_shipping_line_and_same_day_pickup():
    # Oct 15, 2026: dealnews' Under Armour post names its codes as 'The coupon "OCT40"'
    assert code_of("Under Armour Men's Shoe Outlet: Extra 40% + 10% off",
                   'The coupon "OCT40" cuts an extra 40% off, and then "EXTRA10" takes another 10% off.',
                   store_named("Under Armour"))[0] == "OCT40"
    assert code_of("X Sale: 20% off", "Clip the coupon on the product page.", None)[0] == ""
    # Hip2Save's Woot posts end "+ Free Shipping for Amazon Prime Members": a membership, not the store
    woot = post("Up to 75% Off Skechers Shoes + Free Shipping for Amazon Prime Members",
                "Hop over to Woot.com where they're offering up to 75% off Skechers.", source="hip2save", deal_type="")
    assert find_store(woot)[0].key == "woot"
    assert find_store(post("Up to 50% Off Amazon Basics + Free Shipping for Prime Members", source="hip2save",
                           deal_type=""))[0].key == "amazon"
    t = "CVS Photo Custom Canvas Deal: 70% off + same-day pickup"
    assert not_a_sale(post(t), parse_offer(t)) == "pickup only"


def test_halloween_decor_is_home():
    assert ind.from_text("Target Halloween Decor Sale: Up to 40% off").industries == ["home"]
    assert ind.from_text("Halloween Costumes for Kids").industries == ["toys"]


# --- Black Friday week (docs/VERIFICATION.md, "A seventh time"). Titles and texts are posts read on Nov 22, 2026. ----
BF_NOW = datetime(2026, 11, 22, 1, 0, tzinfo=CT)


def bf(title, text="", source="hip2save", days_ago=0.2, **kw):
    kw.setdefault("deal_type", "")
    return post(title, text, source=source, posted=BF_NOW - timedelta(days=days_ago), **kw)


def one(p, now=BF_NOW):
    ex = Counter()
    return StoreSales(None, None).sale(p, now, ex), ", ".join(ex)


def test_an_offer_after_the_sales_name_is_read_as_the_most_it_gives():
    assert offer("Nordstrom Black Friday Sale is LIVE | Up to 75% Off Baublebar, LEGO, UGG & More")[0] == "Up to 75% off"
    assert offer("40% Off Target Handbags = Styles from $9")[0] == "40% off"             # the offer leads: no change
    o = parse_offer("Target’s Black Friday Deals Start 11/22 (50% Off Thousands of Gifts!)")
    assert (o.pct, o.upto) == (None, 50)
    o = parse_offer("Walgreens Black Friday Sneak Peek | $5 Throw Blankets, 50% Off Gift Sets & More")
    assert (o.pct, o.upto) == (None, 50)
    # a list of highlights after a colon: the percent is one item's
    o = parse_offer("Michaels Black Friday Sale is Live: FREE Poinsettias, BOGO Offers, 70% Off Trees & More!")
    assert (o.pct, o.upto, o.bogo) == (None, 70, "buy one, get one deals")
    assert parse_offer("Kohl's Toy Sale: 40% off toys, games & more").pct == 40          # the list's first item: the sale's
    assert not parse_offer("KitchenAid Mixer Just $199 Shipped | 50% Off!").any           # names no sale: an aside stays one


def test_a_stores_event_named_for_a_day_is_shown_without_a_stated_discount():
    s, _ = one(bf("Kohl’s Black Friday Sale Starts at 12am CT!", "The Kohl's Black Friday deals are live now!", days_ago=0.1))
    assert (s.store, s.name, s.offer, s.badge, s.score) == ("kohls", "Black Friday Sale", "Sale event, no discount stated", "Sale event", 0)
    assert s.starts_at.date().isoformat() == "2026-11-22" and s.event == "Black Friday"
    assert s.event_ends_at == datetime(2026, 11, 27, 23, 59, 59, tzinfo=CT) and not s.ends_at
    s, _ = one(bf("Want a Peek at Walmart’s Black Friday Deals? Get Ready to Shop on 11/23!"))
    assert (s.store, s.name, s.starts_at.date().isoformat()) == ("walmart", "Black Friday Deals", "2026-11-23")
    s, _ = one(bf("Macy's Black Friday Small Appliance Deals for Under $50 + free shipping w/ $39", source="dealnews",
                  seller="Macy's", deal_type="sale"))
    assert (s.name, s.offer, s.badge, s.badge_soft) == ("Black Friday Small Appliance Deals", "Under $50", "Under $50", True)
    # a day's name on something that is no sale of the store's states no discount
    for title, seller in (("FREE Lowe’s Black Friday Buckets November 27th (Will You Get the One w/ $2,000 in Prizes?!)", ""),
                          ("Nintendo Switch 2 + Mario Kart World Bundle Black Friday Deal", "Nintendo"),
                          ("Walmart Fall Savings Are Here", "")):
        s, why = one(bf(title, seller=seller, source="dealnews" if seller else "hip2save"))
        assert s is None and why == "not a store sale: no discount stated", title


def test_the_posts_own_sentence_gives_the_offer_a_title_leaves_out():
    s, _ = one(bf("Crocs Black Friday Sale | Cozy Clogs & Holiday Styles from $18",
                  "Through November 29th, head over to Crocs.com where you can score up to 60% off select styles during "
                  "their Black Friday sale! Plus, shipping is free on orders of $55."))
    assert (s.store_name, s.name, s.offer) == ("Crocs", "Black Friday Sale", "Up to 60% off")
    assert s.ends_at.date().isoformat() == "2026-11-29" and "head over to Crocs.com" in s.offer_how
    # a plain percent in that sentence is the most the sale gives, unless it is on everything
    s, _ = one(bf("Old Navy Black Friday Sale is Live", "Hop on over to Old Navy where you can score 50% off pajamas today!"))
    assert (s.pct, s.upto) == (None, 50)
    s, _ = one(bf("Old Navy Black Friday Sale is Live", "Hop on over to Old Navy where you can score 50% off everything!"))
    assert (s.pct, s.upto) == (50, None)


def test_a_sale_named_for_a_day_lasts_through_it_when_no_end_is_stated():
    belk = bf("Belk Black Friday Sale: Up to 80% off + free shipping w/ $99", source="dealnews", seller="Belk",
              deal_type="sale", days_ago=8)
    s, _ = one(belk)
    assert s.event_ends_at == datetime(2026, 11, 27, 23, 59, 59, tzinfo=CT)
    assert live_reason(s, datetime(2026, 11, 27, 20, 0, tzinfo=CT)) == ""
    assert live_reason(s, datetime(2026, 11, 28, 9, 0, tzinfo=CT)) == "sale: no end date and posted over 7 days ago"
    # the wave before the day says it ends before it, not when: the seven days stand
    s, why = one(bf("Belk Early Black Friday Sale: Up to 60% off + free shipping w/ $99", source="dealnews", seller="Belk",
                    deal_type="sale", days_ago=12))
    assert s is None and why == "sale: no end date and posted over 7 days ago"
    # a stated end still wins
    s, _ = one(bf("adidas Black Friday Sale: Up to 60% off", "Ends November 24.", source="dealnews", seller="adidas",
                  deal_type="sale", days_ago=3))
    assert s.ends_at.date().isoformat() == "2026-11-24" and s.event_ends_at is None and s.event == "Black Friday"


def test_what_comes_with_a_sale_is_not_what_is_on_sale():
    samsung = bf("Samsung Black Friday Sale 2026: Up to 36% off + trade-in offers + free delivery", source="dealnews",
                 seller="Samsung", deal_type="sale")
    assert not_a_sale(samsung, parse_offer(samsung.title)) == ""
    cabelas = bf("Cabela’s & Bass Pro Shops Black Friday Ad Preview | Up to 50% Off + FREE Gift Card Giveaway!")
    assert not_a_sale(cabelas, parse_offer(cabelas.title)) == ""
    trade = bf("Samsung Galaxy Trade-In Deals: Up to $900 off", source="dealnews", seller="Samsung", deal_type="sale")
    assert not_a_sale(trade, parse_offer(trade.title)) == "a trade-in"
    vpn = bf("NordVPN Black Friday Deals: Up to 78% off + free shipping", source="dealnews", seller="NordVPN", deal_type="sale")
    assert not_a_sale(vpn, parse_offer(vpn.title)) == "digital, not shipped"


def test_a_post_that_prices_one_thing_is_one_product():
    p = bf("Glitzhome 18\" Frosty Santa: 60% Off Modern Holiday Decor",
           "Give your mantel white-and-silver elegance with Glitzhome's 18\" porcelain-face Frosty Santa, now $38.80 at "
           "Belk, about 60% off the $97 price.", source="theinventory")
    assert not_a_sale(p, parse_offer(p.title)) == "one product, not a sale"


def test_a_headline_says_when_a_sale_starts_and_that_this_is_its_last_day():
    starts, ends, _ = sale_dates(bf("New CVS Black Friday Deals Start 11/22 (+ Select Offers Already Live!)"), BF_NOW)
    assert starts.date().isoformat() == "2026-11-22" and ends is None
    for title in ("Kohl’s Early Black Friday Deals End TONIGHT = Big Savings on Cuisinart, Shark, & More!",
                  "Under Armour Black Friday Warm Up Sale = Up to 60% Off Hoodies – Last Day!"):
        _, ends, how = sale_dates(bf(title, days_ago=0.5), BF_NOW)
        assert ends.date().isoformat() == "2026-11-21" and how == "the post says “today only”", title
    # "last day" in a body is some other day's ("the last day to order for Christmas delivery")
    _, ends, _ = sale_dates(bf("Macy's Black Friday Sale: Up to 60% off", "The last day to order for Christmas delivery is December 20."), BF_NOW)
    assert ends is None
    assert sale_name("Lowe's Live Christmas Trees Sale: Up to 40% off", None, "Lowe's") == "Live Christmas Trees Sale"
    assert sale_name("Shop adidas Black Friday Sale Now to Score 60% Off + FREE Shipping", None, "adidas") == "Black Friday Sale"
    kohls = by_key()["kohls"]
    assert sale_name("Kohl’s Black Friday Sale Starts at 12am CT!", kohls, "Kohl's") == "Black Friday Sale"
    assert sale_name("Michaels Black Friday Sale is Live: FREE Poinsettias, BOGO Offers, 70% Off Trees & More!", None,
                     "Michaels") == "Black Friday Sale"
    assert sale_name("QVC Black Friday Sale for Up to 42% off + extra $20 off $40 + free shipping", None, "QVC") == "Black Friday Sale"
    assert sale_name("Macy's Black Friday Men's Deals: New deals added, up to 80% off + free shipping w/ $39", None,
                     "Macy's") == "Black Friday Men's Deals"


def test_an_event_with_no_discount_yields_to_the_stores_sale_for_that_day_that_states_one():
    a, _ = one(bf("Amazon’s Black Friday Sale Is Live (Score Huge Savings on Tech, Clothes, Beauty, & More!)"))
    b, _ = one(bf("Amazon Black Friday Sale 2026: Up to 70% off + free shipping w/ Prime", source="dealnews",
                  seller="Amazon", deal_type="sale"))
    c, _ = one(bf("Kohl’s Black Friday Sale Starts at 12am CT!"))
    ex = Counter()
    kept = dedupe([a, b, c], ex)
    assert [s.id for s in kept] == [b.id, c.id] and ex["sale: same sale posted elsewhere"] == 1
    assert b.also_posted[0]["source"] == "Hip2Save"


def test_the_wave_before_a_day_and_the_days_own_sale_are_two_sales():
    early, _ = one(bf("Last Chance: Target Early Black Friday Deals | Up to 50% Off Stanley, Boots, & More", days_ago=0.6))
    main, _ = one(bf("Target’s Black Friday Deals Start 11/22 (50% Off Thousands of Gifts!)"))
    assert (early.name, main.name, early.badge, main.badge) == ("Early Black Friday Deals", "Black Friday Deals", "Up to 50%", "Up to 50%")
    assert main.industries and main.starts_at.date().isoformat() == "2026-11-22"
    assert len(dedupe([early, main], Counter())) == 2


def test_sales_of_different_things_named_for_one_day_are_different_sales():
    # run 180, Nov 27, 2026: 103 sales stood under another sale's card, joined by "Black Friday" in their names
    from slomp.sales import sale_said

    def sales_at(store_name, *names, badge="Up to 40%", ends=BF_NOW + timedelta(days=5), source="dealnews"):
        return [StoreSale(id=f"{source}:{store_name}:{n}", store=store_name.lower(), store_name=store_name, title=f"{n}: {badge}", name=n,
                          offer=f"{badge} off", badge=badge, upto=40, source=source, ends_at=ends, posted_at=BF_NOW) for n in names]
    # five brands' sales at one store, the same badge and end
    brands = sales_at("Amazon", "GearWrench Black Friday Deals", "Gillette Black Friday Deals", "Vitamix Black Friday Deals",
                      "Ninja Black Friday Deals", "Dyson Black Friday Deals")
    ex = Counter()
    assert len(dedupe(brands, ex)) == 5 and not ex
    # the store's own sale for the day is not its category sales, nor they one another
    fan = sales_at("Fanatics", "Black Friday Sale", "Black Friday NFL Jerseys Sale", "Nike Black Friday Deals", "MLB Black Friday Sale",
                   "Black Friday College Gear Sale")
    assert len(dedupe(fan, Counter())) == 5
    assert len(dedupe(sales_at("adidas", "Black Friday Men's Accessories Deals", "Black Friday Men's Jacket Deals"), Counter())) == 2
    assert len(dedupe(sales_at("Best Buy", "Half-Price (or Better) Black Friday Appliance Deals", "Half-Price (or Better) Black Friday Phone Deals"),
                      Counter())) == 2
    # the same sale twice is still one: "Deals" for "Sale", the year, the store's own name, a plural, another order,
    # and the words a source dresses an event's name in, which name no goods (Hip2Save's "Target's BIG Black Friday
    # Sale Is LIVE" beside dealnews's "Target Black Friday Sale", run 180)
    for a, b in (("Black Friday Sale", "Black Friday Deals 2026"), ("Black Friday Sale", "Kohl's Black Friday Sale"),
                 ("Black Friday Sale", "Black Friday Event"), ("Black Friday Sale", "BIG Black Friday Sale"),
                 ("Black Friday Promo Code", "Best of Black Friday Deals"),
                 ("Black Friday Outerwear Deals", "Black Friday Outerwear Doorbusters"), ("Black Friday Toy Deals", "Black Friday Top 100 Toys Deals"),
                 ("Black Friday Cell Phone Sale", "Black Friday Cell Phones Deals"), ("Terrex Black Friday Sale", "Black Friday Terrex Deals"),
                 ("Black Friday Printing Deals", "Printing Black Friday Deals")):
        pair = sales_at("Kohl's", a) + sales_at("Kohl's", b, source="Hip2Save")
        ex = Counter()
        kept = dedupe(pair, ex)
        assert len(kept) == 1 and kept[0].source == "dealnews" and ex["sale: same sale posted elsewhere"] == 1, (a, b)
    # a sale named for another day is another sale, and so is the wave before a day
    assert len(dedupe(sales_at("Kohl's", "Black Friday Sale", "Cyber Monday Sale"), Counter())) == 2
    assert len(dedupe(sales_at("Kohl's", "Black Friday Sale", "Early Black Friday Sale"), Counter())) == 2
    assert len(dedupe(sales_at("eBay", "Early Black Friday Sale", "Anker Early Black Friday Deals"), Counter())) == 2
    # the day is when and the rest is what
    said = lambda name, store="Amazon": sale_said(sales_at(store, name)[0])                    # noqa: E731
    assert said("GearWrench Black Friday Deals") == (frozenset({"Black Friday"}), frozenset({"gearwrench"}))
    assert said("Amazon Black Friday Sale 2026") == (frozenset({"Black Friday"}), frozenset())
    assert said("Early Black Friday Deals") == said("Black Friday Sale") and said("Deal Days Shoe Sale")[0] == frozenset()
    assert said("Black Friday & Cyber Monday Deals")[0] == frozenset({"Black Friday", "Cyber Monday"})
    # the same night written in two time zones is one end day, for a store's sale as for any
    from zoneinfo import ZoneInfo
    ET = ZoneInfo("America/New_York")
    two = sales_at("Target", "Christmas Lights Sale", badge="BOGO 50%", ends=datetime(2026, 11, 30, 23, 59, tzinfo=ET)) + \
        sales_at("Target", "Christmas Lights Sale", badge="BOGO 50%", ends=datetime(2026, 12, 1, 3, 0, tzinfo=ET), source="Hip2Save")
    assert len(dedupe(two, Counter())) == 1
    apart = sales_at("Macy's", "Cole Haan Black Friday Men's Deals", ends=datetime(2026, 11, 28, 23, 59, tzinfo=ET)) + \
        sales_at("Macy's", "Nike Black Friday Deals", ends=datetime(2026, 11, 29, 3, 0, tzinfo=ET))
    assert len(dedupe(apart, Counter())) == 2


def test_an_events_headline_goes_under_the_stores_own_sale_for_the_day():
    live, _ = one(bf("Amazon’s Black Friday Sale Is Live (Score Huge Savings on Tech, Clothes, Beauty, & More!)"))
    brand, _ = one(bf("GearWrench Black Friday Deals at Amazon: Up to 40% off + free shipping w/ Prime", source="dealnews",
                      seller="Amazon", deal_type="sale", days_ago=0.9, category="Hand Tools"))
    own, _ = one(bf("Amazon Black Friday Sale 2026: Up to 70% off + free shipping w/ Prime", source="dealnews", seller="Amazon",
                    deal_type="sale"))
    assert live and brand and own and (brand.name, own.name) == ("GearWrench Black Friday Deals", "Black Friday Sale")
    kept = dedupe([live, brand, own], Counter())
    assert sorted(s.id for s in kept) == sorted([brand.id, own.id])
    assert [p["source"] for p in own.also_posted] == ["Hip2Save"] and not brand.also_posted
    # with no sale of the store's own for the day, the headline goes under the first that states a discount, as before
    live.also_posted, brand.also_posted = [], []
    assert [s.id for s in dedupe([live, brand], Counter())] == [brand.id] and brand.also_posted
    # of the store's sales that name no goods, the plainest name is its own sale for the day
    for x in (live, brand, own):
        x.also_posted = []
    clearance, _ = one(bf("Amazon Black Friday Clearance: Up to 80% off + free shipping w/ Prime", source="dealnews", seller="Amazon",
                          deal_type="sale"))
    assert clearance and clearance.name == "Black Friday Clearance"
    kept = dedupe([live, clearance, brand, own], Counter())
    assert len(kept) == 3 and [p["source"] for p in own.also_posted] == ["Hip2Save"] and not clearance.also_posted
