from plum.identifiers import make_gtin
from plum.matching import ProductIndex, match
from plum.models import Listing, Tier
from plum.textfeatures import features, near_code


def test_features_extract_codes_and_sizes():
    f = features("Stanley Quencher H2.0 FlowState Tumbler 40 oz, Charcoal")
    assert "h20" in f.codes and "40oz" in f.sizes
    f2 = features("Nike Pegasus 41 Men's Road Running Shoes")
    assert "pegasus41" in f2.codes
    assert "2nd" not in features("AirPods Pro (2nd generation)").codes


def test_near_code():
    assert near_code("wh1000xm4", "wh1000xm5")
    assert near_code("v11", "v15")
    assert near_code("10280", "10281")
    assert not near_code("nc301", "nc3011")


def test_tiers(products, listings):
    sony = products[0]
    by = {l.id: match(sony, l) for l in listings}
    assert by["amz-1"].tier == Tier.EXACT
    assert by["bb-1"].tier == Tier.EXACT
    assert by["wm-1"].tier == Tier.CONFIDENT and "wh1000xm5" in by["wm-1"].reasons[0]
    assert by["wm-2"].tier == Tier.REJECTED and any("different model" in r for r in by["wm-2"].reasons)
    assert by["eb-1"].tier == Tier.REJECTED and any("accessory" in r for r in by["eb-1"].reasons)
    assert by["eb-3"].tier in (Tier.LIKELY, Tier.CONFIDENT) and any("check digit" in r for r in by["eb-3"].reasons)


def test_products_without_codes_lean_on_words(products):
    airpods = products[1]
    assert match(airpods, Listing("x", "walmart", "Apple AirPods Pro 2nd Generation USB-C", 189)).tier == Tier.CONFIDENT
    assert match(airpods, Listing("y", "amazon", "Silicone Case for AirPods Pro 2nd Generation", 22.99)).tier == Tier.REJECTED


def test_size_clash_and_variant(products):
    stanley = products[2]
    assert match(stanley, Listing("a", "walmart", "Stanley Quencher H2.0 FlowState Tumbler 30 oz, Fog", 35)).tier == Tier.REJECTED
    variant = match(stanley, Listing("b", "ebay", "Stanley Quencher H2.0 FlowState 40oz Tumbler Rose Quartz - New", 29.99, gtin=make_gtin("04138344011")))
    assert variant.tier == Tier.LIKELY and any("variant" in r for r in variant.reasons)


def test_conflict_beats_spurious_shared_code(products):
    ip = products[3]
    m = match(ip, Listing("c", "amazon", "Instant Pot Duo Plus 9-in-1 Electric Pressure Cooker, 6 Quart", 129.95))
    assert m.tier == Tier.REJECTED


def test_index_find_and_resolve(products, listings):
    idx = ProductIndex(products)
    assert idx.find("sony xm5")[0].id == "sony-xm5"
    assert idx.find("airpods")[0].id == "airpods-pro-2"
    assert idx.find(products[0].gtin) == (products[0], "barcode")
    assert idx.find("036000291453") == (None, "invalid barcode")
    assert idx.find("toaster")[0] is None
    p, m = idx.resolve(listings[2])
    assert p.id == "sony-xm5" and m.tier == Tier.CONFIDENT
    assert idx.resolve(listings[4])[0] is None
