from plum.online import same_listing
from plum.sources.prices import asins_in, parse_amazon, parse_amazon_item, parse_newegg

AMAZON_ITEM = """
<span id="productTitle" class="a-size-large"> Sony WH-1000XM6 The Best Noise Cancelling Wireless Headphones </span>
<div id="corePrice_feature_div"><span class="a-price"><span class="a-offscreen">$379.99</span></span></div>
<table><tr><th class="a-color-secondary a-size-base prodDetSectionEntry"> Brand Name </th>
<td class="a-size-base prodDetAttrValue"> Sony </td></tr>
<tr><th class="a-color-secondary a-size-base prodDetSectionEntry"> Model Name </th><td> WH-1000XM6 </td></tr>
<tr><th class="a-color-secondary a-size-base prodDetSectionEntry"> UPC </th><td> 027242930698 </td></tr></table>
"""

AMAZON_SEARCH = """
<div data-component-type="s-search-result" data-asin="B0FL9J9LV4"><span>Sponsored</span>
<h2 aria-label="Sponsored Ad - WH-1000XM6 Headphones"></h2><span class="a-price"><span class="a-offscreen">$449.95</span></span></div>
<div data-component-type="s-search-result" data-asin="B0F3PQHWTZ">
<h2 aria-label="WH-1000XM6 The Best Noise Cancelling Wireless Headphones, Black"></h2>
<span class="a-price"><span class="a-offscreen">$379.99</span></span>
<span class="a-price a-text-price"><span class="a-offscreen">$459.99</span></span></div>
"""


def test_amazon_product_details():
    item = parse_amazon_item("B0F3PQHWTZ", AMAZON_ITEM)
    assert (item.brand, item.models, item.upc, item.price) == ("Sony", ["WH-1000XM6"], "027242930698", 379.99)


def test_amazon_search_skips_sponsored():
    rows = parse_amazon(AMAZON_SEARCH)
    assert [(r.price, r.regular_price, r.url[-10:]) for r in rows] == [(379.99, 459.99, "B0F3PQHWTZ")]


def test_newegg_marketplace_sellers_are_skipped():
    page = ('<script>window.__initialState__ = {"Products": ['
            '{"ItemCell": {"Item": "26-197-663", "FinalPrice": 89.99, "Model": "910-007500", '
            '"Description": {"Title": "Logitech MX Master 3S"}, "Seller": null}},'
            '{"ItemCell": {"Item": "9SIA15TKHA0655", "FinalPrice": 269.99, "Model": "WH-1000XM6/B", '
            '"Description": {"Title": "SONY WH1000XM6/B"}, "Seller": {"SellerName": "Secondipity"}}}]}</script>')
    rows = parse_newegg(page)
    assert [(r.price, r.url) for r in rows] == [(89.99, "https://www.newegg.com/p/N82E16826197663")]


def test_asins_found_in_posts():
    assert asins_in("see https://www.amazon.com/gp/product/B0HC5K6C4G and amazon.com/dp/B0F2FWDM7Z?tag=x") == \
        ["B0HC5K6C4G", "B0F2FWDM7Z"]


def test_amazon_page_must_be_the_posts_product():
    assert same_listing('17.3" LOVEVOOK Laptop Backpack w/ Tumbler Pocket $17',
                        "LOVEVOOK Laptop Backpack for Women, 17.3 Inch Travel Backpack with Tumbler Pocket", "LOVEVOOK")
    assert not same_listing('17.3" LOVEVOOK Laptop Backpack w/ Tumbler Pocket $17',
                            "LOVEVOOK Mini Backpack for Women Stylish Waterproof", "LOVEVOOK")


def test_it02_out_of_stock_comes_from_the_buy_box():
    # it02: every Amazon page carries a "Currently unavailable" message template; 7 of 8 in-stock items were flagged
    page = ('<div id="availability"><span> In Stock </span> {"currentlyUnavailableMessage":"Currently unavailable."}'
            '</div><input id="add-to-cart-button">')
    assert not parse_amazon_item("B0H3ZGJXKH", page).unavailable
    gone = '<div id="availability"><span> Currently unavailable. </span></div>'
    assert parse_amazon_item("B0H3ZGJXKH", gone).unavailable


def test_it03_removed_or_expired_posts_are_detected():
    # it03 O-FID: a dealnews post for a sleeping bag redirected to dealnews' Amazon store page; Plum still listed it
    from plum.sources.feeds import post_gone
    url = "https://www.dealnews.com/Hudson-Baby-Sleeping-Bag-for-11/22242953.html"
    assert post_gone(url, "https://www.dealnews.com/s313/Amazon/22242953.html", "<html>Amazon deals</html>")
    assert post_gone(url, url, "<div class='flag'>This deal has expired</div>")
    assert not post_gone(url, url, "<h1>Hudson Baby Sleeping Bag for $11</h1>")


def test_it05_bundles_and_post_listed_stores():
    from plum.identity import identify, same_product
    from plum.sources.feeds import _SD_STORE_PRICE
    # a console bundle is not the console
    assert not same_product(identify("Nintendo Switch 2 Mario Kart World Bundle"), identify("Nintendo Switch 2 Console"))[0]
    text = ("Amazon [ amazon.com ] has 799-Piece LEGO Icons Williams Racing (10353) on sale for $51.99 . Shipping is free. "
            "Target [ target.com ] has 799-Piece LEGO Icons Williams Racing (10353) on sale for $51.99 .")
    assert _SD_STORE_PRICE.findall(text) == [("amazon.com", "51.99"), ("target.com", "51.99")]


def test_feed_pictures_are_extracted():
    from plum.sources.feeds import _image, parse_bensbargains, parse_theinventory, parse_hip2save
    assert _image("<p><img src='//cdn.bensimages.com/media/img/450/1.webp'></p>") == "https://cdn.bensimages.com/media/img/450/1.webp"
    assert _image("", "http://f.wishabi.net/a.jpg") == "https://f.wishabi.net/a.jpg"
    assert _image("just words", None) == ""
    assert _image("javascript:alert(1)") == ""
    rss = ('<rss xmlns:media="http://search.yahoo.com/mrss/"><channel><item><title>Lacoste Tee 40% Off at $36.27</title>'
           '<link>https://theinventory.com/x</link><guid>g1</guid><description>is now $36.27 (40% off)</description>'
           '<media:thumbnail url="https://theinventory.com/img/tee.png"/></item></channel></rss>').encode()
    assert parse_theinventory(rss, "f", [])[0].image == "https://theinventory.com/img/tee.png"
    rss = ('<rss><channel><item><title>Tuna $10 at Walmart</title><link>https://bensbargains.com/deal/1/</link>'
           '<description>&lt;img src="//cdn.bensimages.com/media/img/450/2.webp"&gt; text</description></item></channel></rss>').encode()
    assert parse_bensbargains(rss, "f", [])[0].image == "https://cdn.bensimages.com/media/img/450/2.webp"
    rss = ('<rss xmlns:h="https://hip2save.com/ns"><channel><item><title>LEGO Set Only $8 on Amazon (Reg. $20)</title>'
           '<link>https://hip2save.com/deals/lego/</link><h:thumbnail-image>https://hip2save.com/wp/lego.jpg?resize=306,182'
           '</h:thumbnail-image></item></channel></rss>').encode()
    assert parse_hip2save(rss, "f", [])[0].image == "https://hip2save.com/wp/lego.jpg?resize=306,182"
