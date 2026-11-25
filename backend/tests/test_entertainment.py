"""Entertainment bought online (slomp/entertainment.py): subscriptions, and tickets, passes and memberships. Titles
and texts are posts read on Nov 24, 2026."""
import json
import subprocess
from collections import Counter
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from slomp import entertainment as ent
from slomp import industries as ind
from slomp.sales import SalesResult, StoreSales, select, to_payload
from slomp.service import InputError, resolve_industries
from slomp.sources.feeds import Post
from test_site import DRIVER, _site, needs_node

CT = ZoneInfo("America/Chicago")
NOW = datetime(2026, 11, 24, 9, 0, tzinfo=CT)


def post(title, text="", category="Video Streaming Services", seller="", source="dealnews", days_ago=1.0, **kw):
    return Post(source=source, id=f"{source}:{abs(hash(title))}", url=f"https://example.com/{abs(hash(title))}",
                title=title, text=text, seller=seller, category=category if source == "dealnews" else "",
                posted_at=NOW - timedelta(days=days_ago), **kw)


def one(p):
    ex = Counter()
    return StoreSales(None, None).sale(p, NOW, ex), ", ".join(ex)


def test_the_source_says_what_a_post_is():
    assert ent.kind_of(post("x", category="Streaming Services")) == "subscription"
    assert ent.kind_of(post("x", category="Music Streaming Services")) == "subscription"      # under Streaming Services
    assert ent.kind_of(post("x", category="Movie Tickets")) == ent.kind_of(post("x", category="Things to Do")) == "tickets"
    assert ent.kind_of(post("Roku Streaming Stick 4K for $29", category="Streaming Media Players")) == ""
    # a site that gives no category: only a title that says so in plain words
    sd = lambda t: ent.kind_of(post(t, source="slickdeals"))                                   # noqa: E731
    assert sd("New Subscribers: 3-Months Frndly TV Streaming Service Plan $1/Month") == "subscription"
    assert sd("Amazon Prime Video Bundle Offers: 2-Month MGM+, Starz & AMC+ Streaming $5.50/Month & More") == "subscription"
    assert sd("AAA Members: Select Amusement Parks, Movie/Event Tickets, Restaurant GCs $80 Off $200+") == "tickets"
    assert sd("Disney+ Members: Avengers: Doomsday (2026) Fandango Movie Ticket Offer $10 Off") == "tickets"
    assert sd("Six Flags Over Texas 2027 Season Pass $69") == "tickets"
    assert sd("Helldivers 2 Season Pass (PC Digital Download) $10") == ""                    # more of a game, not a pass to somewhere
    for goods in ("Roku Streaming Stick 4K $20 + Free Shipping", "Join Planet Fitness for $1 Down + $10/Month",
                  "Dostatni 1,000-Count Movie Night Ticket Roll $9", "Xbox Game Pass Ultimate 3-Month Membership $30"):
        assert sd(goods) == "", goods


def test_a_subscription_priced_by_the_month_with_the_regular_price_the_post_gives():
    s, _ = one(post("HBO Max Black Friday Basic w/ Ads Plan Deal for $5.49/mo",
                    "HBO Max's Black Friday Deal cuts the Basic With Ads plan to $5.49 per month for 12 months, down from "
                    "$10.99. That works out to about $66 saved over the year.", seller="HBO max",
                    expires_at=datetime(2026, 11, 30, 23, 59, tzinfo=CT), expires_stated=True))
    assert (s.what, s.industries, s.store_name) == ("subscription", ["entertainment"], "HBO max")
    assert (s.offer, s.badge, s.discount_pct) == ("$5.49 a month for 12 months, regularly $10.99", "$5.49/mo", 50.0)
    assert s.name == "HBO Max Black Friday Basic w/ Ads Plan Deal" and s.conditions == ["with ads"]
    assert "down from $10.99" in s.offer_how and s.ends_at.date().isoformat() == "2026-11-30" and s.event == "Black Friday"
    s, _ = one(post("Peacock Black Friday Subscription Deals for From $2.99/month",
                    "Peacock's Black Friday Deals bring Select down to $2.99 a month for three months, versus the regular "
                    "$8.99 monthly price.", seller="Peacock TV"))
    assert (s.offer, s.badge, s.badge_soft) == ("From $2.99 a month for 3 months, regularly $8.99", "From $2.99/mo", True)
    # no regular price, and the post says how much it takes off
    s, _ = one(post("Prime Video Black Friday STARZ Subscription Deal for $2.99/mo.",
                    "Prime Video takes 75% off STARZ subscriptions during its Black Friday Sale, dropping the price to "
                    "$2.99/month for two months.", seller="Amazon"))
    assert (s.store, s.offer, s.discount_pct) == ("amazon", "$2.99 a month for 2 months, 75% off", 75.0)
    s, _ = one(post("Prime Video Black Friday Subscription Deals: Up to 79% off", seller="Amazon", category="Streaming Services"))
    assert (s.offer, s.badge, s.score) == ("Up to 79% off", "Up to 79%", 39.5)
    s, _ = one(post("Amazon Music Unlimited 3-Month Trial: Free", "New subscribers get three months free.", seller="Amazon",
                    category="Music Streaming Services"))
    assert (s.offer, s.name, s.conditions, s.discount_pct) == ("Free", "Amazon Music Unlimited 3-Month Trial", ["new subscribers"], None)


def test_tickets_passes_and_things_to_do():
    s, _ = one(post("AMC Theatres Movie Package for 2 w/ Fountain Drinks and Popcorn for $36 + instant e-voucher delivery",
                    'With promo code "FALLFILMS", the AMC Theatres Movie Package at Giftory drops to $36, down from $98.',
                    category="Movie Tickets", seller="Giftory"))
    assert (s.what, s.store_name, s.offer, s.badge, s.code) == ("tickets", "Giftory", "$36, regularly $98", "$36", "FALLFILMS")
    assert s.name == "AMC Theatres Movie Package for 2 w/ Fountain Drinks and Popcorn" and s.discount_pct == 63.3
    s, _ = one(post("Cinemark Movie Club 6-Month Membership for $45", category="Movie Tickets", seller="Groupon"))
    assert (s.offer, s.badge) == ("$45 for 6 months", "$45")
    s, _ = one(post("Fandango Everest: The Other Side Movie Ticket Offer: $15 off",
                    'With promo code "EVEREST", Fandango takes $15 off the total ticket price.', category="Movie Tickets", seller="Fandango"))
    assert (s.offer, s.code) == ("$15 off", "EVEREST")
    s, _ = one(post("Bass Pro Shops Santa's Wonderland Santa Photos: Free", category="Things to Do", seller="Bass Pro Shops"))
    assert (s.offer, s.name) == ("Free", "Bass Pro Shops Santa's Wonderland Santa Photos")
    s, _ = one(post("Disney+, Hulu, & HBO Max Bundle (No Ads) for $34.99/mo", seller="Disney+", category="Streaming Services"))
    assert (s.name, s.offer) == ("Disney+, Hulu, & HBO Max Bundle (No Ads)", "$34.99 a month")


def test_what_stays_out():
    for title, category, seller, why in (
            ("Paramount+ Student Discount: 50% off All Plans + free shipping", "Streaming Services", "Paramount+", "a discount for a group of people"),
            ("Two AMC Theatres Standard/Digital Movie Black Tickets + $20 Gift Card for $40 + email delivery", "Movie Tickets", "Costco", "a gift card"),
            ("Dostatni 1,000-Count Movie Night Ticket Roll for $9 + free shipping w/ Prime", "Movie Tickets", "Amazon", "goods that ship, not a ticket"),
            ("I Love Lucy: The Complete Series Digital TV Series for $20 + no shipping required", "Video Streaming Services", "Fandango", "not a subscription"),
            ("Movies on YouTube: Free w/ ads", "Video Streaming Services", "YouTube", "not a subscription"),
            ("ESPN Unlimited Now Included with YouTube TV: Sign Up Now", "Video Streaming Services", "YouTube TV", "no price or discount stated"),
            ("Send Your Name with Dragonfly: Free", "Things to Do", "", "seller not named")):
        s, got = one(post(title, category=category, seller=seller))
        assert s is None and got == f"entertainment: {why}", title
    # the same times as any sale: an old post with no end, and one past its end
    s, got = one(post("Regal Premiere Movie Ticket w/ Soft Drink E-Voucher for 2 for $23", category="Movie Tickets", seller="Giftory", days_ago=22))
    assert s is None and got == "sale: no end date and posted over 7 days ago"
    # a sale at a store that ships is still read as one
    s, _ = one(post("Best Buy Black Friday TV Deals: Up to 60% off + free shipping", category="TVs", seller="Best Buy", deal_type="sale"))
    assert s.what == "" and "entertainment" not in s.industries


def test_the_sales_tab_covers_entertainment_and_not_dining():
    assert "entertainment" in ind.SALE_IDS and "dining" not in ind.SALE_IDS and not ind.BY_ID["entertainment"].online
    assert resolve_industries("entertainment,dining,tech", sales=True) == ["entertainment", "tech"]
    assert resolve_industries("entertainment,tech", online_only=True) == ["tech"]
    with pytest.raises(InputError):
        resolve_industries("nope", sales=True)
    sub, _ = one(post("Paramount+ Premium Plan Black Friday Deal for $2.99/Mo. for 2 Months", seller="Paramount+"))
    tv, _ = one(post("Best Buy Black Friday TV Deals: Up to 60% off + free shipping", category="TVs", seller="Best Buy", deal_type="sale"))
    res = SalesResult(sales=[sub, tv], generated_at=NOW)
    assert [s.id for s in select(res, ["entertainment"], NOW)[0]] == [sub.id]
    assert [s.id for s in select(res, ["tech"], NOW)[0]] == [tv.id]
    out = to_payload(res, ["entertainment"], NOW)
    assert out["sales"][0]["what"] == "subscription" and out["counts"] == {"sales": 1, "stores": 1}


@needs_node
def test_engine_gives_entertainment_its_sales_and_no_product_deals(tmp_path):
    site = _site(tmp_path)
    meta = json.loads((site / "data" / "meta.json").read_text())
    meta["industries"].append({"id": "entertainment", "name": "Movies & Entertainment", "description": "", "online": False, "sales": True})
    (site / "data" / "meta.json").write_text(json.dumps(meta))
    sale = lambda i, inds, what: {"id": i, "store": "", "store_name": "S", "title": i, "name": i, "offer": "x", "badge": "x",   # noqa: E731
                                  "industries": inds, "what": what, "score": 1, "posted_at": "2026-10-06T10:00:00+00:00"}
    (site / "data" / "sales.json").write_text(json.dumps({
        "generated_at": "2026-10-06T18:00:00+00:00", "excluded": {}, "sources": [], "stores": {},
        "sales": [sale("sub", ["entertainment"], "subscription"), sale("tv", ["tech"], "")]}))
    cases = [{"city": "alpha", "industries": "entertainment", "radius_mi": 10, "now": "2026-10-06T15:00:00-05:00"},
             {"city": "alpha", "industries": "dining", "radius_mi": 10, "now": "2026-10-06T15:00:00-05:00"},
             {"city": "alpha", "industries": "tech,entertainment", "radius_mi": 10, "now": "2026-10-06T15:00:00-05:00"}]
    (tmp_path / "cases.json").write_text(json.dumps(cases))
    out = subprocess.run(["node", "-e", DRIVER, str(site), str(tmp_path / "cases.json")], capture_output=True, text=True, check=True)
    only, dining, both = json.loads(out.stdout)
    assert only["online"] is None and [s["id"] for s in only["sales"]["sales"]] == ["sub"] and only["sales"]["industries"] == ["entertainment"]
    assert dining["online"] is None and dining["sales"] is None
    assert both["online"]["industries"] == ["tech"] and sorted(s["id"] for s in both["sales"]["sales"]) == ["sub", "tv"]


def test_two_channels_at_one_price_are_two_offers_and_no_stores_sale_swallows_them():
    from slomp.sales import dedupe
    starz, _ = one(post("Prime Video Black Friday STARZ Subscription Deal for $2.99/mo.", seller="Amazon"))
    paramount, _ = one(post("Prime Video Black Friday Paramount+ Subscription Deals for $2.99/mo. + free shipping w/ Prime", seller="Amazon"))
    again, _ = one(post("Prime Video Black Friday STARZ Subscription Deal for $2.99/mo", seller="Amazon", source="dealnews", days_ago=2))
    tv, _ = one(post("Amazon Black Friday Sale 2026: Up to 70% off + free shipping w/ Prime", category="TVs", seller="Amazon", deal_type="sale"))
    ex = Counter()
    kept = dedupe([starz, paramount, again, tv], ex)
    assert sorted(s.name for s in kept if s.what) == ["Prime Video Black Friday Paramount+ Subscription Deals",
                                                      "Prime Video Black Friday STARZ Subscription Deal"]
    assert tv in kept and ex["sale: same sale posted elsewhere"] == 1
    pct, _ = one(post("Prime Video Black Friday Subscription Deals: Up to 79% off", seller="Amazon", category="Streaming Services"))
    assert (pct.upto, pct.pct) == (79, None)


def test_the_api_gives_entertainment_its_sales_and_no_product_deals(tmp_path, monkeypatch):
    import asyncio
    from dataclasses import replace
    from datetime import timezone

    import httpx

    from slomp import api
    monkeypatch.setenv("SLOMP_WARM", "0")
    monkeypatch.setenv("SLOMP_CACHE_DIR", str(tmp_path))
    sub, _ = one(post("Paramount+ Premium Plan Black Friday Deal for $2.99/Mo. for 2 Months", seller="Paramount+"))
    sub = replace(sub, posted_at=datetime.now(timezone.utc) - timedelta(hours=1), ends_at=None)      # live whenever this runs

    class Part:
        def to_dict(self):
            return {"ok": True}

    async def go():
        async with api.lifespan(api.app):
            s = api.app.state.slomp

            async def part(*a, **k):
                return Part()

            async def result(use_cache=True):
                return SalesResult(sales=[sub])
            s.local, s.online, s.sales_result = part, part, result
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api.app), base_url="http://slomp") as c:
                out = [(await c.get("/api/v1/search", params={"city": "austin", "industries": i})).json()
                       for i in ("entertainment", "dining", "tech,entertainment")]
                return out, (await c.get("/api/v1/meta")).json(), await c.get("/api/v1/sales", params={"industries": "dining"})
    (only, dining, both), meta, refused = asyncio.run(go())
    assert only["online"] is None and [s["what"] for s in only["sales"]["sales"]] == ["subscription"]
    assert dining["online"] is None and dining["sales"] is None
    assert both["online"] == {"ok": True} and both["sales"]["industries"] == ["tech", "entertainment"]
    flags = {i["id"]: (i["online"], i["sales"]) for i in meta["industries"]}
    assert flags["entertainment"] == (False, True) and flags["dining"] == (False, False) and flags["tech"] == (True, True)
    assert refused.status_code == 422           # dining has no sales: the API says so


def test_one_offer_posted_under_three_names_is_one_card():
    # dealnews, Nov 12 to 24, 2026: the same three free months, and the published list showed three cards
    from slomp.sales import dedupe, offer_words
    ends = dict(expires_at=datetime(2027, 1, 11, 11, 0, tzinfo=CT), expires_stated=True)
    music = dict(category="Music Streaming Services", seller="Amazon", **ends)
    trial, _ = one(post("Amazon Music Unlimited 3-Month Trial: Free", days_ago=12, **music))
    sub, _ = one(post("Amazon Music Unlimited 3-Month Subscription: free", days_ago=11, **music))
    friday, _ = one(post("Amazon Music Unlimited Black Friday Offer: 3 months for free", days_ago=0.1, **music))
    assert [s.name for s in (trial, sub, friday)] == ["Amazon Music Unlimited 3-Month Trial", "Amazon Music Unlimited 3-Month Subscription",
                                                      "Amazon Music Unlimited Black Friday Offer: 3 months"]
    ex = Counter()
    kept = dedupe([friday, sub, trial], ex)
    assert [s.name for s in kept] == ["Amazon Music Unlimited 3-Month Trial"] and ex["sale: same sale posted elsewhere"] == 2
    assert [p["title"] for p in kept[0].also_posted] == [sub.title, friday.title]
    # another term, another service or another tier is another offer
    six, _ = one(post("Amazon Music Unlimited 6-Month Trial: Free", **music))
    hd, _ = one(post("Amazon Music Unlimited Family Plan 3-Month Trial: Free", **music))
    audible, _ = one(post("Audible Premium Plus 3-Month Trial: Free", **music))
    assert len(dedupe([trial, six, hd, audible], Counter())) == 4
    assert offer_words("Paramount+ Premium Plan Black Friday Deal") == offer_words("Paramount+ Premium Cyber Monday Subscription Offer")
    assert offer_words("Paramount+ Essential Annual Plan") != offer_words("Paramount+ Essential Monthly Plan")
    assert offer_words("Peacock 12-Month Plan") == offer_words("Peacock twelve month subscription") == offer_words("Peacock 1-Year Plan") \
        != offer_words("Peacock 6-Month Plan")


def test_a_seller_given_as_its_web_address_is_shown_by_the_name_the_post_writes():
    # Slickdeals, Nov 24, 2026: the card's seller read "disneyplus.com" beside dealnews' "Disney+" cards
    from slomp.sales import dedupe, name_sellers
    from slomp.sources.feeds import seller_key, written_name
    title = "1-Year Disney+ w/ Hulu Premium Bundle w/ No Ads Streaming Subscription $15/Month (Valid thru 12/1)"
    said = "Disney Plus [disneyplus.com] is offering 1-Year Disney+ w/ Hulu Premium Bundle w/ No Ads Streaming Subscription on sale for $14.99/month"
    sd, _ = one(post(title, said, source="slickdeals", seller="disneyplus.com", days_ago=0.1))
    assert (sd.store, sd.store_name, sd.offer) == ("", "Disney Plus", "$15 a month")
    bare, _ = one(post(title, "Offer valid for new and eligible returning subscribers only https://www.disneyplus.com/welcome",
                       source="slickdeals", seller="disneyplus.com", days_ago=0.1))
    assert bare.store_name == "disneyplus.com"                      # the post writes no name: what the source gives stays
    # one spelling for a seller across a build: a name before an address, and the best-ranked source's
    dn, _ = one(post("Disney+ & Hulu Bundle Black Friday Deals for From $4.99/mo for a year", seller="Disney+", category="Streaming Services"))
    hbo, _ = one(post("HBO Max Black Friday Basic w/ Ads Plan Deal for $5.49/mo", seller="HBO max"))
    sales = [sd, bare, dn, hbo]
    name_sellers(sales)
    assert [s.store_name for s in sales] == ["Disney+", "Disney+", "Disney+", "HBO max"]
    assert len(dedupe(sales, Counter())) == 3                       # the two Slickdeals posts were the same offer all along
    alone = [one(post(title, said, source="slickdeals", seller="disneyplus.com"))[0]]
    name_sellers(alone)
    assert alone[0].store_name == "Disney Plus"
    assert seller_key("Disney+") == seller_key("Disney Plus") == seller_key("disneyplus.com") == seller_key("www.disneyplus.com") == "disneyplus"
    # the words beside an address are the store's name only when they spell it
    assert written_name("32 Degrees [32degrees.com] has Men's Cool Classic T-Shirts", "32degrees.com") == "32 Degrees"
    assert written_name("Deal Details Urban Outfitters [ urbanoutfitters.com ] has", "urbanoutfitters.com") == "Urban Outfitters"
    assert written_name("PlayStation Store [playstation.com] has select games", "playstation.com") == "PlayStation Store"
    assert written_name("Thanks to Eragorn. Disney Plus is offering a bundle. https://www.disneyplus.com/welcome", "disneyplus.com") == "Disney Plus"
    assert written_name('Go to the page for the 77" C6 OLED evo AI 4K Smart TV [lg.com] and add it to cart', "lg.com") == ""
    assert written_name("Check this deal [homeandcooksales.com] before it ends", "homeandcooksales.com") == ""
    assert written_name("Catfootwear.com [catfootwear.com] has work boots", "catfootwear.com") == ""


def test_the_duplicates_check_compares_subscriptions_as_the_pipeline_does():
    from slomp.verify import sales_checks as sc
    amazon = dict(seller="Amazon")
    starz, _ = one(post("Prime Video Black Friday STARZ Subscription Deal for $2.99/mo.", **amazon))
    paramount, _ = one(post("Prime Video Black Friday Paramount+ Subscription Deals for $2.99/mo.", **amazon))
    assert sc.quality([starz, paramount], NOW, "duplicates")[0] == "pass"            # two channels at one price
    music = dict(category="Music Streaming Services", **amazon)
    trial, _ = one(post("Amazon Music Unlimited 3-Month Trial: Free", **music))
    sub, _ = one(post("Amazon Music Unlimited 3-Month Subscription: free", **music))
    verdict, det = sc.quality([trial, sub], NOW, "duplicates")
    assert verdict == "fail" and "Amazon Music Unlimited 3-Month Subscription" in det["problems"][0]


def test_one_offer_from_two_sources_a_cent_apart_is_one_card():
    # run 174, Nov 25, 2026: the bundle stood twice, $5.49 a month from dealnews and "$5.50/Month" from Slickdeals
    from slomp.sales import dedupe, same_price
    nov30 = dict(expires_at=datetime(2026, 11, 30, 23, 59, tzinfo=CT), expires_stated=True)
    dn, _ = one(post("Prime Video Black Friday AMC+, MGM+ & STARZ Bundle Deals for $5.49/mo.",
                     "Prime members get the AMC+, MGM+ and STARZ bundle for $5.49 per month for 2 months, down from $21.99.",
                     seller="Amazon", days_ago=3, **nov30))
    sd, _ = one(post("Amazon Prime Video Bundle Offers: 2-Month MGM+, Starz & AMC+ Streaming $5.50/Month & More",
                     "Amazon For those interested Note, offer valid for Amazon Prime Members only [ amazon.com ]", source="slickdeals", seller="Amazon"))
    assert (dn.badge, dn.offer, sd.badge, sd.ends_at) == ("$5.49/mo", "$5.49 a month for 2 months, regularly $21.99", "$5.50/mo", None)
    hbo, _ = one(post("HBO Max Basic Black Friday Subscription Deal on Prime Video for $5.49/mo.", "It is $5.49 per month for 12 months.",
                      seller="Amazon", expires_at=datetime(2026, 12, 1, 23, 59, tzinfo=CT), expires_stated=True))
    starz, _ = one(post("Prime Video Black Friday STARZ Subscription Deal for $2.99/mo.", seller="Amazon", **nov30))
    paramount, _ = one(post("Prime Video Black Friday Paramount+ Subscription Deals for $2.99/mo.", seller="Amazon", **nov30))
    ex = Counter()
    kept = dedupe([sd, hbo, starz, paramount, dn], ex)
    assert sorted(s.id for s in kept) == sorted(s.id for s in (dn, hbo, starz, paramount)) and ex["sale: same sale posted elsewhere"] == 1
    assert [(p["source"], p["title"]) for p in dn.also_posted] == [("Slickdeals", sd.title)] and dn.badge == "$5.49/mo"
    # when the post that leads gives no end, the other's is the offer's
    first, _ = one(post("Amazon Prime Video Bundle Offers: 2-Month MGM+, Starz & AMC+ Streaming $5.50/Month", source="dealnews",
                        seller="Amazon", days_ago=5))
    later, _ = one(post("Prime Video Black Friday AMC+, MGM+ & STARZ Bundle Deals for $5.49/mo for 2 months", seller="Amazon", days_ago=1, **nov30))
    led = dedupe([later, first], Counter())
    assert [s.id for s in led] == [first.id] and first.ends_at == later.ends_at and first.ends_how == "dealnews gives this end date"
    # the same services for another term, or at another price, are another offer
    six, _ = one(post("Amazon Prime Video Bundle Offers: 6-Month MGM+, Starz & AMC+ Streaming $5.50/Month", source="slickdeals", seller="Amazon"))
    dear, _ = one(post("Amazon Prime Video Bundle Offers: 2-Month MGM+, Starz & AMC+ Streaming $6/Month", source="slickdeals", seller="Amazon"))
    assert len(dedupe([dn, six, dear], Counter())) == 3
    assert same_price("$5.49/mo", "$5.50/mo") and same_price("$14.99/mo", "$15/mo") and same_price("$36", "$36")
    assert not same_price("$5.49/mo", "$5.59/mo") and not same_price("$5.49/mo", "$5.50") and not same_price("From $2.99/mo", "$3/mo")
    assert not same_price("Up to 50%", "Up to 50%") and not same_price("Free", "Free")           # not prices: those must be the same badge
    # a store's sale is compared as before: one end stated and one not are two
    from slomp.sales import StoreSales
    a = StoreSales(None, None).sale(Post(source="dealnews", id="dealnews:1", url="u", title="Kohl's Black Friday Sale: Up to 50% off + free shipping",
                                         text="", seller="Kohl's", deal_type="sale", category="Clothing", posted_at=NOW - timedelta(days=1),
                                         **nov30), NOW, Counter())
    b = StoreSales(None, None).sale(Post(source="hip2save", id="hip2save:2", url="u", title="Kohl's Black Friday Sale: Up to 50% Off",
                                         text="", posted_at=NOW - timedelta(days=1)), NOW, Counter())
    assert a and b and len(dedupe([a, b], Counter())) == 2


def test_a_stores_sale_filed_under_streaming_services_is_not_a_subscription():
    # run 174, Nov 25, 2026: dealnews filed this under Streaming Services and it was listed as a subscription
    words = ("Musician's Friend is running its Black Friday sale with discounts across guitars, basses, amps, keyboards, drums, recording "
             "gear, and DJ equipment. Promo code \"BLACKFRIDAY\" adds savings on Fender, D'Angelico, Simmons, and other select brands. "
             "Shipping is free. Sale ends November 29. Shop Now at Musician's Friend")
    mf = post("Musician's Friend Black Friday Deals: Up to 60% off + free shipping", words, category="Streaming Services",
              seller="Musician's Friend", deal_type="sale")
    assert ent.a_stores_sale(mf) and ent.kind_of(mf) == ""
    s, why = one(mf)
    assert s is None or (s.what == "" and "entertainment" not in s.industries), why          # judged as any store's sale is
    # a subscription service's own sale names none in its title, and its words do
    mc = post("MasterClass Pre-Black Friday Sale: 50% off", "MasterClass is taking 50% off the first year of a membership in its "
              "Pre-Black Friday sale.", category="Streaming Services", seller="MasterClass", deal_type="sale")
    assert ent.kind_of(mc) == "subscription" and one(mc)[0].what == "subscription"
    # shipping settles nothing: dealnews ends a streaming plan's title the same way
    for title in ("Disney+ Hulu Bundle 6-Month Streaming Deal: 50% off for 6 months + free shipping",
                  "YouTube TV Base Plan New User Offer: $75 off first 5 months + free shipping",
                  "Prime Video Black Friday Subscription Deals: Up to 79% off + free shipping w/ Prime"):
        assert ent.kind_of(post(title, category="Video Streaming Services")) == "subscription", title
    # a price with no term is still left out as before, with its own reason
    assert one(post("I Love Lucy: The Complete Series Digital TV Series for $20 + no shipping required", seller="Fandango"))[1] \
        == "entertainment: not a subscription"
    # only a subscription category is second-guessed, and only dealnews gives one
    assert ent.kind_of(post("Groupon Black Friday Sale: Up to 80% off", category="Things to Do", seller="Groupon")) == "tickets"
