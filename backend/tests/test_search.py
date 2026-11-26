"""Keyword search (slomp/search.py, and the same rule in static/engine.js)."""
import asyncio
import json
import subprocess

from slomp import search
from slomp.service import searched
from test_site import DRIVER, _site, needs_node

# One of each kind of deal, as the API gives them.
AD = {"id": "flipp:1", "title": "Nike Kids' Cosmic Runner PS", "merchant": "Academy Sports + Outdoors", "brand": "",
      "category": "Apparel & Accessories > Shoes", "industries": ["sports", "fashion"],
      "store": {"name": "Academy Sports + Outdoors", "address": "1 Main St, Austin"}, "regular": None, "kind": "deal",
      "terms": {"summary": "$24.99, reg. $51.99", "conditions": []}}
REGULAR = {"id": "regular:hop", "title": "Happy hour: cocktails, beer, wine and sliders half off", "merchant": "Hopdoddy Burger Bar",
           "brand": "Hopdoddy Burger Bar", "category": "restaurant", "industries": ["dining"], "store": {"name": "Hopdoddy Burger Bar"},
           "regular": {"days_text": "Monday to Thursday", "time_text": "3–6 pm"}, "kind": "regular"}
ONLINE = {"id": "dealnews:1", "title": "LEGO Christmas Table Decoration for $24 + free shipping w/ Prime", "seller": "Amazon",
          "category": "LEGO", "industries": ["toys"], "product": {"brand": "LEGO", "model": "40743"}, "conditions": ["promo code"]}
SALE = {"id": "sale:dealnews:2", "store": "kohls", "store_name": "Kohl's", "title": "Kohl's Black Friday Sale: Up to 60% off + free shipping",
        "name": "Black Friday Sale", "offer": "Up to 60% off", "code": "ENJOY15", "conditions": ["Kohl's Rewards members"], "industries": ["fashion"]}
VENUE = {"id": "sale:venue:x", "store": "", "store_name": "L'Oréal Zoo & Café", "title": "Save up to 55% on Tickets, Passes and More!",
         "name": "Black Friday Deals", "offer": "Up to 55% off", "city": "Galveston", "industries": ["entertainment"]}
EVERY = [AD, REGULAR, ONLINE, SALE, VENUE]

# What is typed, and the deals above it should find.
ASKS = {
    "": [0, 1, 2, 3, 4], "   ": [0, 1, 2, 3, 4], "the for of": [0, 1, 2, 3, 4],       # nothing asked: every deal
    "nike": [0], "NIKE": [0], "nike shoes": [0], "shoe": [0], "shoes for kids": [0], "kid": [0],
    "run": [0], "runner": [0], "runners": [0], "academy": [0], "apparel": [0],
    "lego": [2], "Lego decorations": [2], "decoration": [2], "40743": [2], "amazon": [2], "promo": [2],
    "kohls": [3], "kohl's": [3], "KOHL’S": [3], "enjoy15": [3], "rewards": [3], "friday": [3, 4], "black friday sale": [3],
    "loreal": [4], "l'oreal": [4], "L'Oréal": [4], "cafe": [4], "café": [4], "galveston": [4], "passes": [4], "pass": [4],
    "ticket": [4], "zoo café": [4],
    "happy hour": [1], "thursday": [1], "burger": [1], "burgers": [1], "cocktail": [1], "sliders half off": [1],
    "t-shirt": [], "lens": [], "nike lego": [], "zzyzx": [], "shoes amazon": [],
    "up to": [3, 4],                                 # "to" is not asked for; "up" is
    "55": [4], "60% off": [3], "24": [2],            # a price is found where the title states it, not in the ad's terms
}


def found(q):
    return [i for i, d in enumerate(EVERY) if search.matches(d, search.words(q))]


def test_every_word_must_be_found_in_what_a_card_shows():
    for q, want in ASKS.items():
        assert found(q) == want, q


def test_how_words_are_read():
    assert search.fold("Kohl’s L'Oréal T-Shirt 65\" 4K CAFÉ") == "kohls loreal t shirt 65 4k cafe"
    assert search.words("LEGO® Star Wars for the kids, LEGO!") == ["lego", "star", "wars", "kids"]
    assert search.words("the") == [] and search.words(None) == [] and search.query("  the ") is None
    assert search.query("  Nike   SHOES ") == {"q": "Nike SHOES", "words": ["nike", "shoes"]}
    assert len(search.words("one two three four five six seven eight nine ten")) == search.MAX_WORDS
    assert search.words("x" * 300) == ["x" * search.MAX_CHARS]
    # a plural finds its singular and the other way round, a whole word at a time
    pairs = [("shoes", "shoe"), ("boxes", "box"), ("dresses", "dress"), ("batteries", "battery"), ("movies", "movie"),
             ("watches", "watch"), ("tvs", "tv"), ("glasses", "glass")]
    for plural, single in pairs:
        assert search.found(plural, [single]) and search.found(single, [plural]), (plural, single)
    assert not search.found("lens", ["lenovo"]) and search.found("len", ["lenovo"])     # a start, not a made-up singular
    assert not search.found("glass", ["gas"]) and search.found("bus", ["buses"]) and not search.found("buses", ["bu"])
    assert search.singulars("glass") == () and search.singulars("as") == ()


def test_an_answer_is_narrowed_and_its_counts_follow():
    local = {"city": {"id": "austin"}, "deals": [AD, {**AD, "id": "flipp:2", "title": "Apples"}], "promotions": [], "unconfirmed": [],
             "regulars": [REGULAR], "counts": {"deals": 2, "promotions": 0, "unconfirmed": 0, "regulars": 1}, "excluded": {"x": 1}}
    out = search.local(local, search.words("nike"))
    assert [d["id"] for d in out["deals"]] == ["flipp:1"] and out["regulars"] == []
    assert out["counts"] == {"deals": 1, "promotions": 0, "unconfirmed": 0, "regulars": 0} and out["excluded"] == {"x": 1}
    assert local["counts"]["deals"] == 2 and search.local(local, []) is local              # the answer it came from is untouched
    # online: narrowed first, then the best of each industry
    deals = [{"id": f"d{i}", "title": "LEGO set" if i % 2 else "Doll"} for i in range(10)]
    online = {"industries": ["toys"], "deals": {"toys": deals}, "counts": {"toys": 10}}
    out = search.online(online, ["lego"], 3)
    assert [d["id"] for d in out["deals"]["toys"]] == ["d1", "d3", "d5"] and out["counts"] == {"toys": 3}
    assert search.online(online, [], 3) is online
    sales = {"sales": [SALE, VENUE, {**SALE, "id": "s3", "name": "Friday Flash Sale"}], "counts": {"sales": 3, "stores": 2}, "stores": {"kohls": {}}}
    out = search.sales(sales, ["friday"])
    assert len(out["sales"]) == 3 and out["counts"] == {"sales": 3, "stores": 2}
    out = search.sales(sales, ["kohls"])
    assert len(out["sales"]) == 2 and out["counts"] == {"sales": 2, "stores": 1} and out["stores"] == {"kohls": {}}


def test_keywords_with_no_industry_search_them_all():
    from slomp import industries as ind
    assert searched("", "lego") == (list(ind.IDS), ["lego"])
    assert searched("tech,toys", "lego") == ("tech,toys", ["lego"])
    assert searched("", "") == ("", []) and searched("", "the") == ("", [])               # nothing asked: an industry is needed
    assert searched([], "lego")[0] == list(ind.IDS) and searched(["tech"], "lego")[0] == ["tech"]


def test_the_api_narrows_every_part_of_a_search(tmp_path, monkeypatch):
    import httpx

    from slomp import api, industries as ind
    monkeypatch.setenv("SLOMP_WARM", "0")
    monkeypatch.setenv("SLOMP_CACHE_DIR", str(tmp_path))
    asked_for = []

    class Local:
        def to_dict(self):
            return {"deals": [AD, {**AD, "id": "flipp:2", "title": "Apples"}], "promotions": [], "unconfirmed": [], "regulars": [REGULAR],
                    "counts": {"deals": 2, "promotions": 0, "unconfirmed": 0, "regulars": 1}}

    class Online:
        def __init__(self, inds, limit):
            self.inds, self.limit = inds, limit

        def to_dict(self):
            rows = [{"id": f"d{k}", "title": "LEGO set" if k % 2 else "Doll"} for k in range(self.limit)]
            return {"industries": self.inds, "deals": {i: rows for i in self.inds}, "counts": {i: len(rows) for i in self.inds}}

    async def go():
        async with api.lifespan(api.app):
            s = api.app.state.slomp

            async def local(city, industries, radius_mi=25.0, **k):
                asked_for.append(("local", list(industries) if not isinstance(industries, str) else industries))
                return Local()

            async def online(industries, limit=25, **k):
                asked_for.append(("online", limit))
                return Online(list(industries) if not isinstance(industries, str) else industries.split(","), limit)

            async def sales(industries, **k):
                return {"industries": list(industries), "sales": [SALE, VENUE], "counts": {"sales": 2, "stores": 2}, "stores": {}}
            s.local, s.online, s.sales = local, online, sales
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api.app), base_url="http://slomp") as c:
                get = lambda path, **p: c.get(path, params=p)                                       # noqa: E731
                return [(r.status_code, r.json()) for r in [
                    await get("/api/v1/search", city="austin", q="lego", limit=2),
                    await get("/api/v1/search", city="austin", industries="tech", limit=2),
                    await get("/api/v1/search", city="austin"),
                    await get("/api/v1/local", city="austin", industries="sports", q="nike shoes"),
                    await get("/api/v1/online", q="lego", limit=4),
                    await get("/api/v1/sales", industries="fashion,entertainment", q="galveston")]]
    (_, every), (_, plain), (bad, _), (_, loc), (_, onl), (_, sal) = asyncio.run(go())
    # keywords and no industry: every industry, every online deal kept looked through, the best two that say the word
    assert asked_for[0] == ("local", list(ind.IDS)) and ("online", 100) in asked_for[:3]
    assert every["query"] == {"q": "lego", "words": ["lego"]}
    assert every["local"]["counts"] == {"deals": 0, "promotions": 0, "unconfirmed": 0, "regulars": 0}
    assert all([d["id"] for d in rows] == ["d1", "d3"] for rows in every["online"]["deals"].values()) and every["sales"]["sales"] == []
    # no keywords: as before, with the industry chosen and the page of deals asked for
    assert plain["query"] is None and plain["local"]["counts"]["deals"] == 2 and plain["online"]["counts"] == {"tech": 2}
    assert bad == 422                                                                          # neither words nor an industry
    assert [d["id"] for d in loc["deals"]] == ["flipp:1"] and loc["query"]["words"] == ["nike", "shoes"]
    assert set(onl["deals"]) == {i for i in ind.IDS if ind.BY_ID[i].online} and onl["counts"]["toys"] == 4
    assert [s["id"] for s in sal["sales"]] == ["sale:venue:x"] and sal["counts"] == {"sales": 1, "stores": 1}


RULES = r"""
const path = require("path"), fs = require("fs");
const [engineJs, casesPath] = process.argv.slice(1);
const {keywords: K} = require(engineJs);
const {items, asks, texts} = JSON.parse(fs.readFileSync(casesPath, "utf8"));
process.stdout.write(JSON.stringify({
  found: asks.map(q => items.map((d, i) => K.says(d, K.words(q)) ? i : -1).filter(i => i >= 0)),
  words: asks.map(q => K.words(q)), fold: texts.map(t => K.fold(t))}));
"""


@needs_node
def test_the_engine_reads_and_matches_words_as_the_server_does(tmp_path):
    from test_site import STATIC
    asks = list(ASKS) + ["Ünïcödé naïve", "İstanbul", "ﬁne ½ price", "x" * 300, "a b c d e f g h i j k l", "straße", "日本語 lego", "tab\there\nnow"]
    texts = asks + [search.said(d) for d in EVERY] + ["Kohl’s L'Oréal T-Shirt 65\" 4K CAFÉ", "Ｆｕｌｌｗｉｄｔｈ Ⅷ ²", "é è é ñ"]
    (tmp_path / "cases.json").write_text(json.dumps({"items": EVERY, "asks": asks, "texts": texts}))
    out = subprocess.run(["node", "-e", RULES, str(STATIC / "engine.js"), str(tmp_path / "cases.json")], capture_output=True, text=True, check=True)
    got = json.loads(out.stdout)
    assert got["fold"] == [search.fold(t) for t in texts]
    assert got["words"] == [search.words(q) for q in asks]
    assert got["found"] == [found(q) for q in asks]


@needs_node
def test_the_engine_narrows_a_search_as_the_server_would(tmp_path):
    site = _site(tmp_path)
    # the small site's online deals and sales, with words to find
    data = site / "data"
    (data / "online" / "grocery.json").write_text(json.dumps({
        "generated_at": "2026-10-06T19:00:00+00:00", "excluded": {}, "sources": [],
        "deals": {"grocery": [{"id": f"g{k}", "title": "Honeycrisp Apples 3-lb. Bag" if k % 3 == 0 else "Cheese", "seller": "Mart"} for k in range(9)]}}))
    (data / "sales.json").write_text(json.dumps({
        "generated_at": "2026-10-06T18:00:00+00:00", "excluded": {}, "sources": [], "stores": {},
        "sales": [{"id": "s1", "store": "mart", "store_name": "Mart", "title": "Mart Apple Week: Up to 30% off", "name": "Apple Week", "offer": "Up to 30% off",
                   "industries": ["grocery"], "score": 15, "posted_at": "2026-10-06T10:00:00+00:00"},
                  {"id": "s2", "store": "", "store_name": "Cheese Shop", "title": "Cheese Shop Sale: 20% off", "name": "Sale", "offer": "20% off",
                   "industries": ["grocery"], "score": 20, "posted_at": "2026-10-06T10:00:00+00:00"}]}))
    meta = json.loads((data / "meta.json").read_text())
    for i in meta["industries"]:
        i["sales"] = i["online"]
    (data / "meta.json").write_text(json.dumps(meta))
    base = {"city": "alpha", "radius_mi": 10, "now": "2026-10-06T15:00:00-05:00"}
    cases = [{**base, "industries": "grocery,tech,dining", "limit": 100},                       # everything, no words
             {**base, "industries": "grocery,tech,dining", "limit": 2, "q": "apples"},
             {**base, "limit": 2, "q": "apple"},                                              # no industry: every one
             {**base, "industries": "dining", "q": "tuesday movie"},
             {**base, "industries": "grocery", "q": "the"},                                    # nothing asked
             {**base, "q": ""}]                                                                # neither
    (tmp_path / "cases.json").write_text(json.dumps(cases))
    out = subprocess.run(["node", "-e", DRIVER, str(site), str(tmp_path / "cases.json")], capture_output=True, text=True, check=True)
    full, apples, apple, cinema, nothing, neither = json.loads(out.stdout)
    assert full["query"] is None and len(full["online"]["deals"]["grocery"]) == 9 and full["local"]["counts"]["deals"] >= 2

    def narrowed(q, limit):                       # what slomp/search.py makes of the engine's own full answer
        asked = search.words(q)
        return {"local": search.local(full["local"], asked), "online": search.online(full["online"], asked, limit),
                "sales": search.sales(full["sales"], asked), "query": search.query(q)}
    ids = lambda rows: [d["id"] for d in rows]                                                 # noqa: E731
    for got, (q, limit) in ((apples, ("apples", 2)), (apple, ("apple", 2))):
        want = narrowed(q, limit)
        assert got["query"] == want["query"]
        for key in ("deals", "promotions", "unconfirmed", "regulars"):
            assert ids(got["local"][key]) == ids(want["local"][key]), (q, key)
        assert got["local"]["counts"] == want["local"]["counts"]
        assert {i: ids(v) for i, v in got["online"]["deals"].items()} == {i: ids(v) for i, v in want["online"]["deals"].items()}
        assert got["online"]["counts"] == want["online"]["counts"]
        assert ids(got["sales"]["sales"]) == ids(want["sales"]["sales"]) and got["sales"]["counts"] == want["sales"]["counts"]
    assert [d["title"] for d in apples["local"]["deals"]] == ["Apples"] and ids(apples["online"]["deals"]["grocery"]) == ["g0", "g3"]
    assert ids(apples["sales"]["sales"]) == ["s1"] and apples["sales"]["counts"] == {"sales": 1, "stores": 1}
    assert apple["local"]["industries"] == ["grocery", "tech", "dining"] and apple["query"] == {"q": "apple", "words": ["apple"]}
    assert ids(cinema["local"]["regulars"]) == ids(full["local"]["regulars"]) and cinema["query"]["words"] == ["tuesday", "movie"]
    assert nothing["query"] is None and nothing["local"]["industries"] == ["grocery"] and len(nothing["online"]["deals"]["grocery"]) == 9
    assert "error" in neither and "shopping for" in neither["error"]
