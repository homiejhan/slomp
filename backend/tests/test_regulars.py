"""Regular deals: reading offers and conditions, turning roundup entries into regular deals, merging, evidence checks,
and what a search returns. Sentences are quoted from the live pages of Oct 5, 2026."""
import asyncio
import json
import time
from collections import Counter
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from slomp.config import Settings
from slomp.db import Store
from slomp.http import Blocked, Response
from slomp.reference import city
from slomp.regulars import (Regulars, check_key, find_phrases, from_entry, from_listing, merge, offer_terms, page_texts,
                           regular_conditions, status_text)
from slomp.sources.roundups import Listing
from slomp.sources.venues import Venues

TODAY = date(2026, 10, 5)                      # a Monday
V = Venues()
KCL_WED = "https://thekrazycouponlady.com/tips/money/wednesday-food-deals"
EDD = "https://www.eatdrinkdeals.com/daily-deals-{}-restaurant-specials/"


def kcl(day, brand, text, section="every", modified=date(2026, 9, 30)):
    return Listing("kcl", KCL_WED, day, brand, text, section, modified)


def edd(day, brand, text, modified=date(2026, 10, 2)):
    return Listing("edd", EDD.format(day), day, brand, text, "every", modified)


# --- the offer ------------------------------------------------------------------------------------------------------
def test_buy_one_get_one_in_its_wordings():
    assert (offer_terms("Get BOGO traditional wings at Buffalo Wild Wings.").bogo, offer_terms("BOGO wings").pct) == \
        ("buy 1 get 1 free", 50.0)
    t = offer_terms("Every Tuesday at participating locations buy one large pizza and get another for half price.")
    assert (t.bogo, t.pct, t.basis) == ("buy 1 get 1 50% off", 25.0, "store_regular")
    assert offer_terms("On Tuesdays at Bertucci's, buy one pizza and get one free.").bogo == "buy 1 get 1 free"


def test_percent_and_half_price():
    t = offer_terms("rewards members can grab half-price Sonic cheeseburgers (menu price $4.99) after 5 p.m.")
    assert (t.pct, t.regular, t.summary) == (50.0, 4.99, "half price") and abs(t.price - 2.5) < 0.011
    assert offer_terms("Save 40% on boneless and traditional wings every Tuesday all day long.").pct == 40.0
    t = offer_terms("Participating Cinemark theatres offer up to 50% off movie tickets on Discount Tuesdays.")
    assert (t.pct, t.hedge, t.summary) == (50.0, "up to", "up to half price")
    assert offer_terms("100% beef burgers for $5").pct is None


def test_price_with_and_without_a_regular_price():
    t = offer_terms("Rewards members can enjoy a $5.99 adult pizza buffet (reg. $9.99) at Cicis Pizza with an in-app coupon.")
    assert (t.price, t.regular, t.pct, t.basis) == (5.99, 9.99, 40.0, "store_regular")
    # a regular price for a different quantity is not a reference, and prices inside it are not the deal price
    t = offer_terms("guests can score 24 nuggets (reg. $7.99 for a 12-count) and four sauces (reg. $0.30 each) at KFC for $10.")
    assert (t.price, t.pct, t.summary) == (10.0, None, "$10")
    assert offer_terms("Grab Turkey n' Dressing for $14.49+ for lunch at Cracker Barrel on Thursdays.").price == 14.49
    assert offer_terms("Get $0.70 boneless wings on Mondays at Wingstop.").price == 0.7
    # the price comes before "that's $4 - $5 off": it is the offer
    t = offer_terms("get personal sized pizzas for just $5 at Schlotzsky's. That's $4 - $5 off the normal price, generally.")
    assert (t.price, t.savings) == (5.0, None)
    assert offer_terms("drinks starting at $5 and more specials").hedge == "starting at"


def test_free_things():
    t = offer_terms("Get a FREE appetizer (up to an $11.49 value) with a purchase of $30 or more on Mondays at Logan's Roadhouse.")
    assert (t.summary, t.price) == ("free appetizer", None)
    assert offer_terms("Score a free 6-piece Nuggs at Wendy's every Wednesday when you make an in-app purchase of $5 or more.") \
        .summary == "free 6-piece nuggs"
    assert offer_terms("Jack in the Box offers 2 free tacos with any other purchase on Tuesdays.").summary == "free tacos"
    assert offer_terms("Kids eat free on Sundays at Freebirds World Burrito.").summary == "kids eat free"
    assert offer_terms("members can upsize their 20-ounce smoothie to a 32-ounce for free at Smoothie King every Friday.") \
        .summary == "free item"


def test_conditions():
    c = regular_conditions("Every Tuesday, rewards members can grab half-price Sonic cheeseburgers (menu price $4.99) when "
                           "you order online or in-app after 5 p.m. local.")
    assert c == ["rewards members", "online or in the app"]
    assert regular_conditions("Offer is valid for dine-in only.") == ["dine-in only"]
    assert regular_conditions("Offer valid online, in-app, and in-store.") == []
    assert regular_conditions("Valid for dine-in orders.") == ["dine-in only"]            # " orders" is not " or ..."
    assert regular_conditions("Valid for dine-in or takeout.") == []
    assert "code BOGOWINGS" in regular_conditions("Use promo code BOGOWINGS during online or in-app checkout.")
    c = regular_conditions("Kids 12 and under also eat free after 5 p.m. when you dine in and purchase a full-priced adult entree. "
                           "Limit one per transaction.")
    assert {"kids 12 and under", "dine-in only", "limit 1"} <= set(c)
    assert regular_conditions("Good at participating Chuck E. Cheese locations.") == ["participating locations"]
    assert "age 55+" in regular_conditions("Available daily after 3:00 p.m. For ages 55 and up; ID required")
    # an audit of every list deal after regulars run 1 found these wordings unread
    assert regular_conditions("the $7.45 Sub of the Day in-app deal. This offer is valid for in-app orders only.") == ["in the app"]
    assert regular_conditions("sign into your rewards account on the Quiznos app") == ["in the app", "signed in to an account"]
    assert regular_conditions("Pulled Pork Sandwich for $4.99; good for in-store orders only.") == ["in store only"]
    assert regular_conditions("2 free tacos with any other purchase on Tuesdays to Jack Pack members that order online or in "
                              "the app.") == ["rewards members", "with a purchase", "online or in the app"]
    assert regular_conditions("Get a FREE appetizer (up to an $11.49 value) with a purchase of $30 or more on Mondays") == \
        ["with a $30 purchase"]
    assert regular_conditions("for just $6.95 at select World of Beer locations on Mondays") == ["participating locations"]
    assert regular_conditions("You'll have to use the mobile app or order online and use promo code BOWLRUSH for the deal.") == \
        ["online or in the app", "code BOWLRUSH"]
    assert regular_conditions("Two Buck Shuck oysters on the half shell, a bar special for $2") == ["at the bar"]


# --- roundup entries ------------------------------------------------------------------------------------------------
def test_a_roundup_entry_becomes_a_regular_deal_on_the_pages_day():
    r = from_listing(kcl(2, "Schlotzsky's", "Enjoy BOGO calzones, flatbreads, and pizzas, including the BBQ Chicken & Jalapeno "
                         "pizza, at Schlotzsky's on Wednesdays and save about $10.", "limited"), V, TODAY)
    assert (r.brand, r.schedule.days, r.terms.bogo, r.status, r.industries) == \
        ("Schlotzsky's", [2], "buy 1 get 1 free", "listed", ["dining"])
    assert status_text(r) == "Listed by The Krazy Coupon Lady" and r.evidence[0].page_date == date(2026, 9, 30)
    # a sentence with no day in it still belongs to its page's day
    r = from_listing(kcl(1, "Buffalo Wild Wings (B'Dubs)", "Get BOGO traditional wings at Buffalo Wild Wings . Offer is available "
                         "for online and dine-in orders."), V, TODAY)
    assert (r.brand, r.schedule.days) == ("Buffalo Wild Wings", [1])
    assert r.offer.startswith("Get BOGO traditional wings at Buffalo Wild Wings. Offer")       # no space before the stop


def test_a_lead_in_sentence_is_neither_the_offer_nor_the_schedule():
    r = from_listing(edd(4, "BJ's Restaurants", "BJ's Restaurant has daily specials good every day. On Fridays through Sundays "
                         "get a Prime Rib dinner for $35.99."), V, TODAY)
    assert (r.schedule.days, r.offer, r.terms.price) == ([4, 5, 6], "On Fridays through Sundays get a Prime Rib dinner for $35.99.",
                                                         35.99)


def test_the_next_offers_hours_are_not_this_offers_hours():
    r = from_listing(edd(0, "Red Lobster", "Red Lobster has a $25 Endless Shrimp special on Mondays. Red Lobster posted the weekday "
                         "deals on their Specials page. Red Lobster Happy Hour is Mon-Fri 3-6 pm with $2 off appetizers."), V, TODAY)
    assert (r.schedule.days, r.schedule.windows, r.terms.price) == ([0], [], 25.0)
    assert "Happy Hour" not in r.offer
    # ...but a sentence that only qualifies the offer keeps its time
    r = from_listing(edd(6, "Perry's Steakhouse", "Perry's Steakhouse has a three-course Pork Chop Dinner every Sunday for the "
                         "special price of $49. The Perry's Sunday special is good from 4 pm to close."), V, TODAY)
    assert r.schedule.time_text() == "after 4 pm"


def test_a_later_sentence_that_restricts_the_offer_counts():
    # regulars run 1, R-TXT: "dine-in only" sat two sentences after the offer, past a "$5 off" remark, and was lost
    r = from_listing(edd(2, "Bonefish Grill", "Bang Wednesdays are back at Bonefish Grill, with the iconic Bang Bang Shrimp on "
                         "special for just $7. That's about $5 off the normal price, depending on your location. You can only "
                         "get the special for dine-in orders, not to-go or delivery. Bonefish announced the Bang Bang Shrimp "
                         "special on Facebook (see announcement below). Bonefish Grill also has an every day happy hour with "
                         "specials like $7 cocktails. Bonefish happy hour specials are available only in the bar area."),
                     V, TODAY)
    assert (r.terms.price, r.conditions) == (7.0, ["dine-in only"])            # the happy hour's bar rule is not this deal's
    assert r.offer == "Bang Wednesdays are back at Bonefish Grill, with the iconic Bang Bang Shrimp on special for just $7."
    # regulars run 1, R-TXT: the account the deal needs was named four sentences on; "Start at ..." was shown as the offer
    r = from_listing(edd(1, "Marco's Pizza", "Marco's Pizza has a buy one, get one free offer on Tuesdays plus more pizza deals. "
                         "Start at the Marco's Menu Page. From there click on Hot Deals to see the latest pizza specials; on "
                         "Tuesdays you should see a BOGO Tuesday item. You'll need to be signed into your Marco's account and "
                         "select a location, then click on Hot Deals to see the deals. Read our story on Marco's Pizza deals to "
                         "learn about other promo codes and deals available every day."), V, TODAY)
    assert (r.terms.bogo, r.conditions) == ("buy 1 get 1 free", ["signed in to an account"])
    assert r.offer == "Marco's Pizza has a buy one, get one free offer on Tuesdays plus more pizza deals."
    # a restriction on another day's offer is not this one's
    r = from_listing(edd(0, "Chili's", "Get a $6 Margarita of the Month on Mondays. On Tuesdays kids eat free. The offer is "
                         "valid for dine-in only."), V, TODAY)
    assert r.conditions == []
    assert regular_conditions("Happy hour is at the bar only, Monday to Friday.") == ["at the bar only"]
    assert regular_conditions("The offer is valid all day long at the bar - mention the special.") == ["at the bar"]


def test_another_offers_hours_in_the_same_entry_are_not_borrowed():
    # found reading every list deal after regulars run 1
    r = from_listing(edd(0, "Bar Louie", "Bar Louie has $8 martinis on Mondays plus Happy Hour specials from 3-6 pm."), V, TODAY)
    assert (r.schedule.days, r.schedule.time_text(), r.terms.price) == ([0], "", 8.0)       # all day, not 3-6 pm
    r = from_listing(edd(0, "Grimaldi's Pizzeria", "Grimaldi's Pizzeria has a Social Hour with discounted drinks from 3-5 pm "
                         "daily, plus lunch specials. Get a pizza lunch for just $10.99 on weekdays. The Grimaldi's ASAP Quick "
                         "Lunch is available 11 am - 3 pm Mondays through Fridays."), V, TODAY)
    assert (r.schedule.days, r.schedule.time_text(), r.terms.price) == ([0, 1, 2, 3, 4], "11 am–3 pm", 10.99)
    assert r.offer.startswith("Get a pizza lunch")
    # the lead-in is not shown, but who it says may have the deal still counts
    r = from_listing(edd(3, "IKEA", "IKEA Family members can enjoy special IKEA Restaurant deals every weekday at most "
                         "locations. On Thursdays at IKEA, seniors get 20% off all entrees."), V, TODAY)
    assert (r.offer, r.schedule.days) == ("On Thursdays at IKEA, seniors get 20% off all entrees.", [3])
    assert {"rewards members", "participating locations"} <= set(r.conditions)


def test_conditions_the_full_audit_found_missing():
    # after regulars run 1 a blind judge read every card against its source; these were the conditions left off
    def cond(day, brand, text, context=""):
        x = Listing("edd", EDD.format(day), day, brand, text, "every", date(2026, 10, 2), "", context)
        return from_listing(x, V, TODAY).conditions
    assert cond(6, "Shake Shack", "Get a free Chicken Shack sandwich on Sundays at Shake Shack. Order online, with the app, or "
                "in-store at the kiosk, sign into your account, add $10 in other purchases and add the Chicken Shack. At "
                "checkout enter promo code SHACKSUNDAY.") == ["signed in to an account", "code SHACKSUNDAY", "with a $10 purchase"]
    assert "at the bar" in cond(0, "Cheesecake Factory", "The Cheesecake Factory has Happy Hour specials at most locations with "
                                "appetizers and small plates starting at about $10 on weekdays. Typical times for The Cheesecake "
                                "Factory happy hour are 4 pm - 6 pm Mondays through Fridays in the bar.")
    assert cond(1, "Main Event", "Get a Kids Eat Free deal every Tuesday at Main Event. Get one free kid meal per $11.99 food item "
                "purchase. Valid all day, every Tuesday.") == ["with a $11.99 purchase"]
    assert cond(2, "Huddle House", "Huddle House has a free waffle every Wednesday. Get a free waffle with a minimum $6 entree "
                "purchase.") == ["with a $6 purchase"]
    assert "dine-in only" in cond(2, "Outback Steakhouse", "Outback Steakhouse has a Walkabout Wednesday meal deal. For $13.99, get "
                                  "a 6 oz. Sirloin Steak, fries and a 16 oz. Draft Beer. Fine print: *Available for dine-in on "
                                  "Wednesdays only. Limited time offer.")
    assert cond(6, "Dickey's BBQ", "Dickey's Barbecue has a kids eat free deal every Sunday. Use code KEFOLO at online checkout or "
                "ask your server for the deal when ordering. One kids meal per check with a minimum $12 purchase.") == \
        ["code KEFOLO", "with a $12 purchase", "limit 1"]
    assert cond(0, "Sonic Drive-In", "Sonic Drive-In has $2 Snacks for rewards members every day from 2-5PM now through November "
                "1, 2026. Redeem online or in the Sonic app as a registered user from 2-5pm local time.") == \
        ["rewards members", "online or in the app"]
    assert cond(2, "Red Lobster", "Red Lobster has a $25 Steak and Lobster deal on Wednesdays. Get a Maine lobster tail paired "
                "with a 7-oz. sirloin and choice of side for just $25. Dine-in only. Red Lobster posted the deal on the Red "
                "Lobster Deals website.") == ["dine-in only"]
    # the section's opening sentence says who the deals are for
    assert cond(1, "IKEA Restaurant", "On Tuesdays at IKEA get any adult entree for half price.",
                "IKEA Family members can enjoy special IKEA Restaurant deals most days.") == ["rewards members"]


def test_what_only_some_branches_offer_is_too_vague_to_show():
    assert from_listing(edd(6, "Bar Louie", "Bar Louie has brunch specials on Saturdays and Sundays from open - 3 PM. Enjoy it "
                            "just a little more with Mimosa specials! Some spots offer $3 Mimosas."), V, TODAY) == \
        "no concrete offer stated"


def test_two_lists_describing_one_deal_pool_their_conditions():
    # the second audit: the card kept the first list's wording and lost what only the second list says
    a = from_listing(kcl(2, "Logan's Roadhouse", "On Wednesdays, you can grab a mesquite-grilled steak, two sides, and a soft "
                         "drink for $12.99 at Logan's Roadhouse."), V, TODAY)
    b = from_listing(edd(2, "Logan's Roadhouse", "Get a 6 oz. Sirloin, two sides and a soft drink for only $12.99 on Wednesdays "
                         "at Logan's Roadhouse. The offer is available for dine-in orders only."), V, TODAY)
    (card,) = merge([a, b], Counter())
    assert card.conditions == ["dine-in only"] and status_text(card) == "Listed by 2 deal sites"
    # ...and where the two lists disagree on how to order, the restriction carries the name of the list that states it
    a = from_listing(kcl(1, "Buffalo Wild Wings", "Get BOGO traditional wings at Buffalo Wild Wings. Offer is available for "
                         "online and dine-in orders."), V, TODAY)
    b = from_listing(edd(1, "Buffalo Wild Wings", "On Tuesdays, buy a 6, 10 or 15 piece order of traditional wings and get "
                         "another order free. Dine-in only."), V, TODAY)
    (card,) = merge([a, b], Counter())
    assert card.conditions == ["dine-in only, says EatDrinkDeals (The Krazy Coupon Lady differs)"]
    a = from_listing(kcl(3, "Buffalo Wild Wings", "Get BOGO free boneless wings every Thursday at Buffalo Wild Wings when you "
                         "order takeout or delivery."), V, TODAY)
    b = from_listing(edd(3, "Buffalo Wild Wings", "On Thursdays, buy one order of boneless wings and get another free. Offer "
                         "valid for dine-in or for takeout/delivery thru BWW web/app."), V, TODAY)
    (card,) = merge([a, b], Counter())
    assert card.conditions == ["takeout or delivery, says The Krazy Coupon Lady (EatDrinkDeals differs)"]
    assert regular_conditions("a $10 bucket of the day on weekdays when you order online or with the KFC app") == \
        ["online or in the app"]
    assert regular_conditions("Valid for dine-in, to-go and delivery (delivery has additional charges).") == []
    # a sentence about all weekdays backs each weekday's card with what that sentence says
    wed = from_listing(kcl(2, "KFC", "Each week, KFC offers 10 wings (comes with two sauces) for $10 on Wednesdays."), V, TODAY)
    all_week = from_listing(edd(0, "KFC", "KFC has a $10 bucket of the day on weekdays, a 2 pc Taste of KFC meal for $5.99 and "
                                "more deals when you order online or with the KFC app."), V, TODAY)
    card = next(k for k in merge([wed, all_week], Counter()) if k.schedule.days == [2])
    assert card.conditions == ["online or in the app"]
    assert regular_conditions("Wednesdays - Broccoli Cheddar Chicken $9.99 lunch, $12.99 dinner.") == \
        ["$9.99 at lunch, $12.99 at dinner"]


def test_an_offer_good_on_one_date_ends_on_it():
    # "every Wednesday ... Offer valid on Sept. 30." was shown on Oct 5 as an every-Wednesday deal
    text = ("Wayback Burgers Rewards members can get up to two free kids' meals when you purchase up to two double burgers or "
            "sandwiches every Wednesday. Select the reward at checkout to have the discount applied. Offer valid on Sept. 30.")
    assert from_listing(kcl(2, "Wayback Burgers", text, "limited"), V, TODAY) == "past its stated end date"
    assert not isinstance(from_listing(kcl(2, "Wayback Burgers", text.replace("Sept. 30", "Oct. 7"), "limited"), V, TODAY), str)


def test_hours_that_differ_by_day_are_not_shown_as_one_set_of_hours():
    r = from_listing(edd(3, "Dave & Buster's", "Dave & Buster's has a Happy Hour every day but Saturday with drinks starting at $5 "
                         "and more specials. The typical Dave & Buster's happy hour is Monday - Thursday from 4-7 pm and 10 pm - "
                         "midnight, Fridays 4 - 7 pm, and Sundays 10 pm to midnight."), V, TODAY)
    assert (r.schedule.time_text(), "hours differ by day" in r.conditions) == ("", True)
    assert r.schedule.days == [0, 1, 2, 3, 4, 6]


def test_the_same_offer_worded_for_two_days_is_two_cards_each_with_its_own_day():
    # merged into one card that read "on Mondays" and ran "Mondays and Tuesdays"
    mon = from_listing(kcl(0, "Wingstop", "Get $0.70 boneless wings on Mondays at Wingstop."), V, TODAY)
    tue = from_listing(kcl(1, "Wingstop", "Enjoy $0.70 boneless wings on Tuesdays at Wingstop."), V, TODAY)
    kept = merge([mon, tue], Counter())
    assert sorted((k.schedule.days, k.offer[:6]) for k in kept) == [([0], "Get $0"), ([1], "Enjoy ")]


def test_a_list_items_conditions_come_from_the_paragraph_that_introduces_the_list():
    x = Listing("edd", EDD.format(1), 1, "Whole Foods", "Tuesdays: $2 off Rotisserie Chicken; buy 1, get 1 for 50% off "
                "individual meals", "every", date(2026, 10, 2), "",
                "Whole Foods has deals on takeout meals on Tuesdays and Fridays. Here is the lineup of weekday deals at Whole "
                "Foods; these deals are good only for Prime members.")
    r = from_listing(x, V, TODAY)
    assert (r.brand, r.schedule.days, r.conditions, r.industries) == ("Whole Foods Market", [1], ["Prime members"], ["grocery"])


def test_an_offer_introduced_as_every_day_is_not_one_days_deal():
    # shown as "Every Saturday": the sentence before the price says it is available every day
    r = from_listing(edd(5, "Red Lobster", "Endless Shrimp is available every day at Red Lobster. Get all-you-can eat shrimp "
                         "for $24.99 at most locations."), V, TODAY)
    assert r.suppress == "an everyday offer, not tied to a day or time" and len(r.schedule.days) == 7
    # ...but an offer that names its own days keeps them, whatever the lead-in says
    r = from_listing(edd(4, "BJ's Restaurants", "BJ's Restaurant has daily specials good every day. On Fridays through Sundays "
                         "get a Prime Rib dinner for $35.99."), V, TODAY)
    assert (r.suppress, r.schedule.days) == ("", [4, 5, 6])


def test_a_sentence_listing_several_offers_gives_each_day_only_its_own():
    # shown as "$1 on Tuesdays and Thursdays": the $1 is the every-day menu's, and the taco specials carry no figure
    assert from_listing(edd(1, "Del Taco", "Del Taco has a new every day Value Menu starting at $1, taco specials on Tuesdays "
                            "and Thursdays, and more deals."), V, TODAY) == "no concrete offer stated"
    r = from_listing(edd(0, "Dave & Buster's", "Dave & Buster's has happy hour specials, $1 wings on Mondays, half-priced games "
                         "on Sundays-Thursdays and more deals."), V, TODAY)
    assert (r.offer, r.schedule.days, r.terms.price) == ("$1 wings on Mondays", [0], 1.0)
    # one schedule, however many commas: the sentence stands whole
    r = from_listing(edd(1, "Buffalo Wild Wings", "On Tuesdays, buy a 6, 10 or 15 piece order of traditional wings and get "
                         "another order free."), V, TODAY)
    assert r.offer.startswith("On Tuesdays, buy a 6, 10 or 15 piece") and r.schedule.days == [1]


def test_a_list_does_not_add_days_to_an_offer_the_company_dates_exactly():
    # Dave & Buster's page: half-price games "every Wednesday & Sunday"; a list said "Sundays-Thursdays"
    games = from_entry({"id": "db-games", "brand": "Dave & Buster's", "offer": "Half-price games every Wednesday and Sunday",
                        "days": ["wed", "sun"], "pct": 50, "industries": ["entertainment"], "exact_days": True,
                        "absorbs": ["half-priced games"]}, V, "registry", TODAY)
    listed = from_listing(edd(0, "Dave & Buster's", "Dave & Buster's has half-priced games on Sundays through Thursdays."),
                          V, TODAY)
    assert listed.schedule.days == [0, 1, 2, 3, 6]
    dropped = Counter()
    kept = merge([games, listed], dropped)
    assert [(k.id, k.schedule.days) for k in kept] == [("db-games", [2, 6])]
    assert dropped["regular deal: a list gives other days than the company's own page"] == 1


def test_a_weekday_happy_hour_names_its_own_days():
    r = from_listing(edd(2, "Chuy's", "Chuy's Mexican restaurants have happy hour deals at most locations. Typical happy hours at "
                         "Chuy's are 3-6 pm pm Mondays through Fridays. Chuy's Happy Hour specials usually include $2 off "
                         "Margaritas, $1 off beer and wine."), V, TODAY)
    assert (r.schedule.days, r.schedule.time_text()) == ([0, 1, 2, 3, 4], "3–6 pm")
    assert r.offer.startswith("Typical happy hours at Chuy's") and "participating locations" in r.conditions


def test_what_is_not_a_regular_deal():
    why = lambda x: from_listing(x, V, TODAY)                                                    # noqa: E731
    assert why(kcl(1, "Jack in the Box", "On Tuesday, Sept. 29, get classic hamburgers for $1 each from 2 p.m. until close.",
                   "limited")) == "a one-off date, not a standing offer"
    assert why(kcl(2, "Wienerschnitzel", "Get four chili dogs for $4 at Wienerschnitzel every Wednesday in September.",
                   "limited")) == "past its stated end date"
    assert why(kcl(5, "Buffalo Wild Wings GO", "The first 100 guests in line at the new Buffalo Wild Wings GO in Suffolk, VA, on "
                   "Saturday, Oct. 3, will receive free wings for a year.", "weekend")) == "a one-off date, not a standing offer"
    assert why(kcl(1, "Ruby Tuesday", "Cheeseburgers and select sandwiches are $6.99 at Ruby Tuesday.")) == \
        "the chain has no mapped place in Texas"
    assert why(edd(0, "Dairy Queen", "You can find Dairy Queen coupons in the DQ app every day, with extra deals on Mondays.")) == \
        "no concrete offer stated"
    assert why(edd(3, "Sonic Drive-In", "Sonic Drive-In has a $1.99 Menu good every day featuring a Jr Bacon Cheeseburger.")) \
        .suppress == "an everyday offer, not tied to a day or time"
    assert why(kcl(4, "DoorDash", "Get $5 off orders of $20 on Fridays.")) == "a delivery app's promotion"
    # "weekend food deals" on the Friday page are this weekend's, unless the words say they repeat
    assert why(kcl(5, "Del Taco", "This October, Del Taco is celebrating Tacoberfest with a BOGO free deal on chicken street tacos "
                   "for Del Yeah! Rewards members. Offer valid through Oct. 4.", "weekend")) in \
        ("a one-off date, not a standing offer", "past its stated end date")
    wendys = why(kcl(5, "Wendy's", "This fall, Wendy's has several college football deals available on Saturdays only. Through "
                     "Dec. 4: Rewards members can get 50% off a Dave's Single with purchase.", "weekend"))
    assert (wendys.schedule.days, wendys.schedule.until, wendys.terms.pct) == ([5], date(2026, 12, 4), 50.0)
    assert why(kcl(0, "Schlotzsky's", "On Mondays, earn double rewards points with an in-app reward.")) in \
        ("a gift card, points or sweepstakes offer", "no concrete offer stated")


def test_an_every_day_happy_hour_is_kept_and_a_stale_list_is_not_live():
    r = from_listing(edd(5, "Sonic Drive-In", "Sonic Drive-In has $2 Snacks for rewards members every day from 2-5PM now through "
                         "November 1, 2026."), V, TODAY)
    assert (len(r.schedule.days), r.schedule.time_text(), r.schedule.until) == (7, "2–5 pm", date(2026, 11, 1))
    old = from_listing(kcl(2, "Schlotzsky's", "Enjoy BOGO pizzas at Schlotzsky's on Wednesdays.", modified=date(2026, 7, 1)), V, TODAY)
    assert old.status == "" and not old.evidence[0].live


# --- merging --------------------------------------------------------------------------------------------------------
def regs(*listings):
    out = [from_listing(x, V, TODAY) for x in listings]
    assert not [r for r in out if isinstance(r, str)], [r for r in out if isinstance(r, str)]
    return out


def test_two_lists_agreeing_make_one_deal_and_thursday_stays_its_own():
    tue_kcl = kcl(1, "Buffalo Wild Wings", "Get BOGO traditional wings at Buffalo Wild Wings. Offer is available for online and "
                  "dine-in orders.")
    tue_edd = edd(1, "Buffalo Wild Wings", "Buffalo Wild Wings has buy one order of wings, get one free on Tuesdays and Thursdays. "
                  "On Tuesdays, buy a 6, 10 or 15 piece order of traditional wings and get another order free. Dine-in only.")
    thu_kcl = kcl(3, "Buffalo Wild Wings", "Get BOGO free boneless wings every Thursday at Buffalo Wild Wings when you order "
                  "takeout or delivery.")
    out = merge(regs(tue_kcl, tue_edd, thu_kcl))
    by_day = {tuple(r.schedule.days): r for r in out}
    assert set(by_day) == {(1,), (3,)}                              # Tuesday's wording does not borrow Thursday
    assert status_text(by_day[(1,)]) == "Listed by 2 deal sites" and by_day[(1,)].weight == 0.9
    # EatDrinkDeals' sentence names both days, so it backs Thursday's entry as well; each keeps its own wording
    assert status_text(by_day[(3,)]) == "Listed by 2 deal sites" and "takeout or delivery" in by_day[(3,)].conditions
    assert by_day[(1,)].offer.startswith("Get BOGO traditional") and by_day[(3,)].offer.startswith("Get BOGO free boneless")


def test_the_same_sentence_on_five_pages_is_one_weekday_deal():
    text = "Typical happy hours at Chuy's are 3-6 pm Mondays through Fridays, with $2 off Margaritas."
    out = merge(regs(*(edd(d, "Chuy's", text) for d in range(5))))
    assert len(out) == 1 and out[0].schedule.days == [0, 1, 2, 3, 4] and len(out[0].evidence) == 5


def test_lists_that_disagree_on_a_price_are_not_shown():
    # it12 trial, R-X: Krazy Coupon Lady had Cracker Barrel's Thursday lunch at $14.49, EatDrinkDeals at $9.99
    dropped = Counter()
    out = merge(regs(kcl(3, "Cracker Barrel", "Grab Turkey n' Dressing for $14.49+ for lunch at Cracker Barrel on Thursdays."),
                     edd(3, "Cracker Barrel", "Thursdays – Turkey N' Dressing $9.99 lunch, $13.79 dinner."),
                     kcl(2, "Cracker Barrel", "On Wednesdays, Cracker Barrel offers Broccoli Cheddar Chicken for $9.99.")), dropped)
    assert [(r.schedule.days, r.terms.price) for r in out] == [([2], 9.99)]         # Wednesday's is untouched
    assert dropped == {"regular deal: lists disagree on the price, so it is not shown": 2}
    # two sources agreeing outweigh a third that differs
    a = "On Fridays through Sundays get a Prime Rib dinner for $35.99."
    out = merge(regs(kcl(4, "BJ's Restaurant & Brewhouse", a), edd(4, "BJ's Restaurants", a),
                     edd(5, "BJ's Restaurants", "On Fridays through Sundays get a Prime Rib dinner for $37.99.")))
    assert [r.terms.price for r in out] == [35.99] and len({e.source for e in out[0].evidence}) == 2


def test_an_everyday_offer_filed_under_one_weekday_is_not_that_days_deal():
    # it12 trial: "Save with the $1.99 menu at Sonic" sat on a Monday list; the other list says it is good every day
    monday = kcl(0, "Sonic", "Save with the $1.99 menu at Sonic. Menu items include Chili Cheese Coney and small tots.")
    daily = edd(3, "Sonic Drive-In", "Sonic also has a $1.99 Menu good every day featuring a Jr Bacon Cheeseburger, a Chicken "
                "Wrap and more.")
    tuesday = kcl(1, "Sonic", "Every Tuesday, rewards members can grab half-price Sonic cheeseburgers (menu price $4.99) "
                  "when you order online or in-app after 5 p.m. local.")
    snacks = edd(5, "Sonic Drive-In", "Sonic Drive-In has $2 Snacks for rewards members every day from 2-5PM now through "
                 "November 1, 2026.")
    dropped = Counter()
    out = merge(regs(monday, daily, tuesday, snacks), dropped)
    # the everyday stop takes nothing else with it: not Tuesday's burgers, not the 2-5 pm snacks at a cent more
    assert sorted(r.schedule.days for r in out) == [[0, 1, 2, 3, 4, 5, 6], [1]]
    assert dropped == {"regular deal: an everyday offer, not tied to a day or time": 1}


def test_a_two_day_entry_backs_both_days_and_stands_alone_where_no_other_list_has_it():
    both = "Village Inn has a free kids meal every Monday and Tuesday."
    out = merge(regs(kcl(1, "Village Inn", "Every Tuesday, Village Inn Rewards members can get one free kids meal for children "
                         "(10 and under) with each adult entree purchased."), edd(0, "Village Inn", both), edd(1, "Village Inn", both)))
    by_day = {tuple(r.schedule.days): r for r in out}
    assert set(by_day) == {(0,), (1,)}                              # Monday is not lost when Tuesday's entries are pooled
    assert status_text(by_day[(1,)]) == "Listed by 2 deal sites" and status_text(by_day[(0,)]) == "Listed by EatDrinkDeals"


def test_the_same_price_on_the_same_day_is_one_special_whatever_the_words():
    out = merge(regs(kcl(1, "Outback Steakhouse", "Get a surf and turf meal with sides for $24.99 at Outback Steakhouse every Tuesday."),
                     edd(1, "Outback Steakhouse", "Outback Steakhouse has a Tuesday Tails special for $24.99 with a 6 oz. sirloin.")))
    assert len(out) == 1 and status_text(out[0]) == "Listed by 2 deal sites"
    out = merge(regs(kcl(2, "BJ's Restaurant & Brewhouse", "Get $5 Pizookies on Wednesdays."),
                     edd(2, "BJ's Restaurants", "On Wednesdays get Signature Beers for $5.")))
    assert len(out) == 2                                            # a small round price needs a shared word


def test_the_offers_own_sentence_sets_its_days():
    r = from_listing(edd(3, "IKEA", "IKEA Family members can enjoy special IKEA Restaurant deals every weekday at most locations. "
                         "On Thursdays at IKEA, seniors get 20% off."), V, TODAY)
    assert (r.schedule.days, r.terms.pct) == ([3], 20.0)            # not "every weekday" from the lead-in
    assert from_listing(edd(1, "Slim Chickens", "Slim Chickens usually has a takeout deal on Tuesdays, such as $5 off a $25 order "
                            "or 15% off. They'll post the offer on Facebook."), V, TODAY) == "no concrete offer stated"


def entry(**kw):
    base = {"brand": "Schlotzsky's", "offer": "BOGO Wednesday: buy one pizza, flatbread or calzone and get one free",
            "days": ["wed"], "bogo": "buy 1 get 1 free", "absorbs": ["bogo"],
            "evidence": [{"kind": "official", "url": "https://www.schlotzskys.com/about-us/faqs", "find": ["only available on Wednesdays"]}]}
    return {**base, **kw}


def test_a_registry_entry_absorbs_the_matching_list_entry():
    reg = from_entry(entry(), V, "registry", TODAY)
    lst = from_listing(kcl(2, "Schlotzsky's", "Enjoy BOGO calzones, flatbreads, and pizzas at Schlotzsky's on Wednesdays."), V, TODAY)
    other = from_listing(edd(4, "Schlotzsky's", "From Friday to Sunday after 5 pm, get personal sized pizzas for just $5."), V, TODAY)
    out = merge([lst, other, reg])
    assert [r.origin for r in out] == ["registry", "list"]
    assert [e.kind for e in out[0].evidence] == ["list"]            # the registry's own evidence is added by the confirmer
    assert out[0].offer.startswith("BOGO Wednesday") and out[1].schedule.days == [4, 5, 6]


def test_a_list_price_that_differs_from_the_company_page_is_left_out():
    perry = from_entry({"brand": "Perry's Steakhouse & Grille", "offer": "Pork Chop Friday Lunch for $24", "days": ["fri"],
                        "price": 24, "absorbs": ["pork chop"]}, V, "registry", TODAY)
    lst = from_listing(kcl(4, "Perry's Steakhouse", "Each Friday from 10:30 a.m. - 5 p.m., you can order the Perry's Famous Pork "
                           "Chop Friday lunch for $22 at Perry's Steakhouse & Grill."), V, TODAY)
    dropped = Counter()
    out = merge([lst, perry], dropped)
    assert len(out) == 1 and out[0].evidence == []
    assert dropped == {"regular deal: a list gives a different price than the company's own page": 1}


def test_a_suppress_entry_stops_a_list_entry_known_not_to_apply_here():
    stop = from_entry({"brand": "Red Robin", "offer": "Happy hour 3 to 6 pm Monday to Friday", "days": ["weekdays"],
                       "absorbs": ["happy hour"], "suppress": "the company's page limits it to listed restaurants in other states"},
                      V, "registry", TODAY)
    lst = from_listing(edd(1, "Red Robin", "On weekdays get Happy Hour specials from 3-6 pm with $5 drafts."), V, TODAY)
    dropped = Counter()
    assert merge([lst, stop], dropped) == []
    assert dropped == {"regular deal: the company's page limits it to listed restaurants in other states": 1}


# --- registry entries -----------------------------------------------------------------------------------------------
def test_registry_entries_state_their_terms():
    r = from_entry({"brand": "BJ's Restaurant & Brewhouse", "offer": "Tuesday: $5 Pizookie and half off wine", "days": ["tue"],
                    "price": 5}, V, "registry", TODAY)
    assert (r.brand, r.chain.key, r.terms.price, r.terms.pct, r.terms.summary) == \
        ("BJ's Restaurant & Brewhouse", V.find("BJ's").key, 5.0, None, "$5")       # "half off wine" is not the headline
    r = from_entry({"brand": "Walgreens", "offer": "Seniors Day: 20% off", "days": ["first tue"], "pct": 20}, V, "registry", TODAY)
    assert (r.schedule.monthly, r.schedule.days_text(), r.kind, r.terms.summary) == \
        ("1:1", "First Tuesday of the month", "store", "20% off")
    r = from_entry({"brand": "Hank's", "offer": "Half off all burgers every Monday", "days": ["mon"], "time": "11 am - 9 pm",
                    "pct": 50, "places": [{"name": "Hank's", "address": "5811 Berkman Dr, Austin", "lat": 30.312, "lon": -97.6937}]},
                   V, "registry", TODAY)
    assert (r.chain, r.schedule.time_text(), r.industries, r.terms.summary) == (None, "11 am–9 pm", ["dining"], "half price")


def test_entries_that_cannot_be_used_say_why():
    bad = lambda **kw: from_entry(entry(**kw), V, "yours", TODAY)                                # noqa: E731
    assert bad(days=[]) == "needs the days it runs on"
    assert bad(days=["someday"]) == "not a day: 'someday'"
    assert bad(until="2026-09-30") == "past its stated end date"
    assert bad(until="next week") == "dates must look like 2026-12-31"
    assert bad(brand="Nowhere Cafe").startswith("no mapped place")
    assert bad(offer="") == "needs a brand and an offer"


# --- evidence -------------------------------------------------------------------------------------------------------
PAGE = """<html><head><script type="application/ld+json">{"dateModified":"2026-08-28T10:00:00Z"}</script>
<script>window.__DATA__ = {"copy": "Enjoy Half-Off Golf all day Monday-Thursday when you book online."}</script></head>
<body><h2>Bogo Wednesdays</h2><p>What day is BOGO Wednesday valid? You guessed it! Schlotzsky’s BOGO Wednesday offer is
only available on Wednesdays.</p><p>Weekdays 3—6PM</p>""" + "<p>filler text.</p>" * 80 + "<p>Kids eat free.</p></body></html>"


def test_phrases_are_found_whatever_the_quotes_dashes_and_case():
    texts = page_texts(PAGE)
    assert find_phrases(texts, ["Schlotzsky's BOGO Wednesday offer is only available on Wednesdays"])[0]
    assert find_phrases(texts, ["weekdays 3-6pm"])[0]
    ok, quote = find_phrases(texts, ["Half-Off Golf all day Monday-Thursday"])                 # text kept in a data block
    assert ok and "book online" in quote
    assert not find_phrases(texts, ["BOGO Thursday"])[0]


def test_phrases_must_sit_close_together():
    texts = page_texts(PAGE)
    assert find_phrases(texts, ["BOGO Wednesday", "only available on Wednesdays"])[0]
    assert not find_phrases(texts, ["BOGO Wednesday", "Kids eat free"])[0]                     # same page, another offer
    assert find_phrases(texts, ["BOGO Wednesday", "Kids eat free"], within=0)[0]


class FakeHttp:
    """Serves canned pages; a URL mapped to an exception raises it."""
    def __init__(self, pages):
        self.pages, self.calls, self.away = pages, [], set()

    async def turns_away_ai(self, url):
        return url in self.away

    async def get(self, url, **kw):
        self.calls.append(url)
        page = self.pages[url]
        if isinstance(page, list):                        # a page that differs from one read to the next
            page = page.pop(0) if len(page) > 1 else page[0]
        if isinstance(page, Exception):
            raise page
        return Response(url, url, 200, "text/html", page.encode(), time.time())


def make(tmp_path, pages, entries=(), mine=()):
    (tmp_path / "registry.json").write_text(json.dumps({"regulars": list(entries)}))
    (tmp_path / "mine.json").write_text(json.dumps(list(mine)))
    settings = Settings(cache_dir=tmp_path, regulars_path=tmp_path / "mine.json")
    reg = Regulars(FakeHttp(pages), Store(tmp_path / "slomp.db"), settings, V, tmp_path / "registry.json")

    async def no_roundups(use_cache=True):
        return [], []
    reg.roundups.read = no_roundups
    return reg


URL = "https://www.schlotzskys.com/about-us/faqs"
SPEC = {"kind": "official", "url": URL, "find": ["BOGO Wednesday offer is only available on Wednesdays"]}


def test_a_company_page_that_says_it_confirms_it(tmp_path):
    reg = make(tmp_path, {URL: PAGE})
    ev = asyncio.run(reg.check(SPEC))
    assert (ev.found, ev.live, ev.source) == (True, True, "schlotzskys.com") and "only available on Wednesdays" in ev.quote


def test_a_site_that_turns_away_ai_assistants_is_not_used_as_evidence(tmp_path):
    # the registry is kept up with an AI assistant's help; fortworthzoo.org's robots.txt names "Claude-Code"
    reg = make(tmp_path, {URL: PAGE})
    asyncio.run(reg.check(SPEC))                                   # a good read on record does not rescue it
    reg.http.away.add(URL)
    reg.http.calls.clear()
    ev = asyncio.run(reg.check(SPEC))
    assert (ev.found, ev.live, reg.http.calls) == (None, False, []) and "turns away AI assistants" in ev.note


def test_a_page_served_in_two_versions_is_read_again_before_a_miss_counts(tmp_path):
    # Fuzzy's home page carries its promotions in one version and not in the other, at random
    other = "<html><body>Welcome to our taco shop. Menu. Rewards. Catering.</body></html>"
    reg = make(tmp_path, {URL: PAGE})
    assert asyncio.run(reg.check(SPEC)).found                      # a hit goes on record
    reg.http.pages[URL] = [other, PAGE]
    reg.http.calls.clear()
    ev = asyncio.run(reg.check(SPEC))
    assert (ev.found, ev.live, len(reg.http.calls)) == (True, True, 2)
    reg.http.pages[URL] = [other]                                  # gone in every version: a miss after three reads
    reg.http.calls.clear()
    ev = asyncio.run(reg.check(SPEC))
    assert (ev.found, len(reg.http.calls)) == (False, 3)


def test_a_coupons_expiry_on_its_page_is_the_deals_last_day(tmp_path):
    # Chuck E. Cheese's weekly coupons carry a date that the page moves forward: "... VIEW COUPON Expires 10/19/2026"
    url = "https://www.chuckecheese.com/denton-tx/coupons-and-deals/"
    spec = {"id": "cec-tuesday", "brand": "Chuck E. Cheese", "offer": "Topping Tuesday: buy one large pizza, get one 50% off",
            "days": ["tue"], "bogo": "buy 1 get 1 50% off", "industries": ["dining"],
            "evidence": [{"kind": "official", "url": url, "find": ["Topping Tuesday buy-one-get-one 50% off large pizzas"],
                          "expires_after": "Topping Tuesday Buy 1 Large Pizza, Get One Large 50% OFF"}]}
    page = ("<html><body>Current offers include Topping Tuesday buy-one-get-one 50% off large pizzas. Topping Tuesday Buy 1 "
            "Large Pizza, Get One Large 50% OFF VIEW COUPON Expires {} Close Print</body></html>")
    monday = datetime(2026, 10, 5, 10, 0, tzinfo=ZoneInfo("America/Chicago"))
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    deals, _, _ = search(make(tmp_path / "a", {url: page.format("10/19/2026")}, [spec]), "dallas", ["dining"], monday)
    assert [(d.regular["next"], d.regular["until"]) for d in deals] == [(["2026-10-06"], "2026-10-19")]
    deals, excluded, _ = search(make(tmp_path / "b", {url: page.format("10/1/2026")}, [spec]), "dallas", ["dining"], monday)
    assert deals == [] and excluded["regular deal: does not run in the next 7 days"] == 1


def test_an_unreadable_page_falls_back_on_the_last_good_read_for_a_week(tmp_path):
    reg = make(tmp_path, {URL: PAGE})
    now = datetime(2026, 10, 5, 12, tzinfo=ZoneInfo("America/Chicago"))
    asyncio.run(reg.check(SPEC, now=now))
    reg.http.pages[URL] = Blocked(URL, "the site served a bot check instead of the page", 403)
    ev = asyncio.run(reg.check(SPEC, now=now + timedelta(days=2)))
    assert (ev.found, ev.live) == (None, True) and "bot check" in ev.note
    late = asyncio.run(reg.check(SPEC, now=now + timedelta(days=9)))
    assert (late.found, late.live) == (None, False)                  # a week without a good read: no longer relied on


def test_a_page_that_stops_saying_it_ends_the_deal(tmp_path):
    # Fuzzy's home page dropped its two promotions on Oct 5, 2026 and Slomp went on showing them as confirmed: one miss
    # used to be forgiven as a possible page variant. A variant is now ruled out by reading three times, so a miss ends it.
    reg = make(tmp_path, {URL: PAGE})
    asyncio.run(reg.check(SPEC))
    reg.http.pages[URL] = "<html><body>Our menu.</body></html>"
    reg.http.calls.clear()
    gone = asyncio.run(reg.check(SPEC))
    assert (gone.found, gone.live, gone.note, len(reg.http.calls)) == (False, False, "the page no longer says this", 3)


def test_an_article_counts_by_its_own_date(tmp_path):
    art = "https://hip2save.com/deals/amc-stubs-membership/"
    reg = make(tmp_path, {art: PAGE})
    spec = {"kind": "article", "url": art, "find": ["Half-Off Golf"], "source": "Hip2Save"}
    oct5 = datetime(2026, 10, 5, 12, tzinfo=ZoneInfo("America/Chicago"))
    ev = asyncio.run(reg.check(spec, now=oct5))
    assert (ev.live, ev.page_date, ev.source) == (True, date(2026, 8, 28), "Hip2Save")
    late = asyncio.run(reg.check(spec, now=oct5 + timedelta(days=200)))
    assert not late.live and "too old" in late.note


# --- a search -------------------------------------------------------------------------------------------------------
HANKS = {"id": "hanks-monday", "brand": "Hank's", "offer": "Half off all burgers every Monday, 11 am to 9 pm", "days": ["mon"],
         "time": "11 am - 9 pm", "pct": 50, "conditions": ["dine-in only"], "industries": ["dining"],
         "places": [{"name": "Hank's", "address": "5811 Berkman Dr, Austin, TX", "lat": 30.312014, "lon": -97.693665}],
         "evidence": [{"kind": "official", "url": "https://www.hanksaustin.com/menus/", "find": ["EVERY MONDAY", "Half off all burgers"]}]}
HANKS_PAGE = "<html><body>Specials EVERY MONDAY 11AM–9PM Half off all burgers - Dine-In Only</body></html>"
DOKA = {"brand": "DOKA Bubble Tea", "offer": "BOGO Wednesday on select drinks", "days": ["wed"], "industries": ["dining"],
        "kind": "cafe", "places": [{"address": "2815 Guadalupe St, Austin, TX 78705", "lat": 30.294171, "lon": -97.742141}],
        "link": "https://www.facebook.com/p/Doka-Bubble-Tea-100070021503436/", "note": "Seen on their Facebook page."}


def search(reg, city_id, inds, when, radius=25.0):
    c = city(city_id)
    start = when.astimezone(ZoneInfo(c.tz))
    excluded = Counter()
    deals, sources = asyncio.run(reg.near(c, inds, radius, start, start + timedelta(days=7), excluded, refresh=True))
    return deals, excluded, sources


def test_a_search_returns_regular_deals_with_their_dates_and_evidence(tmp_path):
    reg = make(tmp_path, {"https://www.hanksaustin.com/menus/": HANKS_PAGE}, [HANKS], [DOKA])
    monday_10am = datetime(2026, 10, 5, 10, 0, tzinfo=ZoneInfo("America/Chicago"))
    deals, excluded, sources = search(reg, "austin", ["dining"], monday_10am)
    hank, doka = sorted(deals, key=lambda d: d.merchant, reverse=True)
    assert (hank.id, hank.kind, hank.starts_in_days, hank.store.distance_mi < 5, hank.score) == \
        ("regular:hanks-monday", "regular", 0, True, 45.0)
    # next Monday's 11 am start falls after the 7-day window closes at 10 am, so only today counts
    assert hank.regular["next"] == ["2026-10-05"] and hank.regular["status_text"] == "Confirmed on hanksaustin.com"
    assert (hank.valid_from.hour, hank.valid_to.isoformat()[:16], hank.terms.conditions) == (11, "2026-10-05T21:00", ["dine-in only"])
    assert (doka.regular["status"], doka.regular["status_text"], doka.regular["next"], doka.starts_in_days) == \
        ("yours", "Added by you", ["2026-10-07"], 2)
    assert doka.regular["evidence"][0]["kind"] == "yours" and "facebook.com" not in " ".join(reg.http.calls)   # never fetched
    assert doka.score == 22.5 and doka.to_dict()["kind"] == "regular"          # half the weight of a confirmed one (45)
    assert [s["name"] for s in sources][-3:] == ["Regular deals registry", "Your regular deals", "OpenStreetMap venues"]


def test_a_regular_deal_carries_its_logo_and_the_time_its_hours_end(tmp_path, monkeypatch):
    import slomp.regulars as rg
    monkeypatch.setattr(rg, "_logos", lambda: {"place:hanks": {"url": "https://www.hanksaustin.com/favicon.png", "fit": "contain"}})
    reg = make(tmp_path, {"https://www.hanksaustin.com/menus/": HANKS_PAGE}, [HANKS], [DOKA])
    deals, _, _ = search(reg, "austin", ["dining"], datetime(2026, 10, 5, 10, 0, tzinfo=ZoneInfo("America/Chicago")))
    hank, doka = sorted(deals, key=lambda d: d.merchant, reverse=True)
    assert hank.regular["logo"] == {"url": "https://www.hanksaustin.com/favicon.png", "fit": "contain"}
    assert hank.regular["ends"] == "21:00" and doka.regular["logo"] is None and doka.regular["ends"] is None


def test_a_search_leaves_out_other_industries_far_places_and_finished_days(tmp_path):
    reg = make(tmp_path, {"https://www.hanksaustin.com/menus/": HANKS_PAGE}, [HANKS], [DOKA])
    monday_10pm = datetime(2026, 10, 5, 22, 0, tzinfo=ZoneInfo("America/Chicago"))
    deals, _, _ = search(reg, "austin", ["dining"], monday_10pm)
    hank = next(d for d in deals if d.merchant == "Hank's")
    assert hank.regular["next"] == ["2026-10-12"] and hank.starts_in_days == 7       # tonight's is over at 9 pm
    assert search(reg, "austin", ["tech", "entertainment"], monday_10pm)[0] == []
    deals, excluded, _ = search(reg, "houston", ["dining"], monday_10pm)
    assert deals == [] and excluded["regular deal: no branch within the radius"] == 2


def test_a_date_the_page_marks_sold_out_is_not_shown(tmp_path):
    # Houston Zoo's free day needs a reserved ticket; on Oct 5, 2026 its page read "October 6 - SOLD OUT"
    url = "https://www.houstonzoo.org/free-tuesdays/"
    zoo = {"id": "zoo-free-day", "brand": "Houston Zoo", "offer": "Free Zoo Day on the first Tuesday of the month",
           "days": ["first tue"], "summary": "free admission", "industries": ["entertainment"], "kind": "zoo",
           "places": [{"name": "Houston Zoo", "address": "6200 Hermann Park Dr, Houston, TX", "lat": 29.7146, "lon": -95.3909}],
           "evidence": [{"kind": "official", "url": url, "find": ["on the first Tuesday of each month"],
                         "sold_out": "{month} {day} - SOLD OUT"}]}
    page = "<html><body>Free Zoo Days are provided once a month, on the first Tuesday of each month. {} November 3</body></html>"
    monday = datetime(2026, 10, 5, 10, 0, tzinfo=ZoneInfo("America/Chicago"))
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    reg = make(tmp_path / "a", {url: page.format("October 6 - SOLD OUT")}, [zoo])
    deals, excluded, _ = search(reg, "houston", ["entertainment"], monday)
    assert deals == [] and excluded["regular deal: its page says the coming date is sold out"] == 1
    reg = make(tmp_path / "b", {url: page.format("October 6")}, [zoo])
    deals, excluded, _ = search(reg, "houston", ["entertainment"], monday)
    assert [d.regular["next"] for d in deals] == [["2026-10-06"]]


def test_evidence_that_fails_keeps_the_deal_out(tmp_path):
    reg = make(tmp_path, {"https://www.hanksaustin.com/menus/": "<html><body>Our menus.</body></html>"}, [HANKS])
    deals, excluded, _ = search(reg, "austin", ["dining"], datetime(2026, 10, 5, 10, tzinfo=ZoneInfo("America/Chicago")))
    assert deals == [] and excluded["regular deal: no evidence recent enough to rely on"] == 1


def test_a_registry_entry_without_its_own_evidence_does_not_speak_for_a_list(tmp_path):
    # Fuzzy's page dropped its Tuesday tacos while a deal site still listed them: the card must be the list's, in the
    # list's words, not the registry's wording under a "listed" label
    url = "https://www.fuzzystacoshop.com/"
    entry = {"id": "fuzzys-taco-tuesday", "brand": "Fuzzy's Taco Shop", "offer": "TuesYay: $2.50 classic and $3.50 premium tacos",
             "days": ["tue"], "price": 2.5, "absorbs": ["taco"],
             "evidence": [{"kind": "official", "url": url, "find": ["$2.50 classic and $3.50 premium tacos"]}]}
    reg = make(tmp_path, {url: "<html><body>Welcome to Fuzzy's. Our menu.</body></html>"}, [entry])
    listed = edd(1, "Fuzzy's Taco Shop", "Fuzzy's Taco Shop has $2 tacos every Tuesday.")

    async def one_list(use_cache=True):
        return [listed], []
    reg.roundups.read = one_list
    deals, excluded, _ = search(reg, "fort-worth", ["dining"], datetime(2026, 10, 5, 10, tzinfo=ZoneInfo("America/Chicago")))
    assert [(d.title, d.regular["status"]) for d in deals] == [("Fuzzy's Taco Shop has $2 tacos every Tuesday.", "listed")]
    assert excluded["regular deal: no evidence recent enough to rely on"] == 1
