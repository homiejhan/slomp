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
