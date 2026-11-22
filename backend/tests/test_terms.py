from slomp.terms import ad_terms, bogo_of, is_storewide, post_reference, title_price


def test_feed_item_saving_is_firm():
    t = ad_terms({"current_price": "999.99", "dollars_off": 200, "percent_off": 17}, feed=True)
    assert (t.price, t.regular, t.basis) == (999.99, 1199.99, "store_regular")
    assert t.pct == 16.7


def test_print_ad_saving_without_regular_price_is_only_claimed():
    # v0.2: CVS "You save 76.00" turned out to be a department-store compare-at value
    t = ad_terms({"current_price": "24.99", "dollars_off": 76}, feed=False)
    assert t.basis == "claimed_savings" and t.savings == 76.0


def test_compare_at_value_is_list_basis():
    t = ad_terms({"current_price": "24.99", "original_price": "101.00", "sale_story": "Depart. store value 101.00"},
                 feed=False)
    assert t.basis == "list"


def test_reg_price_in_text_is_firm():
    t = ad_terms({"current_price": "3.99", "sale_story": "Reg. $5.49"}, feed=False)
    assert (t.regular, t.basis) == (5.49, "store_regular")


def test_multibuy_keeps_quantity():
    t = ad_terms({"current_price": "8.00", "pre_price_text": "2/", "original_price": "10.98"}, feed=True)
    assert (t.qty, t.bundle_price, t.price) == (2, 8.0, 4.0)
    assert "2 for $8.00 ($4.00 ea)" in t.summary


def test_bogo_half_off_is_quarter_saving():
    assert bogo_of("Buy 1 Get 1 50% Off") == ("buy 1 get 1 50% off", 25.0)
    assert bogo_of("BOGO FREE") == ("buy 1 get 1 free", 50.0)
    assert bogo_of("Buy 2, Get 1 Free") == ("buy 2 get 1 free", 33.3)


def test_dollars_off_printed_as_price_is_a_saving():
    t = ad_terms({"current_price": "50", "post_price_text": "OFF"}, feed=False)
    assert t.price is None and t.savings == 50.0 and t.promo


def test_case_price_per_pound_is_not_a_discount():
    # v0.2: gyro kones $4.62/lb with an "original" $184.95 that was the 40 lb case
    t = ad_terms({"current_price": "4.62", "post_price_text": "/lb", "original_price": "184.95"}, feed=True)
    assert t.basis == "none" and t.pct is None


def test_up_to_is_a_hedge():
    t = ad_terms({"pre_price_text": "Up to 40% off", "name": "deals for members"}, feed=False)
    assert t.promo and t.hedge == "up to" and t.pct == 40.0


def test_title_price():
    assert title_price('15.3" Apple MacBook Air M5 $1299 & More + Free S&H') == (1299.0, "& more (price varies by option)")
    assert title_price("2-Pk 6-Oz Olay Lotion w/ SPF 15 $11.05 w/ S&S")[0] == 11.05
    assert title_price("Samsung 65\" QN90F $1,299.99 + Free Shipping")[0] == 1299.99


def test_post_references():
    assert post_reference("You'd pay $65 elsewhere.", 29.0)[:2] == (65.0, "editor_compare")
    assert post_reference("It's the best price we could find by $2.", 13.0)[:2] == (15.0, "editor_compare")
    assert post_reference("That's $419 (about 60%) off the $703 list price.", 284.0)[:2] == (703.0, "list")
    assert post_reference("That's a $41 low.", 45.0)[:2] == (86.0, "history")
    assert post_reference("Amazon [ amazon.com ] has it for $12.99 - 10% when you clip the coupon = $11.05 .",
                          11.05)[:2] == (12.99, "store_regular")


def test_storewide():
    assert is_storewide("Best Buy Labor Day Sale: Up to 70% off + free shipping")
    assert is_storewide("Academy Sports + Outdoors Deal Days: Extra 20% to 30% off")
    assert not is_storewide("Bose SoundLink Max SE Portable Bluetooth Speaker for $229")


# Oct 6, 2026, found while building the share card: words after an ad's price were read as the price itself.
def test_a_price_with_an_extra_coupon_is_not_a_percent():
    # JCPenney "$149.99 + Extra 10% Off* with coupon" was shown as "149.99% off"
    t = ad_terms({"current_price": "149.99", "post_price_text": "+ Extra 10% Off* with coupon"}, feed=False)
    assert t.price == 149.99 and t.pct is None and not t.promo


def test_the_printed_price_is_the_price_with_the_coupon():
    # Family Dollar "$8.95 with $1 OFF Smart Coupon" was shown as "$8.95 off", then as $7.95. The same ad prints
    # "$1.25 with $3 OFF Smart Coupon": the price is what you pay with the coupon, the coupon is the saving.
    t = ad_terms({"price": "8.95", "post_price_text": "with $1 OFF Smart Coupon†"}, feed=False)
    assert (t.price, t.regular, t.savings, t.basis) == (8.95, 9.95, 1.0, "claimed_savings")
    assert "coupon required" in t.conditions
    t = ad_terms({"price": "1.25", "post_price_text": "with $3 OFF Smart Coupon†"}, feed=True)
    assert (t.price, t.savings, t.pct, t.basis) == (1.25, 3.0, 70.6, "claimed_savings")     # never the store's regular


def test_bogo_percent_above_a_price_keeps_the_price():
    t = ad_terms({"current_price": "12.99", "pre_price_text": "BOGO 25% Off"}, feed=False)
    assert t.bogo == "buy 1 get 1 25% off" and t.regular == 12.99 and t.pct == 12.5


def test_percent_printed_where_the_price_goes():
    t = ad_terms({"current_price": "40", "pre_price_text": "Up to", "post_price_text": "% OFF"}, feed=False)
    assert t.price is None and t.pct == 40.0 and t.promo and t.hedge == "up to"


def test_multi_buy_with_a_word_in_front():
    # "Sale! 2/ $9" was read as $9 each
    t = ad_terms({"current_price": "9", "pre_price_text": "Sale! 2/"}, feed=False)
    assert (t.qty, t.bundle_price, t.price) == (2, 9.0, 4.5)
    for pre in ("SALE 3 for", "BUY 2 FOR", "Sale Price 4 FOR", "— ONLY — 2/"):
        assert ad_terms({"current_price": "9", "pre_price_text": pre}, feed=False).qty > 1
    assert ad_terms({"current_price": "9", "pre_price_text": "Buy 2, Get 1"}, feed=False).qty == 1



# Nov 16, 2026: a week of builds left 2,600 ad items out as "no saving stated" whose own words state one.
def _said(price, words, **more):
    return ad_terms({"current_price": price, "sale_story": words, **more}, feed=False)


def test_a_saving_in_words_beside_the_price():
    t = _said("649.99", "Save $250")                                  # the saving, with no regular price printed
    assert (t.price, t.regular, t.savings, t.pct, t.basis) == (649.99, 899.99, 250.0, 27.8, "claimed_savings")
    assert ad_terms({"current_price": "129.99", "sale_story": "Save $70, Sale"}, feed=True).basis == "store_regular"
    assert _said("3.49", "SAVE 50¢").savings == 0.5
    t = _said("3.00", "SAVE $1.50 on 2", pre_price_text="2/")         # 2 for $3, $1.50 less than two cost
    assert (t.price, t.regular, t.savings) == (1.5, 2.25, 0.75) and "each" in t.summary


def test_a_saving_with_no_dollar_sign():
    t = _said("104.99", "You save 5.00")
    assert (t.regular, t.savings) == (109.99, 5.0)
    for words, amount in (("250.00 OFF REG. PRICE", 250.0), ("200 OFF REG. PRICE", 200.0), ("Sale! 50¢ OFF", 0.5),
                          ("8.00 Off SAVE 8.00 WITH EACH PURCHASE OF ONE", 8.0)):
        t = _said(None, words)                                        # no price at all: a promotion
        assert (t.price, t.savings, t.promo) == (None, amount, True), words
    assert _said("4.98", "Great Value 10.75 oz").basis == "none"      # a size is not an amount


def test_a_saving_up_to_an_amount_is_a_ceiling():
    t = _said("5.97", "SAVE up to $2 per lb.", post_price_text="lb.")
    assert (t.price, t.regular, t.savings, t.pct, t.hedge) == (5.97, None, 2.0, 25.1, "up to")
    assert "up to $2.00" in t.summary and "up to 25.1% off" in t.summary
    t = _said(None, "Save up to $30")
    assert (t.savings, t.promo, t.hedge) == (30.0, True, "up to") and t.summary == "up to $30.00 off"


def test_a_saving_on_an_order_or_on_something_else_is_not_the_items():
    for words in ("Save $10 when you spend $40 on select holiday decor", "SPEND $199 SAVE $50, SPEND $299 SAVE $80",
                  "$10 off $50", "COMPRA 1 LB O MÁS / OBTÉN $1 OFF EN TORTILLAS DE MAÍZ", "$5 off your next order",
                  "Buy 2 get $5 Rewards WITH CARD", "Save More with FOOD TOWN", "BUY BIG SAVE BIG", "SAVE",
                  "Instant Savings* are on now", "Plus a 10% Fee at Checkout", "FINAL PRICE WITH COUPON",
                  "/EA With Digital Coupon", "FREE $22.98 value", "Up to $298 value with purchase"):
        t = _said("5.99", words)
        assert t.basis == "none" and t.savings is None and t.pct is None, words
    assert _said(None, "50¢ OFF PER GALLON WITH YOUR $50 GROCERY PURCHASE").savings is None


def test_a_saving_for_several_is_shared_among_them():
    t = _said("10.39", "FINAL PRICE When You Buy 6 SAVE $60 When You Buy 6 or more")
    assert (t.regular, t.savings) == (20.39, 10.0) and "buy multiple" in t.conditions
    t = _said("43.99", "Buy 2 Get $12.00 Off")
    assert (t.price, t.savings, t.bogo) == (43.99, 6.0, "") and "buy multiple" in t.conditions


def test_a_coupons_amount_is_the_saving():
    for price, words, each in (("6.99", "with myWalgreens $1 off online coupon", 1.0),
                               ("15.95", "FINAL PRICE WITH COUPON $4 DG DIGITAL COUPON", 4.0),
                               ("5.49", "WITH CARD Also get savings with $2.50 Digital mfr coupon", 2.5),
                               ("2.00", "with 75¢ OFF Smart Coupon†", 0.75),
                               ("3.99", "ea. $4.99-1.00 Digital Coupon", 1.0),
                               ("2.97", "ea Digital Coupon - $1.00", 1.0),
                               ("1.77", "plus a 10% fee at checkout - 90¢ / EA DIGITAL COUPON FINAL PRICE", 0.9),
                               ("13.00", "Earn $5 rewards when you buy 2**, $7 off 2 online coupon◊", 3.5)):
        t = _said(price, words)
        assert (t.price, t.savings, t.basis) == (float(price), each, "claimed_savings"), words
        assert "coupon required" in t.conditions
    t = _said("4.00", "with $1 OFF Smart Coupon†", pre_price_text="Sale! 2/")       # one coupon over the two
    assert (t.qty, t.price, t.regular) == (2, 2.0, 2.5)
    t = _said("5.00", "2 POR $6.00 -$1.00 Digital Coupon", pre_price_text="2/")
    assert (t.price, t.regular) == (2.5, 3.0)
    assert _said(None, "75¢ OFF with Smart Coupon*†").savings == 0.75
    # what a coupon earns, or the order it takes, is not what it saves
    for words in ("$5 gift card with coupon", "Get $8 rewards with coupon", "$5 off $25 coupon"):
        t = _said("9.99", words)
        assert t.savings is None and t.basis == "none", words
    assert _said("5.49", "$2.50 Digital mfr coupon + Spend $25 get $8 ExtraBucks Rewards").savings == 2.5


def test_the_saving_printed_where_the_price_goes_after_save():
    t = ad_terms({"current_price": "2.0", "pre_price_text": "SAVE", "post_price_text": "DG DIGITAL COUPON"}, feed=False)
    assert (t.price, t.savings, t.promo) == (None, 2.0, True) and "coupon required" in t.conditions
    t = ad_terms({"current_price": "1.0", "pre_price_text": "INSTANTLY SAVE", "post_price_text": "WHEN YOU BUY 2"},
                 feed=False)
    assert (t.price, t.savings, t.promo) == (None, 1.0, True) and "buy multiple" in t.conditions
    t = ad_terms({"current_price": "9.99", "pre_price_text": "SAVE"}, feed=False)       # a burst over a price
    assert (t.price, t.savings, t.promo) == (9.99, None, False)


def test_a_price_compared_with_other_stores():
    t = _said("39.99", "WITH CARD Depart. store value 65.00 You save 25.00")
    assert (t.regular, t.savings, t.basis) == (65.0, 25.01, "list")
    t = _said("3.99", "EACH THEIRS $8.99. SAVE UP TO 56% OFF FANCY STORES")
    assert (t.regular, t.pct, t.basis) == (8.99, 55.6, "list")
    assert _said("7.00", "20% BIGGER & HEAVIER THAN FANCY STORES' BATH SHEETS!, theirs $19.99").regular == 19.99


def test_a_firm_percent_beside_a_price():
    for words in ("10% OFF When You Buy 6 or More", "when you BUY 6 or more - 10% OFF", "-10% OFF",
                  "member price -10% OFF When You Buy 6 or More", "SAVE 10% WHEN YOU BUY SIX OR MORE BOTTLES OF WINE"):
        t = _said("22.49", words)
        assert (t.price, t.pct, t.regular, t.hedge, t.basis) == (22.49, 10.0, None, "", "claimed_savings"), words
    assert "buy multiple" in _said("13.99", "SAVE 10% WHEN YOU BUY SIX OR MORE BOTTLES OF WINE").conditions
    assert _said("22.49", "- 10% OFF When You Buy 6", post_price_text="ea").hedge == ""
    for words in ("Up to 50% Off Kitchen Appliances + Extra 10% Off* with coupon", "SAVE UP TO 40% OFF APPAREL*",
                  "50% off 2nd", "20% off your next purchase", "Additional 15% off with card"):
        assert _said("62.99", words).pct is None, words
    t = _said(None, "Save 20% When you buy any 6 bottles of wine 750 ml. or larger")
    assert (t.pct, t.promo) == (20.0, True) and "buy multiple" in t.conditions


def test_a_price_that_runs_up_to_another_is_a_floor():
    t = ad_terms({"current_price": "6.0", "post_price_text": "to $13.00 with myWalgreens",
                  "sale_story": "$2 off Walgreens coupon◊"}, feed=False)
    assert (t.price, t.savings, t.pct, t.regular, t.hedge) == (6.0, 2.0, None, None, "starting at")


def test_buy_and_get_with_words_between():
    assert bogo_of("BUY ONE AND GET ONE FREE") == ("buy 1 get 1 free", 50.0)
    assert bogo_of("BUY TWO AND GET ONE FREE") == ("buy 2 get 1 free", 33.3)
    assert bogo_of("BUY 1 GET FREE 1") == ("buy 1 get 1 free", 50.0)
    # how many come free is not said, another item comes free, or the second one costs something
    for words in ("BUY 2 GET FREE", "Buy 1 get free shipping", "Buy 2 Get $6.00 Off", "Buy 1 get 2nd for $1* WITH CARD",
                  "Buy 2 get $5 ExtraBucks Rewards", "BUY 1 Classico Pasta Sauce, GET 1 FREE Clover Valley Spaghetti",
                  "BUY ONE OF THESE GET 1 FREE SELECT POWER TOOL", "Buy 2 gallons"):
        assert bogo_of(words) == ("", None), words
    assert bogo_of("Buy 2 gallons, BOGO free") == ("buy 1 get 1 free", 50.0)



# Nov 22, 2026: the first build with the readers above still left out three wordings.
def test_instantly_save_takes_an_amount_whatever_follows():
    t = ad_terms({"current_price": "1.0", "pre_price_text": "INSTANTLY SAVE", "post_price_text": "*"}, feed=False)
    assert (t.price, t.savings, t.promo) == (None, 1.0, True)
    t = ad_terms({"current_price": "5", "pre_price_text": "SAVE UP TO"}, feed=False)
    assert (t.price, t.savings, t.promo, t.hedge) == (None, 5.0, True, "up to")
    t = ad_terms({"current_price": "9.99", "pre_price_text": "SAVE", "post_price_text": "*"}, feed=False)
    assert (t.price, t.savings, t.promo) == (9.99, None, False)          # a bare "SAVE" is still a burst over a price


def test_a_saving_with_a_word_before_the_amount():
    t = _said("19.99", "SAVE ADDITIONAL $8 WHEN YOU BUY 2, Earn 4x POINTS", post_price_text="ea member price")
    assert (t.price, t.savings, t.regular) == (19.99, 4.0, 23.99) and "buy multiple" in t.conditions
    assert _said("9.99", "Save an extra $2").savings == 2.0
    assert _said("9.99", "Save extra 20% with coupon").savings is None      # a percent is no amount


def test_a_saving_off_a_list_price():
    t = _said("49.99", "$20 OFF MSRP")
    assert (t.regular, t.savings, t.basis) == (69.99, 20.0, "list")
    t = _said("49.99", "UP TO $50 OFF MSRP", post_price_text="- $69.99")       # "$49.99 - $69.99, up to $50 off MSRP"
    assert (t.price, t.regular, t.savings, t.hedge, t.basis) == (49.99, None, 50.0, "up to", "list")
    assert "up to $50.00" in t.summary
    assert _said("49.99", "$20 off tortillas").savings is None
