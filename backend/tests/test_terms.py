"""Deal-terms parsing. Every case is a real Austin weekly-ad item (Sept 2026) checked against its printed ad image."""
import pytest

from plum.terms import bogo, clean, money, pack_lb, parse_terms, price_is_discount


def test_money_and_clean():
    assert money("$1,299.99") == 1299.99 and money(3.99) == 3.99 and money("3.99") == 3.99
    assert money("") is None and money("0") is None and money(None) is None and money(True) is None
    assert clean("Regular Fit\u200b\u200b Shirt*  ") == "Regular Fit Shirt"


def test_feed_backed_price_cut_reconstructs_the_regular_price():
    # Cabela's (retailer feed): $59.98, $30.01 off, 33% -> reg $89.99, as on cabelas.com
    t = parse_terms(price="59.98", pct=33.0, dollars=30.01, story="Footwear Deals")
    assert (t.price, t.was, t.pct_off, t.hedge, t.offer) == (59.98, 89.99, 33.3, "", "")
    # Best Buy: the feed's regular price wins; the rounded headline percent is recomputed from exact dollars
    t = parse_terms(price="248.99", pct=31.0, dollars=110.01, story="Headphones")
    assert (t.was, t.pct_off) == (359.0, 30.6)


def test_multi_buy_keeps_the_quantity():
    # CVS: "2/$8.00 or reg retail ea. WITH CARD": $4 each only when you buy two
    t = parse_terms(price="8.0", pre="2/", post="or reg retail ea. WITH CARD", feed=False)
    assert (t.price, t.quantity, t.unit_price) == (8.0, 2, 4.0)
    assert t.conditions == ("loyalty card", "buy 2") and t.offer.startswith("2 for $8.00")
    # Sprouts "2 FOR $6": no single-price alternative printed, so no "buy 2" requirement is invented
    t = parse_terms(price="6.0", pre="2 FOR")
    assert (t.quantity, t.unit_price, t.conditions) == (2, 3.0, ())


@pytest.mark.parametrize("story,expected_pct,needs", [
    ("Buy 1 get 1 50% OFF* WITH CARD", 25.0, "buy 2"),      # CVS: headline says 50, you save 25%
    ("BUY 3 GET 3 FREE", 50.0, "buy 6"),                    # Randalls
    ("BUY 2 GET 1 FREE**", 33.3, "buy 3"),                  # Dollar General
    ("Buy one get one free", 50.0, "buy 2"),
])
def test_bogo_counts_the_effective_saving(story, expected_pct, needs):
    t = parse_terms(story=story, pct=50.0, feed=False)
    assert t.pct_off == expected_pct and needs in t.conditions and t.was is None and t.price is None


def test_bogo_shorthand():
    assert bogo("B1G1 50%") == (1, 1, 50.0) and bogo("BOGO") == (1, 1, 100.0) and bogo("Buy 2 save") is None


def test_hedges():
    # H-E-B: "$6.97 lb. SAVE up to $1 per lb.": the saving is a ceiling, so no regular price is claimed
    t = parse_terms(price="6.97", post="lb.", story="SAVE up to $1 per lb.", pct=13.0, dollars=1.0, feed=False)
    assert (t.unit, t.hedge, t.was) == ("lb", "up to", None)
    assert parse_terms(price="5.0", pre="Starting at").hedge == "starting at"
    assert parse_terms(story="Up to 50% off", pct=50.0).hedge == "up to"


def test_compare_at_value_is_not_a_regular_price():
    # CVS: "Depart store value 103.00 You save 73.00"
    t = parse_terms(price="29.99", post="WITH CARD", story="Depart store value 103.00 You save 73.00", pct=71.0,
                    dollars=73.0, feed=False)
    assert t.hedge == "compare at" and "loyalty card" in t.conditions


def test_transcribed_saving_without_a_regular_price_is_hedged():
    # CVS So De La Renta: data says only "You save 76.00"; the printed ad compares to a department-store value
    t = parse_terms(price="24.99", post="WITH CARD", story="You save 76.00", pct=75.0, dollars=76.01, feed=False)
    assert (t.hedge, t.was, t.dollars_off) == ("no reference", None, 76.0)    # the ad's own $76.00, not 76.01
    # The same numbers from a retailer feed are trusted
    assert parse_terms(price="24.99", story="You save 76.00", pct=75.0, dollars=76.01).hedge == ""


def test_transcribed_saving_with_a_stated_regular_price_is_firm():
    # ALDI: "PRICE DROPS $4.29 Per Lb. Was $4.79"
    t = parse_terms(price="4.29", original="4.79", pre="PRICE DROPS", post="Per Lb.", pct=10.0, dollars=0.5, feed=False)
    assert (t.was, t.pct_off, t.unit, t.hedge, t.offer) == (4.79, 10.4, "lb", "", "PRICE DROPS")


def test_garbled_transcription_is_dropped():
    # Restaurant Depot avocado pulp: the ad says "$28.20 cs only, $2.35 lb"; the data says 2.8 vs 12.35 (77% off)
    t = parse_terms(price="2.8", original="12.35", post="cs only", pct=77.0, dollars=9.55, description="6/2 lb",
                    merchant="Restaurant Depot", feed=False)
    assert (t.was, t.pct_off, t.dollars_off, t.unit) == (None, None, None, "")
    assert t.conditions == ("full case only", "business membership")


def test_dollars_off_recorded_as_the_price():
    # Restaurant Depot: "10\" STICK BLENDER $50 OFF" arrives as price 50, 50% off
    t = parse_terms(price="50.0", story="$50 OFF", pct=50.0, dollars=50.0, feed=False)
    assert (t.price, t.dollars_off, t.pct_off) == (None, 50.0, None)
    assert price_is_discount(2.0, "", "/CS", "200 OFF/CS")                   # "200 OFF" = $2.00 off
    assert price_is_discount(5.0, "", "off", "")
    assert not price_is_discount(19.99, "", "", "$5 off")


def test_case_price_compared_with_a_per_lb_price_is_not_a_discount():
    # Restaurant Depot gyro kones: $4.62/lb, "original" $184.95 is the 40 lb case at the same rate
    t = parse_terms(price="4.62", original="184.95", post="lb", pct=98.0, dollars=180.33, description="40 lb 36280")
    assert (t.was, t.pct_off, t.dollars_off) == (None, None, None)
    assert pack_lb("6/2 lb 961072") == 12.0 and pack_lb("Jumbo Bag") is None


def test_conditions_and_fine_print():
    t = parse_terms(price="1.79", post="lb", disclaimer="Limit 10 lbs. Each", feed=False)
    assert t.conditions == ("limit 10 lb",)
    t = parse_terms(price="6.0", post="Final Price With Coupon", story="Save $4 with DG DIGITAL COUPONS", pct=40.0,
                    dollars=4.0)
    assert (t.was, "coupon" in t.conditions) == (10.0, True)
    t = parse_terms(price="15.49", pre="Online Price", pct=18.0, dollars=3.5, merchant="Costco ")
    assert t.conditions == ("online price", "membership")                  # "Costco " has a trailing space in the feed
    t = parse_terms(price="11.99", post="ea", story="10% OFF When You Buy 6 or More", feed=False)
    assert "buy 6+" in t.conditions and t.hedge == "no reference"
    assert "members only" in parse_terms(story="15% off, MyLowe's Pro Rewards Members Only Spend $2,500 Save $200",
                                         pct=15.0).conditions
    assert parse_terms(story="15% off, Spend $2,500 Save $200", pct=15.0).dollars_off is None   # a reward, not a price cut


def test_bundle_and_price_only_in_the_story():
    t = parse_terms(price="5.0", pre="BUNDLE", story="YOU SAVE $1.78", pct=26.0, dollars=1.78, feed=False)
    assert "bundle" in t.conditions and t.hedge == "no reference"
    assert parse_terms(story="$3499.99** ea.").price == 3499.99
    assert parse_terms(story="$2 off 1").price is None                     # "$2 off" is a saving, not a $2 price
