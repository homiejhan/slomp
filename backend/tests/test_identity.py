from plum.identity import identify, model_query, same_product


def test_models_and_named_products():
    assert identify("Sony WH-1000XM6 Wireless Headphones").key == "sony|WH1000XM6"
    assert identify("Apple AirPods Pro 3 (2025)").key == "apple|AIRPODSPRO3"
    assert identify("Apple AirPods 4 with Active Noise Cancellation").model == "AIRPODS4ANC"
    assert identify("LEGO Icons Bonsai Tree 10281").key == "lego|10281"
    assert identify("Nike Dunk Low Retro DD1391-100").model == "DD1391100"


def test_specs_and_words_are_not_models():
    assert identify("4-Pk Energizer 3V Lithium Coin 2025 Batteries w/ 3-in-1 Child Shield").model == ""
    assert identify("3-Port 100W USB-C GaN Wall Charger").model == ""
    assert identify("Insta360 Luna Ultra 8K 360 Camera").model == ""      # the brand is not its own model


def test_color_variants_match_and_generations_do_not():
    assert same_product(identify("Sony WH-1000XM5 Black"), identify("Sony WH1000XM5/S Silver"))[0]
    assert not same_product(identify("Sony WH-1000XM5"), identify("Sony WH-1000XM4"))[0]
    assert not same_product(identify("Sony WH-1000XM6"), identify("Sony WF-1000XM6 Earbuds"))[0]


def test_brandless_amazon_title_matches_with_hint():
    ok, _ = same_product(identify("Sony WH-1000XM6"), identify("WH-1000XM6 The Best Noise Cancelling Headphones", "Sony"))
    assert ok


def test_accessories_conditions_and_sizes_do_not_match():
    printer = identify("Epson WorkForce WF-2930 Color Inkjet All-In-One Printer")
    assert not same_product(printer, identify("232 Claria Ink Combo Pack (T232120-BCS) Works with Workforce WF-2930",
                                              "Epson"))[0]
    assert not same_product(printer, identify("Maintenance Box Compatible with XP-3100 WF-2810 WF-2930"))[0]
    assert not same_product(identify("Sony WH-1000XM5"), identify("Sony WH-1000XM5 (Renewed)"))[0]
    assert not same_product(identify('Samsung 55" QN90F'), identify('Samsung 65" QN90F'))[0]
    assert same_product(identify("MacBook Air 15 M5 16GB 512GB"), identify("Apple MacBook Air 15 M5 16GB 512GB SSD"))[0]
    assert not same_product(identify("MacBook Air M5 16GB 512GB"), identify("MacBook Air M5 16GB 1TB"))[0]


def test_unidentifiable_products_get_no_query():
    assert model_query(identify("Nike Men's Club Fleece Hoodie")) is None
