from plum.identifiers import canonical_gtin, check_digit, extract_gtins, extract_mpns, is_valid_gtin, make_gtin


def test_known_upc():
    assert is_valid_gtin("036000291452")
    assert not is_valid_gtin("036000291453")


def test_ean13_and_upc_compare_equal_when_canonical():
    upc = "036000291452"
    assert canonical_gtin(upc) == canonical_gtin("0" + upc)
    assert canonical_gtin(upc) == "00036000291452"


def test_make_gtin_roundtrip():
    g = make_gtin("02724292350")
    assert len(g) == 12 and is_valid_gtin(g)
    assert check_digit(g[:-1]) == int(g[-1])


def test_extract_from_text():
    text = "Sony WH-1000XM5 headphones UPC 036000291452 sku 99999999"
    assert extract_gtins(text) == ["00036000291452"]
    assert "WH-1000XM5" in extract_mpns(text)


def test_bad_lengths_rejected():
    assert not is_valid_gtin("12345")
    assert canonical_gtin("") is None
