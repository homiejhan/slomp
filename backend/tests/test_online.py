"""Online deals. Feed items mirror real Slickdeals, dealnews and camelcamelcamel posts (Sept 2026)."""
import json
from datetime import timedelta

import httpx
import pytest

from fakeweb import LAT, LON, NOW, FakeWeb
from plum import cli
from plum.adapters.feeds import parse_camel, parse_dealnews, parse_slickdeals
from plum.net import HttpClient
from plum.online import OnlineDealService, not_an_item, same_product
from plum.render import basis_label, jsonable, render_online
from plum.textfeatures import model_codes

POSTED = (NOW - timedelta(hours=3)).strftime("%a, %d %b %Y %H:%M:%S +0000")
OLD = (NOW - timedelta(days=9)).strftime("%a, %d %b %Y %H:%M:%S +0000")


def sd_item(tid, title, body, *, slug="amazon", desc="", posted=POSTED):
    lead, has, rest = body.partition(" has ")          # as on Slickdeals, the store phrase is the link text
    post = f'<a data-store-slug="{slug}">{lead}</a> has {rest}' if has else f'<a data-store-slug="{slug}"></a>{body}'
    content = (f'<div><img src="https://static.slickdealscdn.com/{tid}.thumb"></div><div>Thumb Score: +{tid % 50} </div>'
               f"<div>{post}</div>")
    return (f"<item><title><![CDATA[{title}]]></title><link>https://slickdeals.net/f/{tid}-x?utm_source=rss</link>"
            f"<description><![CDATA[{desc or body}]]></description><content:encoded><![CDATA[{content}]]></content:encoded>"
            f"<pubDate>{posted}</pubDate></item>")


def slickdeals_feed(*items):
    return ('<?xml version="1.0"?><rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">'
            f"<channel>{''.join(items)}</channel></rss>")


def dn_item(num, title, text, price, retailer, *, staff="false", category="Electronics", expires="2026-12-01T00:00:00-05:00"):
    desc = f"&lt;img src='https://d.dlnws.com/{num}.jpg'&gt;&lt;p&gt;{text}&lt;/p&gt;"
    return (f"<item><title>{title}</title><link>https://www.dealnews.com/x/{num}.html?iref=rss</link>"
            f"<description>{desc}</description><pubDate>{POSTED}</pubDate><dealnews:price>{price}</dealnews:price>"
            f"<dealnews:retailer>{retailer}</dealnews:retailer><dealnews:staffPick>{staff}</dealnews:staffPick>"
            f"<dealnews:category>{category}</dealnews:category><dealnews:expires>{expires}</dealnews:expires></item>")


def dealnews_feed(*items):
    return ('<?xml version="1.0" encoding="UTF-8"?><rss version="2.0" xmlns:dealnews="https://www.dealnews.com/ns/rss/1.0.htm">'
            f"<channel>{''.join(items)}</channel></rss>")


CAMEL = ('<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>'
         f"<item><title>I'll Be Your Girl - down 13.26% ($3.88) to $25.37 from $29.25</title>"
         f"<link>https://camelcamelcamel.com/product/B0791XK5SV</link><pubDate>{POSTED}</pubDate></item>"
         f"<item><title>Samsung U8000H 43in 4K Smart TV - down 40.00% ($132.00) to $198.00 from $330.00</title>"
         f"<link>https://camelcamelcamel.com/product/B0TV000001</link><pubDate>{POSTED}</pubDate></item>"
         "</channel></rss>")

SLICK = slickdeals_feed(
    sd_item(20050443, '4" x 6" Phomemo Smart Touchscreen Thermal Label Printer (Black) $50 + Free S&H',
            "Phomemo-YQ via Amazon [ amazon.com ] has 4\" x 6\" Phomemo PM64D Thermal Shipping Label Printer on sale for "
            "$89.98 - $39.99 off when you apply promo code 9ZJWD47V at checkout. Shipping is free.",
            desc='Phomemo-YQ via Amazon [amazon.com] has *4" x 6" Phomemo PM64D Thermal Shipping Label Printer* on sale'),
    sd_item(20052474, "6-Pk 16.9-Oz Diet Coke Soda Soft Drink Bottles 4 for $13.90 w/ S&S",
            "Amazon [ amazon.com ] has 6-Pack 16.9-Oz Diet Coke Diet Soda 4 for $21.56 - $15 (multibuy discount) - 5% "
            "when you check out via Subscribe & Save = $13.92 . Shipping is free."),
    sd_item(20055276, "Prime Members: 3-Pk 10' KYEHD 60W USB-C Fast Charging Cables $4 + Free S&H",
            "Lvgder via Amazon [ amazon.com ] has for Prime Members : 3-Pack 10' KYEHD 60W USB-C Cables on sale for $7.99 "
            "- $4.00 promo code B9ZARBPS at checkout = $3.99 . Shipping is free."),
    sd_item(20051439, "Disney Mickey Mouse Men's Beach Swim Trunks (Red, Various) $5.25",
            "Disney Swim Trunks for Men Sale Price: $5.24 List Price: $19.98 Ships FREE with Walmart+", slug="walmart"),
    sd_item(20045532, "adidas Kids' Runfalcon 5 Shoes Kids: Royal Blue $18, Bliss Pink $16.80 + Free S&H",
            "adidas via eBay has adidas Kids' Runfalcon 5 Shoes on sale for $28 - 40% coupon code SEPTEMBER40 "
            "auto-applied at checkout. Shipping is free.", slug="ebay"),
    sd_item(20043471, "Certified Refurb: Bose QuietComfort Ultra Noise Cancelling Headphones $190",
            "Bose via eBay has refurbished QuietComfort Ultra headphones for $190. 2-year warranty.", slug="ebay"),
    sd_item(20054670, "DeWALT Retractable Utility Knife w/ Blade Storage $10",
            "Amazon [ amazon.com ] has DEWALT Retractable Utility Knife w/ Blade Storage (DWHT10998) on sale for $9.99 . "
            "Shipping is free.", desc="Amazon [amazon.com] has *DEWALT Retractable Utility Knife w/ Blade Storage (DWHT10998)*"),
    sd_item(20045600, "30% Off Select Boss or Roland Products + Free S&H",
            "Focus Pro Audio has 30% off select Boss or Roland products with code FCRBSL.", slug="focus"),
    sd_item(20012345, "Samsung U8000H 43\" 4K UHD Smart TV $199", "Walmart [ walmart.com ] has Samsung U8000H 43\" 4K UHD "
            "Smart TV on sale for $199.00 . Shipping is free.", slug="walmart"),
    sd_item(20000001, "Ancient Blender $20", "Amazon [ amazon.com ] has a blender on sale for $40 - 50% with promo code "
            "OLDCODE1 = $20.", posted=OLD),
    sd_item(20050434, "Prime Members: 32-Oz ENCOOL Insulated Stainless Steel Water Bottle w/ Straw Lid $9 & More",
            "ENCOOL via Amazon [ amazon.com ] has for Prime Members : ENCOOL Insulated Stainless Steel Water Bottle on sale "
            "from $17.99 - 50% off when you apply promo code SM8BDOZV at checkout. Shipping is free."),
)
DEALNEWS = dealnews_feed(
    dn_item(22209922, "Polo Ralph Lauren Men's Varick Slim Straight Stretch Jeans for $43 + free shipping",
            "Macy's offers the Polo Ralph Lauren Men's Varick Slim Straight Stretch Jeans in Khaki Hill for $42.63. "
            "You'd pay over $90 elsewhere. Buy Now at Macy's", "43.00", "Macy's", staff="true", category="Jeans"),
    dn_item(22209940, "Dockers Men's Frederick Casual Sneakers for $25 + free shipping",
            "Walmart offers them for $24.99. You'd pay $5 more at Macy's. Buy Now at Walmart", "25.00", "Walmart"),
    dn_item(22212486, "The North Face Borealis Tote Bag for $40 + free shipping",
            "At Amazon, clip the on-page coupon to get The North Face Borealis Tote Bag for $40. It's the best price we "
            "found by at least $50. Buy Now at Amazon", "40.00", "Amazon"),
    dn_item(22209909, "DSG Ultimate Backpack 5.0 for $11 + free shipping w/ $49",
            "Dick's offers it for $10.97. That's a $39 savings. Buy Now at Dick's", "11.00", "Dick's Sporting Goods"),
    dn_item(537523, "Vevor Bench Polisher &amp; Buffing Machine for $38 + free shipping w/ Prime",
            "Woot offers it for $37.99. That's a $9 low and its best-ever price.", "38.00", "Woot! An Amazon Company"),
    dn_item(22209999, "Costco 1-Year Gold Star Membership for $65", "Join Costco.", "65.00", "Costco", category="Memberships"),
    dn_item(22209998, "Mint Mobile Premium Wireless for $15/mo. for up to 1 year", "New customers only.", "15.00", "Mint Mobile"),
    dn_item(22209997, "Expired Widget for $5", "That's a $5 savings.", "5.00", "Amazon", expires="2026-09-01T00:00:00-05:00"),
    dn_item(22212490, "Bella PRO Small Kitchen Appliances at Best Buy for Deals from $30 + free shipping",
            "This Best Buy sale includes a coffee maker at $29.99. Savings run as high as $74 off.", "30.00", "Best Buy"),
    dn_item(22212491, "Household &amp; Personal Care Essentials at Amazon for $10 off $40 + free shipping w/ Prime",
            "Clip the coupon.", "40.00", "Amazon"),
    dn_item(22212492, "Ridgid 18V Cordless Inverter Kit w/ 2.0 Ah Battery &amp; Charger for $79 + free shipping",
            "Home Depot offers it for $79. Savings run as high as $189 on the kit.", "79.00", "Home Depot"),
)


def routes(**overrides):
    r = {
        "slickdeals.net/newsearch.php": SLICK,
        "www.dealnews.com/": DEALNEWS,
        "camelcamelcamel.com/top_drops/feed": CAMEL,
        "nominatim.openstreetmap.org/search": [{"lat": str(LAT), "lon": str(LON), "addresstype": "city",
                                                "address": {"city": "Austin", "state": "Texas", "postcode": "78701"}}],
        "backflipp.wishabi.com/flipp/items/search": lambda req: {"items": [
            {"id": 7001, "flyer_id": 70, "merchant_name": "Best Buy", "name": "Samsung - 43\" Class U8000H 4K UHD Smart TV",
             "current_price": 229.99, "valid_from": "2026-09-22T04:00:00+00:00", "valid_to": "2026-09-29T03:59:59+00:00"},
            {"id": 7002, "flyer_id": 70, "merchant_name": "Best Buy", "name": "Samsung - 43\" Class U7900F 4K UHD Smart TV",
             "current_price": 179.99, "valid_from": "2026-09-22T04:00:00+00:00", "valid_to": "2026-09-29T03:59:59+00:00"},
        ]} if "U8000H" in str(req.url) else {"items": []},
    }
    r.update(overrides)
    return {k: (httpx.Response(200, text=v) if isinstance(v, str) else v) for k, v in r.items()}


def service(**overrides):
    web = FakeWeb(routes(**overrides))
    return OnlineDealService(HttpClient(transport=httpx.MockTransport(web), backoff_s=0), clock=lambda: NOW), web


# --- parsing --------------------------------------------------------------------------------------------------------

def test_slickdeals_math_codes_and_references():
    by = {d.id.split(":")[1]: d for d in parse_slickdeals(SLICK)}
    p = by["20050443"]
    assert (p.store, p.terms.price, p.terms.was, p.terms.pct_off, p.code) == ("Amazon", 49.99, 89.98, 44.4, "9ZJWD47V")
    assert p.title.startswith('4" x 6" Phomemo PM64D') and p.votes == 20050443 % 50 and p.image_url
    coke = by["20052474"].terms                                   # "4 for $21.56 ... = $13.92"
    assert (coke.price, coke.quantity, coke.was, coke.pct_off, coke.conditions) == (13.92, 4, 21.56, 35.4, ("Subscribe & Save",))
    cable = by["20055276"]
    assert cable.terms.price == 3.99 and "Prime members only" not in cable.title and cable.terms.conditions[-1] == "prime members only"
    trunks = by["20051439"].terms                                 # "List Price" is a compare-at price
    assert (trunks.price, trunks.was, trunks.hedge, by["20051439"].store) == (5.24, 19.98, "compare at", "Walmart")
    shoes = by["20045532"]                                        # 40% off $28 = $16.80, one of the two title prices
    assert (shoes.store, shoes.terms.price, shoes.terms.pct_off) == ("eBay", 16.8, 40.0)
    bose = by["20043471"]
    assert bose.store == "eBay" and "refurbished" in bose.terms.conditions and bose.terms.hedge == "no reference"
    knife = by["20054670"]
    assert knife.terms.hedge == "no reference" and knife.terms.pct_off is None and "DWHT10998" in knife.title
    bottle = by["20050434"]                                       # Amazon opened on the 18 oz at $21.99: sizes vary
    assert (bottle.terms.price, bottle.terms.hedge) == (8.99, "starting at")
    assert basis_label(bottle) == "price depends on the option you pick"


def test_dealnews_comparisons_history_and_savings():
    by = {d.id.split(":")[1]: d for d in parse_dealnews(DEALNEWS)}
    polo = by["22209922"]
    assert (polo.terms.price, polo.store, polo.staff_pick, polo.terms.hedge, polo.terms.pct_off) == (42.63, "Macy's", True, "elsewhere", 52.6)
    assert [(p.store, p.price, p.at_least) for p in polo.elsewhere] == [("other stores", 90.0, True)]
    dockers = by["22209940"].elsewhere[0]
    assert (dockers.store, dockers.price, dockers.source) == ("Macy's", 29.99, "dealnews editors")
    tote = by["22212486"]                                         # on Amazon: $69.13 less a $28.65 clip coupon
    assert [(p.store, p.price, p.at_least) for p in tote.elsewhere] == [("next-cheapest store", 90.0, True)]
    assert tote.terms.conditions == ("clip coupon",)
    bag = by["22209909"].terms                                    # "a $39 savings" names no reference
    assert (bag.hedge, bag.dollars_off, bag.was) == ("no reference", 39.0, None)
    vevor = by["537523"]
    assert vevor.store == "Woot!" and vevor.history == "$9 below its previous low; best price ever seen" and vevor.terms.pct_off is None
    assert "22209998" not in by                                   # a monthly plan isn't a priced product
    kit = by["22212492"]                                          # "as high as $189" is a ceiling, not this kit's saving
    assert kit.terms.hedge == "up to" and basis_label(kit).startswith("the saving is an 'up to'")


def test_camelcamelcamel_drops_are_against_amazons_own_price():
    girl, tv = parse_camel(CAMEL)
    assert (girl.store, girl.terms.price, girl.terms.was, girl.terms.pct_off, girl.terms.hedge) == ("Amazon", 25.37, 29.25, 13.3, "")
    assert tv.store_url == "https://www.amazon.com/dp/B0TV000001" and basis_label(tv) == "vs Amazon's own recent price of $330.00"


def test_malformed_feeds_yield_nothing():
    assert parse_slickdeals("<html>not a feed") == [] and parse_dealnews("") == [] and parse_camel("<rss><channel/></rss>") == []


# --- matching -------------------------------------------------------------------------------------------------------

def test_model_codes_ignore_specs_and_counts():
    assert model_codes("Angel Soft 12 mega rolls") == frozenset()
    assert model_codes('Element 32" 1080P Wi-Fi 7 Monitor 2024') == frozenset()
    assert model_codes("Element EM2FPAF32B 32\" Monitor") == {"em2fpaf32b"}
    assert model_codes("DEWALT Utility Knife (DWHT10998)") == {"dwht10998"}
    assert model_codes("LEGO Icons Bonsai Tree 10281") == {"10281"}
    assert model_codes("Sony WH-1000XM5 Headphones") == {"wh1000xm5"}


def test_end_day_reads_utc_ad_ends_as_the_local_date():
    from datetime import datetime, timezone
    from plum.adapters.flipp import end_day, when
    assert end_day(when("2026-09-29T03:59:59+00:00")) == "Sep 28"           # 11:59 PM Eastern on the 28th
    assert end_day(when("2026-09-28T23:59:59-04:00")) == "Sep 28"
    assert end_day(datetime(2026, 9, 28, 18, 0, tzinfo=timezone.utc)) == "Sep 28"


def test_same_product_is_strict():
    assert same_product("Samsung U8000H 43\" 4K Smart TV", "Samsung - 43\" Class U8000H 4K UHD Smart TV")
    assert not same_product("Samsung U8000H 43\" 4K Smart TV", "Samsung U8000H 55\" 4K Smart TV")      # different size
    assert not same_product("Sony WH-1000XM5 Headphones", "Sony WH-1000XM6 Headphones")               # different model
    assert not same_product("Sony WH-1000XM5 Headphones", "Hard Case for Sony WH-1000XM5")            # an accessory
    assert not same_product("32\" 1080p Monitor", "24\" 1080p Monitor")                               # specs aren't models


# --- the service ----------------------------------------------------------------------------------------------------

async def test_online_deals_rank_filter_and_compare():
    svc, web = service()
    rep = await svc.deals(where="Austin, TX", min_pct=30)
    await svc.http.aclose()
    titles = [d.title[:22] for d in rep.deals]
    assert titles[:2] == ["The North Face Boreali", "Polo Ralph Lauren Men'"]      # 55.6% and 52.6% below other stores
    assert all((d.terms.pct_off or 0) >= 30 for d in rep.deals)
    assert rep.skipped == {"a service or membership": 1, "a sale, not one item": 3, "deal has ended": 1,
                           "posted more than 5 days ago": 1}
    tv = next(d for d in rep.deals if d.source == "camelcamelcamel" and "U8000H" in d.title)
    # The same model at Walmart (another feed) and in Best Buy's weekly ad near Austin; the U7900F is a different model
    assert [(p.store, p.price, p.source) for p in tv.elsewhere] == [
        ("Walmart", 199.0, "Slickdeals post"), ("Best Buy", 229.99, "Best Buy weekly ad")]
    assert "ad runs through Sep 28" in tv.elsewhere[1].note
    assert rep.looked_up >= 1 and rep.compared_near.postal_code == "78701"
    popular = [d.title[:14] for d in rep.popular]
    assert "DEWALT Retract" in popular and all(not d.terms.pct_off for d in rep.popular)


async def test_one_feed_down_the_rest_still_answer():
    svc, _ = service(**{"www.dealnews.com/": httpx.Response(503)})
    rep = await svc.deals()
    await svc.http.aclose()
    status = {s.name: s.ok for s in rep.sources}
    assert status == {"Slickdeals": True, "dealnews": False, "camelcamelcamel": True} and rep.deals
    assert rep.compared_near is None and "Store ads near you" not in status


def test_not_an_item():
    [costco] = [d for d in parse_dealnews(DEALNEWS) if "Membership" in d.title]
    assert not_an_item(costco) == "a service or membership"


def test_basis_labels_say_what_the_discount_is_measured_against():
    by = {d.id.split(":")[1]: d for d in parse_slickdeals(SLICK) + parse_dealnews(DEALNEWS)}
    assert basis_label(by["20050443"]) == "vs $89.98 at Amazon without the code"
    assert basis_label(by["20051439"]) == "vs a list price of $19.98"
    assert basis_label(by["22209922"]) == "vs at least $90.00 at other stores"
    assert basis_label(by["22209909"]) == "the post gives no regular price; says it saves $39.00"


async def test_rendering_api_and_cli(monkeypatch, capsys):
    svc, _ = service()
    rep = await svc.deals(where="78701")
    text = render_online(rep)
    assert "BIGGEST DISCOUNTS" in text and "Best Buy $229.99 (Best Buy weekly ad)" in text
    assert json.loads(json.dumps(jsonable(rep)))["deals"][0]["basis"].startswith("vs ")

    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from plum.api import create_app
    from plum.demo_data import build_service
    client = TestClient(create_app(build_service(), online=service()[0]))
    j = client.get("/online/deals", params={"min_pct": 50}).json()
    assert j["deals"] and all(d["terms"]["pct_off"] >= 50 for d in j["deals"])
    assert client.get("/online/deals", params={"min_pct": 150}).status_code == 422

    await svc.http.aclose()


def test_cli_online(monkeypatch, capsys):
    monkeypatch.setattr("plum.online.OnlineDealService", lambda http, **kw: service()[0])
    assert cli.main(["online", "--near", "78701", "--min", "30"]) == 0
    out = capsys.readouterr().out
    assert "BIGGEST DISCOUNTS" in out and "vs $89.98 at Amazon without the code" in out and "Looked up" in out
