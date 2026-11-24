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
