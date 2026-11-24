"""A venue's own sale, read from its own page (slomp/entertainment.py, docs/DESIGN-online-stores.md 4.6). The lines
are the venues' pages as read on Nov 24, 2026, block by block."""
import asyncio
import json
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from slomp import entertainment as ent
from slomp.http import Disallowed
from slomp.reference import DATA
from slomp.sales import StoreSales, select, to_payload
from slomp.verify import sales_checks

CT = ZoneInfo("America/Chicago")
NOW = datetime(2026, 11, 24, 10, 0, tzinfo=CT)
VENUE = {"name": "Splash Park", "city": "Galveston", "site": "splashpark.example", "pages": ["https://splashpark.example/tickets/"]}


def sale(*lines, now=NOW, venue=VENUE):
    return ent.venue_sale(venue, [("https://splashpark.example/tickets/", list(lines))], now)


def offers(*lines):
    return [(o.pct if o.pct is not None else o.price, o.thing or o.kind) for o in ent.page_offers(list(lines), 2026)]


def test_a_page_is_read_block_by_block():
    page = """<html><head><title>Tickets | Splash Park</title><style>.x{color:red}</style></head><body>
      <nav><ul><li><a href="/a">Military Offers</a></li><li><a href="/b">Hotel Packages</a></li></ul></nav>
      <h2>Black Friday: Save Up to 50% on Tickets!</h2>
      <div class="tile"><h3>Single-Day Ticket</h3><div class="badge"><span>Black Friday:</span> <b>Save up to 50%</b></div>
      <p>Enjoy one visit on the date selected. See the <a href="/faq">questions</a> for more.</p></div>
      <script>var x = "Save 90% on Tickets";</script></body></html>"""
    assert ent.page_lines(page) == [
        "Tickets | Splash Park", "Military Offers", "Hotel Packages", "Black Friday: Save Up to 50% on Tickets!",
        "Single-Day Ticket", "Black Friday: Save up to 50%", "Enjoy one visit on the date selected. See the questions for more."]
    # a page its scripts build has its wording in its data, and that is read when nothing else is there
    built = '<html><body><div id="app"></div><script>window.__DATA__ = {"headline": "Get a 2027 Silver Pass for $69. Ends 11/27."};</script></body></html>'
    assert any("2027 Silver Pass for $69" in ln for ln in ent.page_lines(built))
    # in such a run of words the offer is dated by what is near it, wherever in the run it sits
    data = " ".join(["Plan your visit and see what is new this season."] * 40)
    s = sale(f"{data} Holiday Sale: save 30% on Season Passes. Offer ends December 6. {data}")
    assert (s.offer, s.title, s.ends_at.astimezone(CT).date().isoformat()) == ("30% off", "Holiday Sale: save 30% on Season Passes.", "2026-12-06")


def test_a_saving_stated_on_tickets_in_the_pages_own_words():
    s = sale("Home", "Black Friday Deals", "Save up to 55% on Tickets, Passes and More! Offer Ends Nov 30th", "Unwrap More Time Together!")
    assert (s.store_name, s.name, s.offer, s.badge, s.badge_soft) == ("Splash Park", "Black Friday Deals", "Up to 55% off", "Up to 55%", True)
    assert (s.pct, s.upto, s.what, s.industries, s.own_site) == (None, 55, "tickets", ["entertainment"], True)
    assert s.ends_at.astimezone(CT).date().isoformat() == "2026-11-30" and "the page says" in s.ends_how
    assert s.title == "Save up to 55% on Tickets, Passes and More! Offer Ends Nov 30th"
    assert s.offer_how == "splashpark.example says “Save up to 55% on Tickets, Passes and More! Offer Ends Nov 30th”"
    assert (s.source, s.source_url, s.city, s.conditions) == ("splashpark.example", "https://splashpark.example/tickets/", "Galveston", [])
    assert s.id == "sale:venue:splash-park" and s.posted_at == NOW and s.checked_at == NOW
    assert sales_checks.sale_offer(s)[0] == "pass"

    s = sale("4 Attractions for Just $49", "Black Friday Sale: 50% Off Texas Annual Pass", "Save 50%!", "Save 50%!", "Texas Annual Pass")
    assert (s.name, s.offer, s.pct, s.upto, s.badge_soft) == ("Black Friday Sale: Texas Annual Pass", "50% off", 50, None, False)
    assert s.ends_at is None and (s.event, s.event_ends_at.astimezone(CT).date().isoformat()) == ("Black Friday", "2026-11-27")

    s = sale("Membership means savings!", "Join and Save 10%!",
             "Now through Nov. 30, save 10% on membership! You'll get FREE general admission and parking, exclusive hours and "
             "events, and savings throughout the Zoo all year long. Join at the Patron level or above to see the lights for FREE.",
             "Save 10% Now")
    assert (s.name, s.offer, s.title) == ("Memberships", "10% off", "Now through Nov. 30, save 10% on membership!")
    assert s.ends_at.astimezone(CT).date().isoformat() == "2026-11-30"

    s = sale("Membership Gift Certificates", "Get 10% off * a membership gift certificate this holiday season with promo code MERRY26.")
    assert (s.offer, s.code, s.name) == ("10% off", "MERRY26", "Memberships")
    assert sales_checks.sale_offer(s)[0] == "pass"


def test_a_tile_names_the_ticket_over_or_under_its_saving():
    assert offers("Add to cart", "Single-Day Ticket", "Black Friday: Save up to 50%", "Enjoy one visit on date selected") == [(50, "Single-Day Ticket")]
    assert offers("SeaWorld 2027 Season Pass (1 Park)", "Black Friday: Save 35% + $5 in Merry Bucks",
                  "Enjoy unlimited visits with no blockout dates for all of 2027! Plus, get free general parking and up to 10% on in-park discounts.") \
        == [(35, "SeaWorld 2027 Season Pass")]
    # the was and the now sit between the name and the saving
    assert offers("Get Deal", "2027 Enchanted Hero Pass", "$145.99 $59.99", "Save 55%", "As low as $7.00/month with payment plans") \
        == [(55, "2027 Enchanted Hero Pass")]
    # a badge over the name
    assert offers("Find out more", "20% off + 2 free months", "Portal Pass Supremium", "Unlimited admission for one year to all five locations") \
        == [(20, "Portal Pass")]
    assert offers("Buy now", "15% off for a limited time", "Portal Pass", "Unlimited* admission for one year") == [(15, "Portal Pass")]
    # the same badge twice, as a page built for phones and desktops has it
    assert offers("1 fin-tastic price", "Save 50%!", "Save 50%!", "Texas Annual Pass", "Show more") == [(50, "Texas Annual Pass")] * 2
    # named on the same line
    assert offers("Any Day Ticket Black Friday: Save up to 25%") == [(25, "Any Day Ticket")]
    assert offers("Black Friday Annual Pass Sale: 25% off a Whole Year of Fun") == [(25, "Annual Pass")]
    s = sale("Offers and Exclusive Discounts", "Black Friday Annual Pass Sale: 25% off a Whole Year of Fun",
             "Big savings for our little builders - limited time only, deal ends December 1st!", "Limited-Time Offer - Online Only")
    assert (s.name, s.offer) == ("Black Friday sale: Annual Pass", "25% off")
    assert s.ends_at.astimezone(CT).date().isoformat() == "2026-12-01"          # the line under it dates it


def test_a_price_for_a_pass_when_the_page_speaks_of_a_sale():
    s = sale("Daily Tickets", "Black Friday Deal: a season of visits for the price of a day",
             "Get a 2027 Silver Pass for $69. Ends 11/27. Plus, a FREE Bring-A-Friend ticket with new passes, renewals and memberships.", "Shop Now")
    assert (s.name, s.offer, s.badge, s.pct, s.upto) == ("Black Friday sale", "2027 Silver Pass for $69", "$69", None, None)
    assert s.ends_at.astimezone(CT).date().isoformat() == "2026-11-27"
    assert sales_checks.sale_offer(s)[0] == "pass"
    # a standing price is not a sale, and a price by the month is a payment plan
    assert sale("Annual Passes", "Get a Family Pass for $495 and visit all year.") is None
    assert sale("12 Mo. Annual Passes", "Black Friday: Passes as low as $5.99/ Mo.") is None
    # a percent leads a price
    s = sale("Black Friday Sale: 50% Off Texas Annual Pass", "Get the Texas Annual Pass for just $49 this Black Friday and enjoy unlimited visits.")
    assert s.offer == "50% off"


def test_what_a_pass_holder_gets_is_not_a_sale():
    perks = [
        # SeaWorld San Antonio: a pass's benefits
        ("Valid for unlimited visits through January 2, 2028.", "Save 5% off on in-park merchandise", "Save 5% off on photo prints & framing",
         "Save 10% on Quick Queue", "Exclusive Pass Member discounted tickets", "FREE general parking", "10% off food & beverage",
         "20% off daily & all Season discounted quick queue", "Save 10% off on stroller rentals"),
        # Moody Gardens: the ticket discount is one of the member's benefits
        ("Member Benefits", "Savings Every Time You Visit",
         "15% Off any attraction ticket purchase Not valid with other coupons, discounts, special exhibits or events.",
         "20% Off at concessions and restaurants Excludes alcohol.", "10% Off at gift shops", "50% Off a photo print Must be purchased in person."),
        ("Membership Perks", "15% off any attraction ticket purchase"),
        ("Membership Benefits", "Zoo Lights Tickets", "20% off"),
        # LEGOLAND Discovery Center: for whoever comes along, and a perk that sits right over the next pass's name
        ("All Year Admission", "10% Off Birthday Parties", "10% off select items in our LEGO shop", "20% off LEGO Cafe",
         "20% off admission for friends and family who visit with you", "Valid 1 year from date of purchase"),
        ("12 Months Entry", "40% off friends & family tickets when visiting with you", "10% off LEGO Products in our Shop",
         "10% off in our Cafe", "New Pass", "$59"),
        # Meow Wolf: a table of what each pass gets
        ("Benefit", "Standard", "Supremium", "Tickets to additional Meow Wolf locations", "10% off", "FREE", "Additional guest tickets",
         "10% off", "20% off", "Discounts at any Meow Wolf gift shop & online", "10% off", "20% off"),
        # Texas Tides: bring-a-friend tickets, and add-ons that are not tickets
        ("Combo Meal 10-Pack", "Two free 2027 Bring-A-Friend tickets, plus two per month at 20% off", "View Terms & Conditions"),
        ("The 2027 Enchanted Hero Pass includes unlimited visits, Free Preferred Parking (Lot B), discounts on food & retail, one 20% off "
         "Bring-A-Friend Ticket per month and more.",),
        ("2027 All Season Drink Plan", "$36.99 $28.99", "Save 20%", "Stay cool all season."),
        ("2027 All Season Fast Lane", "$275.99 $164.99", "Save 40%"),
        # for one group of people
        ("Special Discounts Available On-Site", "20% Off", "Military Discount", "Value Pass with Valid Military ID - For Active-Duty Military Personnel"),
        ("Military Offers", "Save 30% on Tickets"),
        ("Seniors save 20% on tickets every Sunday.",),
        # the second of two, other things on sale, and goods that come with tickets
        ("Buy One, Get One 50% Off", "For a limited time, save 50% on a second General Admission ticket. *Terms and conditions apply.*"),
        ("30% Off Zoo Experiences", "From animal encounters to behind-the-scenes tours", "30% Off Kids Wild Night Out"),
        ("Black Friday: 30% OFF Room Rates at Moody Gardens Hotel 30% OFF Hotel Rooms",),
        ("Save 15% and get free shipping on all Adopt-An-Animal plush packages for the holidays! These super-soft plush animals come "
         "with two tickets to the Zoo, a customized adoption certificate, and more.",),
        ("10% off select items with your pass",),
        ("CityPASS tickets bundle Dallas Zoo admission with three more top Dallas attractions, saving you up to 56%.",),
    ]
    for lines in perks:
        assert ent.page_offers(list(lines), 2026) == [], lines
        assert sale(*lines) is None
    # ... and in one statement with a real saving, only the tickets count
    assert offers("Promos & Discounts", "Up to 20% off Portal Passes, up to 50% off tickets, and 30% off our online shop!") \
        == [(20, "Portal Passes"), (50, "Tickets")]
    # ... unless the page goes on to say that percent is off the second of two: its headline was naming a two-for
    assert offers("Promos & Discounts", "Up to 20% off Portal Passes, up to 50% off tickets, and 30% off our online shop!",
                  "Buy One, Get One 50% Off", "For a limited time, save 50% on a second General Admission ticket.") == [(20, "Portal Passes")]
    assert offers("Save up to 50% on Tickets", "Dining", "Buy one, get one 50% off entrees") == [(50, "Tickets")]      # not about tickets


def test_a_sale_that_is_over_or_left_up_is_not_shown():
    assert sale("General Admission Ticket", "40% off ends September 10, 2026", "Starting from", "$21.99") is None
    assert sale("Black Friday 2024", "Save 50% on Tickets!") is None
    assert sale("Black Friday 2026", "Save 50% on Tickets!").offer == "50% off"
    # named for a day that is not coming, with no end stated: a page left up
    december = datetime(2026, 12, 8, 10, 0, tzinfo=CT)
    assert sale("Black Friday: Save Up to 50% on Tickets!", now=december) is None
    assert sale("Black Friday: Save Up to 50% on Tickets! Offer extended through Dec 31.", now=december).offer == "Up to 50% off"
    assert sale("Holiday Sale", "Save 20% on Tickets", now=december).offer == "20% off"
    # the one that is still on leads, though a bigger one has ended
    s = sale("Summer Sale: 60% off Season Passes. Ends August 1, 2026.", "Holiday Sale", "Save 20% on Season Passes")
    assert (s.offer, s.name) == ("20% off", "Season Passes")


def test_the_biggest_saving_leads_and_says_up_to_when_it_names_no_ticket():
    s = sale("Tickets", "Black Friday: Save Up to 50% on Tickets!", "Single-Day Ticket", "Black Friday: Save up to 50%",
             "2-Day 1 Park Flex Ticket", "Black Friday: Save 40%", "Any Day Ticket", "Black Friday: Save up to 25%")
    assert (s.offer, s.name, s.title) == ("Up to 50% off", "Black Friday sale", "Black Friday: Save Up to 50% on Tickets!")   # the top of the page
    s = sale("Holiday Sale", "Save 40% on tickets", "Daily Parking", "Season Pass", "Save 25%")
    assert (s.offer, s.pct, s.upto) == ("Up to 40% off", None, 40)                 # two savings, and the bigger names no ticket
    s = sale("Black Friday Sale: 50% Off Texas Annual Pass", "Admission to SEA LIFE Aquarium + LEGOLAND Discovery Center",
             "Save up to 30% when you book both attractions together in advance!")
    assert (s.offer, s.pct, s.name) == ("50% off", 50, "Black Friday Sale: Texas Annual Pass")       # a named pass keeps its figure
    # of two pages, the one that dates the sale or names its day is the one linked
    s = ent.venue_sale(VENUE, [("https://splashpark.example/tickets/", ["Tickets", "SAVE UP TO 55% ON TICKETS, PASSES & MORE!"]),
                               ("https://splashpark.example/black-friday-deals/", ["Black Friday Deals", "Save up to 55% on Tickets, Passes and More! Offer Ends Nov 30th"])], NOW)
    assert s.source_url == "https://splashpark.example/black-friday-deals/" and s.name == "Black Friday Deals"


def test_sale_pages_are_found_from_the_page_listed():
    page = """<a href="/overtexas/black-friday-deal">Shop</a> <a href="/overtexas/special-offers">Offers</a>
              <a href="/overtexas/special-offers/military">Military</a> <a href="/overtexas/group-sales">Groups</a>
              <a href="/overtexas/events/holiday">Events</a> <a href="/fiestatexas/special-offers">Another park</a>
              <a href="https://other.example/overtexas/deals">Elsewhere</a> <a href="/overtexas/daily-tickets#top">Here</a>
              <a href="/overtexas/rides/special-events">Rides</a> <a href="/overtexas/spa/specials-packages">Spa</a>"""
    assert ent.sale_links(page, "https://www.sixflags.com/overtexas/daily-tickets") == [
        "https://www.sixflags.com/overtexas/black-friday-deal", "https://www.sixflags.com/overtexas/special-offers"]
    # a page at the top of its site may link anywhere on it
    assert ent.sale_links('<a href="/promotions">Promos</a> <a href="/about">About</a>', "https://meowwolf.com/portal-pass") == ["https://meowwolf.com/promotions"]


class Site:
    """A stand-in for the polite client: the pages it has, the ones robots.txt keeps from it, and what it was asked for."""
    def __init__(self, pages, disallowed=()):
        self.pages, self.disallowed, self.asked = pages, set(disallowed), []

    async def get(self, url, **kw):
        self.asked.append(url)
        if url in self.disallowed:
            raise Disallowed(url, "the site's robots.txt turns away AI assistants")
        html = self.pages.get(url)
        return SimpleNamespace(status=200 if html else 404, text=html or "", final_url=url, fetched_at=NOW.timestamp())


def _venues(monkeypatch):
    venues = [VENUE,
              {"name": "City Zoo", "city": "Waco", "site": "cityzoo.example", "pages": ["https://cityzoo.example/"]},
              {"name": "Quiet Museum", "city": "Austin", "site": "quiet.example", "pages": ["https://quiet.example/visit/tickets/", "https://quiet.example/visit/membership/"]},
              {"name": "Gone Park", "city": "Lubbock", "site": "gone.example", "pages": ["https://gone.example/tickets"]}]
    monkeypatch.setattr(ent, "venue_pages", lambda: venues)
    return Site({
        "https://splashpark.example/tickets/": '<h1>Tickets</h1><a href="/black-friday-deals/">Deals</a><a href="/group-sales/">Groups</a>'
                                               '<div>Member Benefits</div><div>10% off at gift shops</div>',
        "https://splashpark.example/black-friday-deals/": "<h1>Black Friday Deals</h1><h2>Save up to 55% on Tickets, Passes and More! Offer Ends Nov 30th</h2>",
        "https://quiet.example/visit/tickets/": "<h1>Tickets</h1><p>Adults $12. Children $8.</p>",
        "https://quiet.example/visit/membership/": "<h1>Membership</h1><ul><li>10% off in the museum shop</li></ul>",
    }, disallowed={"https://cityzoo.example/"})


def test_each_venues_pages_are_read_and_what_cant_be_read_is_reported(monkeypatch):
    site = _venues(monkeypatch)
    sales, sources = asyncio.run(ent.venue_sales(site, NOW))
    assert [(s.store_name, s.offer, s.source_url) for s in sales] == [("Splash Park", "Up to 55% off", "https://splashpark.example/black-friday-deals/")]
    assert sorted(site.asked) == ["https://cityzoo.example/", "https://gone.example/tickets", "https://quiet.example/visit/membership/",
                                  "https://quiet.example/visit/tickets/", "https://splashpark.example/black-friday-deals/",
                                  "https://splashpark.example/tickets/"]           # the sale page it links to, and not its group sales
    assert sources == [
        {"name": "Splash Park (its own site)", "own_site": True, "ok": True, "posts": 1},
        {"name": "City Zoo (its own site)", "own_site": True, "ok": False, "posts": 0, "error": "the site's robots.txt turns away AI assistants"},
        {"name": "Quiet Museum (its own site)", "own_site": True, "ok": True, "posts": 0},
        {"name": "Gone Park (its own site)", "own_site": True, "ok": False, "posts": 0, "error": "HTTP 404"}]


def test_the_sales_build_lists_them_under_entertainment(monkeypatch):
    site = _venues(monkeypatch)

    class Feeds:
        async def read(self, plan):
            return [], ""
    res = asyncio.run(StoreSales(Feeds(), site).run(NOW, check=False))
    assert [s.id for s in res.sales] == ["sale:venue:splash-park"]
    assert {"name": "City Zoo (its own site)", "own_site": True, "ok": False, "posts": 0,
            "error": "the site's robots.txt turns away AI assistants"} in res.sources
    assert [s.id for s in select(res, ["entertainment"], NOW)[0]] == ["sale:venue:splash-park"] and select(res, ["fashion"], NOW)[0] == []
    card = to_payload(res, ["entertainment"], NOW)["sales"][0]
    assert (card["own_site"], card["what"], card["store"], card["store_name"], card["source"], card["city"]) == \
        (True, "tickets", "", "Splash Park", "splashpark.example", "Galveston")
    # with no client there are no pages to read, and nothing else changes
    assert asyncio.run(StoreSales(Feeds(), None).run(NOW, check=False)).sales == []


def test_the_list_says_where_to_look_and_never_what_the_offer_is():
    raw = (DATA / "venue_pages.json").read_text()
    assert "%" not in raw and "$" not in raw
    venues = json.loads(raw)["venues"]
    assert len({v["name"] for v in venues}) == len(venues) >= 10
    for v in venues:
        assert v["name"] and v["city"] and v["site"] and v["pages"], v
        for url in v["pages"]:
            assert url.startswith("https://") and v["site"] in url.split("/")[2], (v["name"], url)


def test_the_checks_read_the_page_again_and_look_for_the_words_quoted(monkeypatch):
    site = _venues(monkeypatch)
    s = asyncio.run(ent.venue_sales(site, NOW))[0][0]
    for check in (sales_checks.sale_source(site, s), sales_checks.sale_store(site, s), sales_checks.sale_dates(site, s, NOW)):
        assert asyncio.run(check)[0] == "pass"
    site.pages[s.source_url] = "<h1>Deals</h1><h2>Save up to 40% on Tickets, Passes and More! Offer Ends Dec 6th</h2>"
    verdict, det = asyncio.run(sales_checks.sale_source(site, s))
    assert verdict == "fail" and det["why"].startswith("the page no longer says 'Save up to 55%")
    del site.pages[s.source_url]
    assert asyncio.run(sales_checks.sale_source(site, s))[1]["why"] == "the page was removed (404)"
