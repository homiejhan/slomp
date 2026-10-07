"""The home page's biggest deals (slomp/top.py): which deals count, how big each one is, which nine show and when,
the server's use of what it has already read, and engine.js picking the same nine from the published site's file
(needs Node). Regular deals are real registry entries (slomp/data/regulars.json, Oct 7, 2026) at their real chains;
posts, online deals and sales are made up in the shape the feeds give."""
from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import time
from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from slomp import top
from slomp.config import Settings
from slomp.models import OnlineDeal, StoreSale
from slomp.online import OnlineResult, score as online_score
from slomp.promos import RestaurantPromos
from slomp.regulars import Evidence, RegularSet, from_entry
from slomp.sales import SalesResult
from slomp.service import SlompService
from slomp.site import STATIC
from slomp.sources.feeds import Post
from slomp.sources.stores import RestaurantLocator
from slomp.sources.venues import Venues

CT = ZoneInfo("America/Chicago")
NOW = datetime(2026, 10, 7, 10, 0, tzinfo=CT)          # a Wednesday morning
V = Venues()

ENTRIES = [
    {"id": "main-event-kids-bowl-free", "brand": "Main Event", "summary": "kids bowl free", "days": ["weekdays"],
     "offer": "Kids Bowl Free: 2 free games of bowling for kids 15 and under, Monday to Friday until 5 pm",
     "industries": ["entertainment"], "time": "until 5 pm", "until": "2026-10-31",
     "conditions": ["kids 15 and under", "participating locations"]},
    {"id": "main-event-monday-night-madness", "brand": "Main Event", "days": ["mon"], "price": 12.99,
     "offer": "Monday Night Madness: all-you-can-play activities or games for $12.99 a person",
     "industries": ["entertainment"], "time": "after 4 pm", "conditions": ["participating locations"]},
    {"id": "dave-busters-half-price-games", "brand": "Dave & Buster's", "days": ["wed", "sun"], "pct": 50,
     "offer": "Half-price games every Wednesday and Sunday", "industries": ["entertainment"],
     "conditions": ["in store only"]},
    {"id": "topgolf-half-off-golf", "brand": "Topgolf", "days": ["mon", "tue", "wed", "thu"], "pct": 50,
     "offer": "Half-Off Golf: 50% off game play all day Monday to Thursday when you book online",
     "industries": ["entertainment"], "conditions": ["participating venues"]},
    {"id": "schlotzskys-bogo-wednesday", "brand": "Schlotzsky's", "days": ["wed"], "bogo": "buy 1 get 1 free",
     "offer": "BOGO Wednesday: buy one pizza, flatbread or calzone and get one free"},
    {"id": "outback-kids-eat-free-monday", "brand": "Outback Steakhouse", "days": ["mon"], "summary": "kids eat free",
     "offer": "Kids eat free every Monday: a free kids' meal with every adult entrée",
     "conditions": ["with an adult entrée", "participating locations"]},
    {"id": "pluckers-kids-eat-free-tuesday", "brand": "Pluckers Wing Bar", "days": ["tue"], "summary": "kids eat free",
     "offer": "Kids eat free all day on Tuesdays: two free kids meals per adult entrée",
     "conditions": ["kids 10 and under", "dine-in only"]},
    {"id": "cinemark-discount-tuesdays", "brand": "Cinemark", "days": ["tue"], "pct": 50, "hedge": "up to",
     "offer": "Discount Tuesdays: movie tickets up to 50% off, all day", "industries": ["entertainment"]},
    {"id": "chuck-e-cheese-winning-wednesday", "brand": "Chuck E. Cheese", "days": ["wed"], "pct": 30,
     "offer": "Winning Wednesday: 30% off All You Can Play", "industries": ["entertainment"]},
    # Left out: a central-Texas chain, one area's operator of a chain, one zoo, a monthly deal not due this week.
    {"id": "kerbey-lane-kids-eat-free-tuesday", "brand": "Kerbey Lane Cafe", "days": ["tue"], "summary": "kids eat free",
     "offer": "Kids eat free every Tuesday: one free kids meal with an adult entrée", "conditions": ["with an adult entrée"]},
    {"id": "goodwill-central-texas-color-tag-wednesday", "brand": "Goodwill Central Texas", "venue": "Goodwill",
     "days": ["wed"], "pct": 60, "offer": "Color Tag Day: one tag color is 60% off each Wednesday",
     "area": {"lat": 30.2672, "lon": -97.7431, "mi": 40}, "industries": ["fashion", "home"]},
    {"id": "houston-zoo-free-first-tuesday", "brand": "Houston Zoo", "days": ["first tue"], "kind": "zoo",
     "summary": "free admission", "offer": "Free Zoo Day: free admission on the first Tuesday of the month",
     "industries": ["entertainment"]},
    {"id": "walgreens-seniors-day", "brand": "Walgreens", "days": ["first tue"], "pct": 20,
     "offer": "Seniors Day: 20% off regular-price items on the first Tuesday of the month"},
]


def regulars():
    out = []
    for e in ENTRIES:
        r = from_entry(e, V, "registry", NOW.date())
        assert not isinstance(r, str), (e["id"], r)
        kind = "list" if r.brand == "Chuck E. Cheese" else "official"     # known from a deal list only: 0.75
        r.evidence = [Evidence(kind=kind, source="example.com", url="https://example.com/" + r.id, found=True,
                               live=True)]
        out.append(r)
    mine = from_entry({"brand": "Topgolf", "days": ["fri"], "pct": 90, "offer": "My own 90% off Fridays"}, V, "yours",
                      NOW.date())
    mine.evidence = [Evidence(kind="yours", source="you", live=True)]
    return out + [mine]


def post(title, seller="", text="", posted=NOW - timedelta(hours=5), **kw):
    return Post(source="dealnews", id=f"dealnews:{abs(hash(title))}", url=f"https://example.com/p{abs(hash(title))}",
                title=title, text=text, seller=seller, posted_at=posted, **kw)


POSTS = [
    post("Krispy Kreme: Free Original Glazed Doughnut, today only", "Krispy Kreme"),
    post("Buffalo Wild Wings: BOGO Free Boneless Wings on Thursdays", "Buffalo Wild Wings"),
    post("Free Medium Fries w/ Any Purchase in the McDonald's App", "McDonald's"),
    post("Wendy's: Free Jr. Cheeseburger with Any Purchase in the App", "Wendy's"),
    post("P. Terry's: Free Burger with Any Purchase", "P. Terry's"),                 # an Austin-area chain
    post("Chili's: $25 Gift Card for $20", "Chili's"),                              # not a promotion
    post("Pizza Hut: Free Breadsticks", "Pizza Hut", posted=NOW - timedelta(days=5)),   # no dates, too old
]


def online_deal(i, title, seller, store_key, price, ref, basis, **kw):
    d = OnlineDeal(id=f"dn:{abs(hash(title))}", source="dealnews", source_url="https://example.com/o" + str(i),
                   title=title, seller=seller, price=price, industries=[kw.pop("ind", "tech")], industry_rule="test",
                   reference_price=ref, basis=basis, pct=round(100 * (1 - price / ref), 1), store_key=store_key,
                   posted_at=NOW - timedelta(hours=8), **kw)
    d.score = online_score(d)
    return d


ONLINE = [
    online_deal(1, "Ninja 6-qt. Air Fryer", "Walmart", "walmart", 59.0, 99.0, "market", ind="home"),
    online_deal(2, "Apple AirPods Pro 2", "Amazon", "amazon", 169.99, 249.0, "market"),
    online_deal(3, "Anker 20W USB-C Charger 2-Pack", "Amazon", "amazon", 9.99, 25.99, "list"),
    online_deal(4, "Samsung 65\" OLED TV", "Best Buy", "bestbuy", 1299.99, 2199.99, "list",
                expires_at=NOW + timedelta(days=2)),
    online_deal(5, "Gaming Mouse", "Gadget Shop", "", 9.0, 59.0, "list"),          # not a store in the registry
]


def sale(key, name, store, badge, score, ends=None, code="", posted=NOW - timedelta(hours=6), store_name=None):
    return StoreSale(id=f"sale:{key}", store=store, store_name=store_name or name, title=f"{name}: {badge}",
                     name=f"{name} sale", offer=badge, badge=badge, code=code, ends_at=ends, posted_at=posted,
                     source="dealnews", source_url=f"https://example.com/s-{key}", industries=["fashion"],
                     discount_pct=score, score=score)


SALES = [
    sale("oldnavy", "Old Navy", "oldnavy", "50% off", 50.0, ends=NOW + timedelta(days=3)),
    sale("nike", "Nike", "nike", "Up to 50% off + extra 25%", 43.8, ends=NOW + timedelta(days=5)),
    sale("kohls", "Kohl's", "kohls", "Extra 30% off", 30.0, ends=NOW + timedelta(days=1), code="SAVE30"),
    sale("target", "Target", "target", "Up to 50% off", 25.0, ends=NOW + timedelta(days=4)),
    sale("local", "Corner Shop", "", "70% off", 70.0, ends=NOW + timedelta(days=4)),   # not in the registry
    sale("ended", "Gap", "gap", "60% off", 60.0, ends=NOW - timedelta(hours=1)),
]


def world():
    return SimpleNamespace(regulars=regulars(), promos=RestaurantPromos(None, RestaurantLocator()), posts=POSTS,
                           online=[OnlineResult(["tech"], {"tech": ONLINE})], sales=SalesResult(sales=list(SALES)))


def pool(now=NOW):
    w = world()
    return top.candidates(now, w.regulars, w.promos, w.posts, w.online, w.sales)


def brands(deals):
    return [d["top"]["brand"] for d in deals]


# --- which chains count -------------------------------------------------------------------------------------------
def test_a_chain_counts_when_its_branches_are_all_over_texas():
    for name in ("Main Event", "Cinemark", "Taco Cabana", "Dave & Buster's"):
        assert top.statewide(V.find(name).locations), name
    # Kerbey Lane Cafe's 10 branches run from Round Rock to San Antonio; Star Cinema Grill's are around Houston;
    # Galaxy has 2. P. Terry's has 28, from Austin to San Antonio.
    for name in ("Kerbey Lane Cafe", "Star Cinema Grill", "Galaxy Theatres"):
        assert not top.statewide(V.find(name).locations), name
    pterrys = RestaurantLocator().brand("P. Terry's")[0]
    assert len(top._branches(pterrys)) >= top.MIN_BRANCHES and not top.statewide(top._branches(pterrys))


# --- how big a deal is ----------------------------------------------------------------------------------------------
def test_how_big_a_deal_is_as_best_deal_first_counts_it():
    assert top.badge_pct({"discount_pct": 32.4, "terms": {"pct": 50}}) == 32.4
    assert top.badge_pct({"terms": {"pct": 50, "summary": "half price"}}) == 50
    assert top.badge_pct({"title": "Kids Bowl Free", "terms": {"summary": "kids bowl free"}}) == 100
    assert top.badge_pct({"title": "x", "terms": {"summary": "kids eat free"}}) == 50
    assert top.badge_pct({"title": "x", "terms": {"summary": "free taco", "conditions": ["with a $1 purchase"]}}) == 50
    assert top.badge_pct({"title": "Free Medium Fries w/ Any Purchase", "terms": {"summary": "free medium fries"}}) == 50
    assert top.badge_pct({"title": "$12.99 all you can play", "terms": {"price": 12.99, "summary": "$12.99"}}) is None


def test_ranks_weigh_the_size_by_what_backs_it():
    ranked = {d["id"]: d["top"]["rank"] for d in pool()}
    assert ranked["regular:main-event-kids-bowl-free"] == 90.0         # free, confirmed by the company: 100 x 0.9
    assert ranked["regular:dave-busters-half-price-games"] == 45.0     # half price: 50 x 0.9
    assert ranked["regular:cinemark-discount-tuesdays"] == 22.5        # "up to" halves it
    assert ranked["regular:chuck-e-cheese-winning-wednesday"] == 20.25  # known from one deal list: x 0.75
    bww = next(d for d in pool() if d["top"]["brand"] == "Buffalo Wild Wings")
    assert bww["top"]["rank"] == 31.5 and bww["terms"]["bogo"] == "buy 1 get 1 free"   # BOGO, from one post: x 0.7


# --- the candidates ---------------------------------------------------------------------------------------------
def test_candidates_are_chains_found_all_over_texas_and_the_big_online_stores():
    p = pool()
    by_kind = {k: brands(d for d in p if d["top"]["kind"] == k) for k in top.KINDS}
    assert by_kind["regular"] == ["Main Event", "Dave & Buster's", "Outback Steakhouse", "Pluckers Wing Bar",
                                  "Schlotzsky's", "Topgolf", "Cinemark", "Chuck E. Cheese"]
    assert by_kind["promotion"] == ["Krispy Kreme", "Buffalo Wild Wings", "McDonald's", "Wendy's"]
    assert by_kind["online"] == ["Walmart", "Amazon", "Best Buy"]          # Amazon's best deal only
    assert by_kind["sale"] == ["Old Navy", "Nike", "Kohl's", "Target"]
    # Each carries what the page needs: a regular deal its schedule, a sale its code, an online deal its store.
    me = p[0]
    assert me["store"] is None and me["regular"]["next"][0] == "2026-10-07" and me["regular"]["time_text"] == "until 5 pm"
    assert me["top"] == {"kind": "regular", "brand": "Main Event", "key": "mainevent", "rank": 90.0, "from": None,
                         "until": "2026-10-31T23:59:59-05:00", "branches": len(V.find("Main Event").locations)}
    assert next(d for d in p if d["top"]["brand"] == "Kohl's")["code"] == "SAVE30"
    assert next(d for d in p if d["top"]["brand"] == "Best Buy")["top"]["until"] == "2026-10-09T10:00:00-05:00"


def test_each_kind_keeps_its_best_few():
    from slomp.stores_online import registry
    keys = [s.key for s in registry()][:top.POOL + 3]
    many = SalesResult(sales=[sale(k, k, k, f"{60 - i}% off", 60.0 - i, ends=NOW + timedelta(days=2))
                              for i, k in enumerate(keys)])
    kept = top.candidates(NOW, sales=many)
    assert [d["store"] for d in kept] == keys[:top.POOL]


# --- the nine -------------------------------------------------------------------------------------------------------
def test_nine_deals_one_per_brand_three_of_a_kind_at_most_and_each_three_mixed():
    shown = top.pick(pool(), NOW)
    assert brands(shown) == ["Main Event", "Krispy Kreme", "Old Navy",
                             "Dave & Buster's", "Nike", "Walmart",
                             "Outback Steakhouse", "Amazon", "Buffalo Wild Wings"]
    kinds = [d["top"]["kind"] for d in shown]
    assert all(kinds.count(k) <= top.PER_KIND for k in top.KINDS)
    for page in range(0, 9, 3):
        assert len(set(kinds[page:page + 3])) == 3


def test_one_kind_fills_in_when_the_others_run_out():
    p = [d for d in pool() if d["top"]["kind"] == "regular"] + [d for d in pool() if d["top"]["brand"] == "Nike"]
    shown = top.pick(p, NOW)
    assert len(shown) == 9 and [d["top"]["kind"] for d in shown].count("sale") == 1
    assert brands(shown)[:3] == ["Main Event", "Nike", "Dave & Buster's"]


def test_what_shows_follows_the_moment():
    p = pool()
    by = {d["top"]["brand"]: d for d in p}
    at = lambda *a: datetime(*a, tzinfo=CT)                                                     # noqa: E731
    assert top.live(by["Krispy Kreme"], at(2026, 10, 7, 23, 59)) and not top.live(by["Krispy Kreme"], at(2026, 10, 8))
    assert not top.live(by["Kohl's"], NOW + timedelta(days=1, seconds=1))           # the sale's end
    assert not top.live(by["Best Buy"], NOW + timedelta(days=2, seconds=1))         # the deal's stated expiry
    # A promotion that gives no dates is shown for 3 days after it was posted.
    assert top.live(by["McDonald's"], at(2026, 10, 10, 23, 59)) and not top.live(by["McDonald's"], at(2026, 10, 11))
    assert not top.live(by["Main Event"], at(2026, 11, 1))                          # its stated end, Oct 31
    # Thursdays' BOGO counts from a week before its first Thursday, as the tabs' 7 days would show it.
    assert by["Buffalo Wild Wings"]["top"]["from"] == "2026-10-01T00:00:00-05:00"
    tomorrow = brands(top.pick(p, NOW + timedelta(days=1)))
    assert "Krispy Kreme" not in tomorrow and "McDonald's" in tomorrow           # the next promotion moves up


def test_the_answer_names_only_its_own_online_stores():
    res = top.payload(pool(), NOW)
    assert res["generated_at"] == "2026-10-07T10:00:00-05:00" and len(res["deals"]) == 9
    assert sorted(res["stores"]) == ["amazon", "nike", "oldnavy", "walmart"]
    assert res["stores"]["oldnavy"]["name"] == "Old Navy" and "logo" in res["stores"]["nike"]


# --- the server ------------------------------------------------------------------------------------------------------
def stub(svc: SlompService, w=None) -> list[str]:
    """The service reads `world()` instead of the sources; tech's online deals are already computed. Returns the list
    of the online industries it computes from then on."""
    w = w or world()
    computed: list[str] = []

    async def regs(refresh=False, now=None):
        return RegularSet(regulars=w.regulars)

    async def posts():
        return w.posts, []

    async def sales(use_cache=True):
        return w.sales

    async def run(inds, limit=25, now=None, compare=True):
        computed.append(inds[0])
        return OnlineResult(inds)
    svc.regulars.all, svc.promos.posts, svc.sales_result, svc.online_deals.run = regs, posts, sales, run
    svc._cache[("online", "tech", True)] = (time.time(), w.online[0])
    return computed


def test_the_server_uses_the_online_deals_it_has_and_reads_the_others_in_the_background(tmp_path):
    svc = SlompService(Settings(cache_dir=tmp_path, offline=True))
    computed = stub(svc)

    async def go():
        first = await svc.top(NOW)
        await svc._refreshing
        return first
    try:
        res = asyncio.run(go())
    finally:
        asyncio.run(svc.aclose())
    assert "Walmart" in brands(res["deals"])                   # tech was ready
    assert computed == [i for i in top.ONLINE_IDS if i != "tech"]   # the rest, one at a time, for the next visit


def test_the_api_answers_with_the_home_pages_deals(tmp_path, monkeypatch):
    import httpx
    from slomp import api
    monkeypatch.setenv("SLOMP_WARM", "0")
    monkeypatch.setenv("SLOMP_CACHE_DIR", str(tmp_path))

    async def go():
        async with api.lifespan(api.app):
            s = api.app.state.slomp
            stub(s)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api.app), base_url="http://slomp") as c:
                r = await c.get("/api/v1/top")
            if s._refreshing:
                await s._refreshing
            return r
    r = asyncio.run(go())
    assert r.status_code == 200
    res = r.json()                      # at the real moment: the weekly deals with no end are always among them
    assert res["deals"] and all(d["top"]["kind"] in top.KINDS for d in res["deals"])
    assert len({d["top"]["key"] for d in res["deals"]}) == len(res["deals"]) and isinstance(res["stores"], dict)


def test_the_published_sites_file_holds_the_whole_pool(tmp_path):
    from slomp.site import top_file
    svc = SlompService(Settings(cache_dir=tmp_path, offline=True))
    computed = stub(svc)
    try:
        f = asyncio.run(top_file(svc, NOW))
    finally:
        asyncio.run(svc.aclose())
    assert set(f) == {"built", "candidates", "stores"} and f["built"] == "2026-10-07T10:00:00-05:00"
    assert [d["id"] for d in f["candidates"]] == [d["id"] for d in pool()]          # every kind's best, not just 9
    assert sorted(f["stores"]) == ["amazon", "bestbuy", "kohls", "nike", "oldnavy", "target", "walmart"]
    assert computed == [i for i in top.ONLINE_IDS if i != "tech"]                   # the build waits for them all


def test_the_command_line_prints_the_nine_as_the_page_groups_them(capsys):
    from slomp.cli import print_top
    print_top(top.payload(pool(), NOW))
    out = capsys.readouterr().out.splitlines()
    assert out[0].startswith("9 biggest deals") and out[1].split()[:3] == ["90.0", "regular", "Main"]
    assert out.count("") == 2                                                      # three groups of three
    assert "promotion Krispy Kreme: Free Original Glazed Doughnut, today only" in out[3]     # not "Krispy Kreme: Krispy…"
    assert "ends 2026-10-10" in out[6] and "40% off, vs other stores' current prices" in out[13]


# --- engine.js -------------------------------------------------------------------------------------------------------
DRIVER = r"""
const fs = require("fs"), path = require("path");
const [site, momentsPath] = process.argv.slice(1);
const engine = require(path.join(site, "engine.js"));
engine.configure({loader: p => Promise.resolve(JSON.parse(fs.readFileSync(path.join(site, "data", p), "utf8")))});
(async () => {
  const out = [];
  for (const now of JSON.parse(fs.readFileSync(momentsPath, "utf8"))) out.push(await engine.top({now}));
  process.stdout.write(JSON.stringify(out));
})();
"""
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="Node isn't installed")


@needs_node
def test_the_published_site_picks_the_same_nine_as_the_server(tmp_path):
    p = pool()
    data = tmp_path / "data"
    data.mkdir()
    shutil.copy(STATIC / "engine.js", tmp_path / "engine.js")
    (data / "meta.json").write_text(json.dumps({"built": "2026-10-07T10:00:00-05:00", "cities": []}))
    (data / "top.json").write_text(json.dumps({"built": "2026-10-07T10:00:00-05:00", "candidates": p,
                                               "stores": top.stores_of(p)}))
    moments = [NOW, NOW + timedelta(hours=6), NOW + timedelta(days=1), NOW + timedelta(days=2, hours=1),
               datetime(2026, 10, 9, 10, 0, tzinfo=CT), datetime(2026, 11, 1, 9, tzinfo=CT)]
    (tmp_path / "moments.json").write_text(json.dumps([m.isoformat() for m in moments]))
    out = subprocess.run(["node", "-e", DRIVER, str(tmp_path), str(tmp_path / "moments.json")], capture_output=True,
                         text=True, check=True)
    pages = json.loads(out.stdout)
    for m, page in zip(moments, pages):
        server = top.payload(json.loads(json.dumps(p)), m)
        assert [d["id"] for d in page["deals"]] == [d["id"] for d in server["deals"]], m
        assert page["stores"] == server["stores"]
    assert pages[0]["generated_at"] == "2026-10-07T10:00:00-05:00"
