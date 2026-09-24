import json

import httpx
import pytest

from fakeweb import NOW, FakeWeb, austin_routes
from plum.local import LocalDealService, matches_query
from plum.models import Presence
from plum.net import HttpClient
from plum.render import jsonable, render_deals, render_search


def service(routes=None, **kw):
    web = FakeWeb(routes or austin_routes())
    return LocalDealService(HttpClient(transport=httpx.MockTransport(web), backoff_s=0), clock=lambda: NOW, **kw), web


async def test_deals_rank_firm_savings_and_explain_everything_else():
    svc, web = service()
    rep = await svc.deals("Austin, TX", limit=5, promo_limit=5)
    await svc.aclose()

    assert rep.place.postal_code == "78701" and [f.merchant for f in rep.upcoming] == ["Walgreens"]
    assert [(d.merchant, d.terms.price, d.terms.was, d.terms.pct_off) for d in rep.deals] == [
        ("Best Buy", 8.49, 26.99, 68.5), ("Belk", 29.99, 59.99, 50.0),
        ("Best Buy", 148.0, 248.0, 40.3), ("Best Buy", 179.99, 219.99, 18.2)]
    # CVS's "You save 76.00" has no regular price in the data, and a BOGO's 50% headline is a 25% saving
    assert [(d.title[:12], d.terms.hedge, d.terms.pct_off) for d in rep.promos] == [
        ("So De La Ren", "no reference", 75.0), ("ALL Osteo Bi", "", 25.0)]
    assert rep.skipped == {"price only, no saving stated": 2, "not an item (ad banner or page element)": 1,
                           "same item in another ad": 1}
    assert rep.complete and rep.items_seen == 10

    sony = next(d for d in rep.deals if d.title.startswith("Sony"))
    assert sony.store.address == "1201 Barbara Jordan Boulevard, Austin" and sony.detailed
    assert sony.product_url.startswith("https://www.bestbuy.com/") and sony.source_url.endswith("/item/8101")
    belk = next(d for d in rep.deals if d.merchant == "Belk")
    assert belk.store is None and "nearest mapped Belk is 76 mi away" in belk.flags[0]   # "Belk Beauty" is a salon
    assert rep.presence["Belk"].status == Presence.FAR and rep.presence["CVS Pharmacy"].status == Presence.CONFIRMED


async def test_full_records_are_read_only_where_they_can_change_the_answer():
    svc, web = service(batch=1)
    rep = await svc.deals("Austin, TX", limit=1, promo_limit=1)
    await svc.aclose()
    assert [d.title[:6] for d in rep.deals] == ["Barbie"] and [d.title[:6] for d in rep.promos] == ["So De "]
    # Barbie's exact 68.5% beats every unread headline below it (Belk 50%, Sony 40%, fridge 18%)
    assert rep.details_read == 3 and rep.complete
    assert web.hits("/items/8301") == web.hits("/items/8101") == web.hits("/items/8106") == 0


async def test_a_merchant_that_already_filled_its_slots_isnt_read_further():
    svc, web = service(batch=1)
    rep = await svc.deals("Austin, TX", limit=10, per_store=1)
    await svc.aclose()
    assert [d.merchant for d in rep.deals] == ["Best Buy", "Belk"]
    assert web.hits("/items/8101") == web.hits("/items/8106") == 0     # can't beat Best Buy's 68.5%


async def test_budget_exhaustion_is_reported():
    svc, _ = service(batch=1, detail_budget=1)
    rep = await svc.deals("Austin, TX")
    await svc.aclose()
    assert not rep.complete and rep.details_read == 1
    assert "Stopped reading full ad records" in render_deals(rep)


async def test_confirmed_only_drops_merchants_without_a_mapped_store():
    svc, _ = service()
    rep = await svc.deals("Austin, TX", confirmed_only=True)
    await svc.aclose()
    assert "Belk" not in {d.merchant for d in rep.deals} and rep.skipped["no store mapped in range"] == 1


async def test_merchant_and_category_filters():
    svc, _ = service()
    rep = await svc.deals("Austin, TX", merchants=["best buy"])
    assert {d.merchant for d in rep.deals + rep.promos} == {"Best Buy"}
    rep = await svc.deals("Austin, TX", category="Pharmacy")
    await svc.aclose()
    assert {f.merchant for f in rep.flyers} == {"CVS Pharmacy"} and not rep.deals


async def test_a_failed_store_lookup_still_returns_deals_and_says_so():
    routes = austin_routes()
    routes["overpass-api.de/api/interpreter"] = httpx.Response(504, text="<html>too busy</html>")
    svc, _ = service(routes)
    rep = await svc.deals("Austin, TX")
    await svc.aclose()
    assert rep.deals and all(d.flags == ["store locations weren't checked"] for d in rep.deals)
    assert next(s for s in rep.sources if "OpenStreetMap store" in s.name).ok is False


async def test_a_failed_ad_source_returns_an_empty_report_with_the_reason():
    routes = austin_routes()
    routes["backflipp.wishabi.com/flipp/flyers"] = httpx.Response(503)
    svc, _ = service(routes)
    rep = await svc.deals("Austin, TX")
    await svc.aclose()
    assert not rep.deals and not rep.sources[-1].ok and "503" in rep.sources[-1].detail


async def test_unknown_place():
    routes = austin_routes()
    routes["nominatim.openstreetmap.org/search"] = []
    svc, _ = service(routes)
    with pytest.raises(LookupError):
        await svc.deals("Nowhere, ZZ")
    await svc.aclose()


async def test_search_compares_unit_prices_and_prefers_the_store_over_its_pharmacy_pin():
    svc, web = service()
    rep = await svc.search("chicken breasts", "78701")
    await svc.aclose()
    assert [(d.merchant, d.terms.unit_price, d.terms.unit) for d in rep.results] == [
        ("Randalls", 1.79, "lb"), ("H-E-B", 3.99, "lb")]
    assert rep.results[0].terms.conditions == ("limit 10 lb",)            # fine print from the full record
    assert rep.results[1].store.name == "H-E-B"                            # not "H-E-B Pharmacy" next door
    assert rep.skipped == {"an accessory, not the item": 1, "no item name": 1}
    assert web.hits("postalcode=78701") == 1


def test_query_matching():
    assert matches_query("chicken breasts", "Boneless Skinless Chicken Breast") == ""
    assert matches_query("eggs", "Happy Egg Free Range Large Eggs 12 ct.") == ""
    assert matches_query("sony wh-1000xm5", "Sony WH-1000XM6 Headphones") == "a different model"
    assert matches_query("airpods", "Silicone Case for AirPods Pro") == "an accessory, not the item"
    assert matches_query("chicken thighs", "Boneless Chicken Breasts") == "doesn't match the search"


async def test_rendering_and_json():
    svc, _ = service()
    rep = await svc.deals("Austin, TX")
    text = render_deals(rep)
    assert "BEST DEALS" in text and "OTHER OFFERS" in text and "Starting soon: Walgreens (Sep 27)" in text
    assert "68% off, reg. $26.99 · $8.49" in text and "saves $76.00 (the ad gives no regular price)" in text
    assert "store page: https://www.bestbuy.com/" in text and "ends Sep 28" in text
    assert json.loads(json.dumps(jsonable(rep)))["deals"][0]["price_label"] == "$8.49"
    found = await svc.search("chicken breast", "Austin, TX")
    await svc.aclose()
    assert "$1.79/lb" in render_search(found) and "needs: limit 10 lb" in render_search(found)
