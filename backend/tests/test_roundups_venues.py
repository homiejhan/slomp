"""The day-of-week roundup pages' parsers, and the lookup that places a chain on the map."""
from datetime import date

from slomp.reference import city, fold
from slomp.sources.roundups import page_modified, parse_edd, parse_kcl, sentences
from slomp.sources.venues import Venues

KCL_PAGE = """<html><head><script type="application/ld+json">{"@type":"Article","datePublished":"2023-01-19T23:59:00.000Z",
"dateModified":"2026-09-30T11:09:00.000Z"}</script></head><body>
<h2>What's on this page:</h2><ul><li>Limited-Time Wednesday Food Deals</li></ul>
<h2>Limited-Time Wednesday Food Deals</h2><ul>
<li> <p> <b>Schlotzsky&#39;s</b>: Enjoy BOGO calzones, flatbreads, and pizzas at <a href="https://www.schlotzskys.com/">Schlotzsky&#39;s</a>
 on Wednesdays and save about $10. </p> </li>
<li><p><b>Oct. 3 - 4</b>: A date where the chain's name should be.</p></li></ul>
<h2>Every-Wednesday Food Deals</h2><ul>
<li><p><a href="https://www.buffalowildwings.com/promos/">Buffalo Wild Wings (B'Dubs)</a>: Get BOGO boneless wings at Buffalo Wild Wings.</p></li></ul>
<h3>Weekend Food Deals</h3><ul>
<li><p><b>Wendy's</b>: This fall, Wendy's has several college football deals available on Saturdays only.</p></li>
<li><p><b>Carrabba's</b>: Get a dinner for two for $45 this weekend only at Carrabba's.</p></li></ul>
<h2>You may also like</h2><ul><li>Amazon: Prime Big Deal Days is Oct. 6-7, here is what to know about it.</li></ul></body></html>"""

EDD_PAGE = """<html><head><meta property="article:modified_time" content="2026-10-01T11:18:55+00:00"></head><body>
<h1>Tuesday Restaurant Specials And Deals</h1>
<h2>What are the best Tuesday restaurant deals going right now?</h2><p>Some of our favorite Tuesday restaurant deals are many.</p>
<h2>Arby’s</h2><p>Arby’s coupons are available every day in the Arby’s app.</p>
<h2>Buffalo Wild Wings</h2><p>Buffalo Wild Wings has buy one order of wings, get one free on Tuesdays and Thursdays. On Tuesdays,
buy a 6, 10 or 15 piece order of traditional wings and get another order free. Dine-in only. On Thursdays, buy one order of
boneless wings and get another free. For more details see our story.</p>
<p>Buffalo Wild Wings has a Pick 6 Meal for Two for $19.99 good every day.</p>
<h2>Chuck E. Cheese</h2><p>Chuck E. Cheese has Two for Tuesdays pizza deals and more specials. Every Tuesday at participating
Chuck E. Cheese locations buy one large pizza and get another for half price.</p>
<h2>Cracker Barrel</h2><p><strong>Cracker Barrel</strong> has lunch and dinner deals every weekday.</p>
<ul><li>Every Day: Purchase any regular priced entree and take home a meal for just $5</li>
<li>Tuesdays &#x2013; Meatloaf $9.49 lunch.</li><li>Thursdays &#x2013; Turkey N&#x2019; Dressing $9.99 lunch, $13.79 dinner.</li></ul>
<h2>Applebee’s</h2><p>Nothing about that day here.</p></body></html>"""


def test_kcl_lists_by_section():
    rows = parse_kcl(KCL_PAGE, 2, "https://example.test/wednesday")
    got = [(r.brand, r.section, r.day) for r in rows]
    assert got == [("Schlotzsky's", "limited", 2), ("Buffalo Wild Wings", "every", 2), ("Wendy's", "weekend", 5),
                   ("Carrabba's", "weekend", 5), ("Carrabba's", "weekend", 6)]
    assert rows[0].modified == date(2026, 9, 30) and rows[0].brand_url == "https://www.schlotzskys.com/"
    assert rows[0].text.startswith("Enjoy BOGO calzones") and rows[0].source_name == "The Krazy Coupon Lady"


def test_edd_keeps_the_sentences_about_the_pages_day():
    listed = parse_edd(EDD_PAGE, 1, "https://example.test/tuesday")
    rows = {r.brand: r for r in listed}
    # the question heading and Applebee's are out; a chain's bulleted day list gives its Tuesday item only
    assert set(rows) == {"Arby’s", "Buffalo Wild Wings", "Chuck E. Cheese", "Cracker Barrel"}
    assert [r.text for r in listed if r.brand == "Cracker Barrel"] == [
        "Tuesdays – Meatloaf $9.49 lunch.", "Cracker Barrel has lunch and dinner deals every weekday."]   # no offer: dropped later
    bww = rows["Buffalo Wild Wings"].text
    assert "On Tuesdays, buy a 6, 10 or 15 piece" in bww and "Dine-in only." in bww
    assert "On Thursdays" not in bww and "For more details" not in bww
    assert rows["Chuck E. Cheese"].text.startswith("Chuck E. Cheese has Two for Tuesdays")   # "E." does not end a sentence
    assert rows["Arby’s"].modified == date(2026, 10, 1)


def test_edd_keeps_a_longer_sentence_that_restricts_the_offer():
    # regulars run 1: "You can only get the special for dine-in orders, not to-go or delivery." is 71 characters, one over
    # the follow-on limit, so the dine-in rule never reached the card
    page = """<html><head><meta property="article:modified_time" content="2026-10-01T11:18:55+00:00"></head><body>
    <h2>Bonefish Grill</h2><p>Bang Wednesdays are back at Bonefish Grill, with the iconic Bang Bang Shrimp on special for
    just $7. That’s about $5 off the normal price, depending on your location. You can only get the special for dine-in
    orders, not to-go or delivery. Bonefish announced the Bang Bang Shrimp special on Facebook (see announcement below).</p>
    <h2>Marco’s Pizza</h2><p>Marco’s Pizza has a buy one, get one free offer on Wednesdays plus more pizza deals. Start at
    the Marco’s Menu Page. On Wednesdays you should see a BOGO item. You’ll need to be signed into your Marco’s account and
    select a location, then click on Hot Deals to see the deals. Marco's pizza is made with dough made fresh in store every
    single morning by people who care a great deal about pizza and about you and about dough.</p></body></html>"""
    rows = {r.brand: r.text for r in parse_edd(page, 2, "https://example.test/wednesday")}
    assert rows["Bonefish Grill"].endswith("You can only get the special for dine-in orders, not to-go or delivery.")
    assert rows["Marco’s Pizza"].endswith("then click on Hot Deals to see the deals.")       # the long aside after it is not kept


def test_edd_keeps_a_restriction_a_sentence_or_two_after_the_offer_and_the_sections_opening_sentence():
    page = """<html><head><meta property="article:modified_time" content="2026-10-01T11:18:55+00:00"></head><body>
    <h2>Sonic Drive-In</h2><p>Sonic Drive-In has $2 Snacks for rewards members every day from 2-5PM now through November 1,
    2026. Included items are a Corn Dog, small Mozzarella Sticks, small Tots, small Premium Chicken Bites, and small Groovy
    Fries. Redeem online or in the Sonic app as a registered user from 2-5pm local time. The deal is posted on the Sonic
    Rewards page. Sonic also has a $1.99 Menu good every day. Redeem that one however you like, it is a different offer.</p>
    <h2>IKEA Restaurant</h2><p>IKEA Family members can enjoy special IKEA Restaurant deals most days. On Tuesdays at IKEA get
    any adult entree for half price. For more details see the IKEA Foods page.</p></body></html>"""
    rows = {r.brand: r for r in parse_edd(page, 1, "https://example.test/tuesday")}
    sonic = rows["Sonic Drive-In"].text
    assert "Redeem online or in the Sonic app" in sonic and "Included items" not in sonic
    assert "different offer" not in sonic                      # what follows "also has" belongs to the other offer
    assert rows["IKEA Restaurant"].text.startswith("On Tuesdays at IKEA")
    assert rows["IKEA Restaurant"].context == "IKEA Family members can enjoy special IKEA Restaurant deals most days."


def test_edd_list_items_keep_the_paragraph_that_introduces_them():
    page = """<html><head><meta property="article:modified_time" content="2026-10-01T11:18:55+00:00"></head><body>
    <h2>Whole Foods</h2><p><strong>Whole Foods</strong> has deals on takeout meals on Tuesdays and Fridays. Here is the
    lineup of weekday deals at Whole Foods; these deals are good only for Prime members.</p>
    <ul><li>Tuesdays: $2 off Rotisserie Chicken; buy 1, get 1 for 50% off individual meals</li>
    <li>Fridays: Oysters 12 for $12; Large 1-topping pizza $12, Sushi Rolls buy 1, get 1 50% off</li></ul>
    <p>For more deals like these see: Whole Foods Savings</p></body></html>"""
    items = [r for r in parse_edd(page, 1, "https://example.test/tuesday") if r.text.startswith("Tuesdays:")]
    assert len(items) == 1 and "good only for Prime members" in items[0].context


def test_sentences_and_page_dates():
    assert sentences("P.F. Chang's has a happy hour. It runs until 5 p.m. Tuesday. Dine-in only.") == \
        ["P.F. Chang's has a happy hour.", "It runs until 5 p.m. Tuesday.", "Dine-in only."]
    assert page_modified("<html>no dates</html>") is None


def test_chains_as_deal_pages_spell_them():
    v = Venues()
    name = lambda n: getattr(v.find(n), "name", None)                                            # noqa: E731
    assert name("Schlotzsky’s") == "Schlotzsky's" and name("KFC") == "KFC"
    assert name("BJ’s Restaurant & Brewhouse") == name("BJ’s Restaurants") == "BJ's Restaurant & Brewhouse"
    assert name("Freebirds World Burrito") == "Freebirds" and name("Sonic Drive-In") == "Sonic Drive-In"
    assert name("Applebee’s") == "Applebee's" and name("Cheesecake Factory") == "The Cheesecake Factory"
    assert name("Top Golf") == "Topgolf" and name("AMC Theatres") == "AMC" and name("Rosa's Cafe") == "Rosa's Café"
    assert len(v.find("Taco Bell").locations) > 100                 # not "Taco Bell Cantina", which shares the name
    assert name("Jack’s Family Restaurants") is None and name("Ruby Tuesday") is None and name("DoorDash") is None
    assert v.find("Cinemark").kind == "cinema" and v.find("Cinemark").industries == ("entertainment",)
    assert v.find("Kohl's").kind == "store" and v.find("Goodwill").industries == ("fashion", "home")
    assert fold("Cinépolis") == fold("Cinepolis") == "cinepolis"


def test_nearest_branch_and_regional_operators():
    v = Venues()
    near = v.nearest(v.find("Schlotzsky's"), city("austin"))
    assert near.distance_mi < 10 and near.source == "osm" and near.merchant == "Schlotzsky's"
    area = {"lat": 30.2672, "lon": -97.7431, "mi": 40}
    assert v.nearest(v.find("Goodwill"), city("austin"), area).distance_mi < 5
    assert v.nearest(v.find("Goodwill"), city("houston"), area).distance_mi > 100   # Houston's Goodwill is another operator
    assert v.nearest(v.find("Goodwill"), city("houston")).distance_mi < 10


def test_a_branch_the_chains_own_locator_no_longer_lists_is_not_shown_as_the_nearest():
    # The map still has Buca di Beppo at 3612 Tudor Blvd, Austin; the chain's locator lists Dallas, Frisco, Southlake
    # and Shenandoah. Found when every deal's branch was checked against the chains' locators after regulars run 1.
    from slomp.sources import venues
    V = Venues()
    austin = city("austin")
    key = V.find("Buca di Beppo").key
    mapped = Venues.nearest(venues._chains(False)[0][key], austin)
    listed = Venues.nearest(V.find("Buca di Beppo"), austin)
    assert mapped.distance_mi < 10 and listed.distance_mi > 100
    # a locator that looks incomplete is not used: Jack in the Box's has 16 branches near Texas against 504 on the map
    assert "Jack in the Box" not in venues._unlisted()
    assert len(V.find("Jack in the Box").locations) == len(venues._chains(False)[0][V.find("Jack in the Box").key].locations)
