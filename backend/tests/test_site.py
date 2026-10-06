"""The published site: the build's offline pieces, and engine.js on a small hand-made dataset (needs Node)."""
from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from slomp.geo import miles
from slomp.reference import cities
from slomp.site import ANCHOR_MI, ANCHOR_POP, STATIC, _zoned_ends, anchors, nearest_anchor, page_html


def test_every_city_is_near_an_anchor_and_every_big_city_is_one():
    a = anchors()
    ids = [x.id for x in a]
    assert ids[0] == "houston" and {"plano", "irving", "denton", "odessa", "round-rock"} <= set(ids)
    for c in cities():
        assert nearest_anchor(c, a)[1] <= ANCHOR_MI
        assert (c.population or 0) < ANCHOR_POP or c.id in ids
    small = [x for x in a if (x.population or 0) < ANCHOR_POP]      # the rest are spread out: 1 per 20 mi
    for x in small:
        assert all(miles(x.lat, x.lon, y.lat, y.lon) > ANCHOR_MI for y in a[:a.index(x)])
    assert [x.id for x in anchors()] == ids                           # the same every run


def test_ad_end_in_eastern_time_is_the_end_of_that_day_in_each_texas_zone():
    # Flipp writes "through Oct 7" as 11:59 PM Eastern and pulls the item then (10:59 PM Central).
    vf = datetime(2026, 10, 1, 0, 0, tzinfo=ZoneInfo("America/New_York"))
    vt = datetime(2026, 10, 7, 23, 59, 59, tzinfo=ZoneInfo("America/New_York"))
    e = _zoned_ends(vf, vt)
    assert e["vf"] == "2026-10-01T00:00:00-05:00" and e["vfm"] == "2026-10-01T00:00:00-06:00"
    assert e["vt"] == "2026-10-07T23:59:59-05:00" and e["vtm"] == "2026-10-07T23:59:59-06:00"
    assert e["gone"] == "2026-10-07T23:59:59-04:00"


def test_an_ad_stated_in_utc_needs_no_mountain_copy_when_it_isnt_normalized():
    vf = datetime.fromisoformat("2026-10-01T15:00:00+00:00")       # mid-day: a real moment, kept as it is
    vt = datetime.fromisoformat("2026-10-07T18:00:00+00:00")
    e = _zoned_ends(vf, vt)
    assert "vfm" not in e and "vtm" not in e and "gone" not in e
    assert e["vt"] == "2026-10-07T13:00:00-05:00"


def test_the_published_page_loads_the_engine_before_its_own_script():
    html = page_html()
    i, j = html.index('<script src="engine.js"></script>'), html.index('"use strict";')
    assert i < j
    assert 'typeof SlompStatic !== "undefined"' in html


# --- engine.js on a hand-made site ------------------------------------------------------------------------------
NOW = "2026-10-06T15:00:00-05:00"          # a Tuesday afternoon in Central time
DRIVER = r"""
const fs = require("fs"), path = require("path");
const [site, casesPath] = process.argv.slice(1);
const engine = require(path.join(site, "engine.js"));
engine.configure({loader: p => Promise.resolve(JSON.parse(fs.readFileSync(path.join(site, "data", p), "utf8")))});
(async () => {
  const out = [];
  for (const c of JSON.parse(fs.readFileSync(casesPath, "utf8"))) {
    try { out.push(await engine.search(c)); } catch (e) { out.push({error: String(e)}); }
  }
  process.stdout.write(JSON.stringify(out));
})();
"""


def _site(tmp: Path) -> Path:
    data = tmp / "data"
    (data / "ads").mkdir(parents=True)
    (data / "online").mkdir()
    shutil.copy(STATIC / "engine.js", tmp / "engine.js")
    city = lambda cid, name, lat, lon, tz, anchor, mi: {                                     # noqa: E731
        "id": cid, "name": name, "county": "Test County", "population": 1000, "zip": "78701", "kind": "city",
        "lat": lat, "lon": lon, "tz": tz, "anchor": anchor, "anchor_mi": mi}
    files = {
        "meta.json": {"built": "2026-10-06T19:00:00+00:00", "radii_mi": [10, 25, 50], "anchors": {
                          "alpha": {"name": "Alpha", "zip": "78701"}, "gamma": {"name": "Gamma", "zip": "79901"}},
                      "industries": [{"id": "grocery", "name": "Grocery", "description": "", "online": True},
                                     {"id": "tech", "name": "Tech", "description": "", "online": True},
                                     {"id": "dining", "name": "Dining", "description": "", "online": False}],
                      "cities": [city("alpha", "Alpha", 30.0, -97.0, "America/Chicago", "alpha", 0.0),
                                 city("beta", "Beta", 30.1, -97.0, "America/Chicago", "alpha", 6.9),
                                 city("gamma", "Gamma", 31.8, -106.4, "America/Denver", "gamma", 0.0)]},
        "ads/index.json": {
            "anchors": {"alpha": {"ads": [1, 2], "out": 1}, "gamma": {"ads": [3], "out": 0}},
            "flyers": {"1": {"merchant": "Mart", "flipp": "Mart", "vf": "2026-10-01T00:00:00-05:00",
                             "vt": "2026-10-07T23:59:59-05:00"},
                       "2": {"merchant": "Mart", "flipp": "Mart", "vf": "2026-10-05T00:00:00-05:00",
                             "vt": "2026-10-11T23:59:59-05:00"},
                       "3": {"merchant": "Mart", "flipp": "Mart", "vf": "2026-10-01T00:00:00-05:00",
                             "vt": "2026-10-10T23:59:59-05:00", "vtm": "2026-10-10T23:59:59-06:00"}},
            "merchants": {"Mart": {"uncertain": False}}},
        "ads/1.json": {"id": 1, "merchant": "Mart", "excluded": {"no saving amount": 2}, "deals": [
            {"id": 11, "title": "Apples", "industries": ["grocery"], "terms": {"price": 1.0, "pct": 50.0,
             "basis": "store_regular"}, "vf": "2026-10-01T00:00:00-05:00", "vt": "2026-10-07T23:59:59-05:00",
             "score": 45.0, "dk": "Mart|apples|1.0|50.0"},
            {"id": 12, "title": "Laptop", "industries": ["tech"], "terms": {"price": 300.0, "pct": 25.0,
             "basis": "store_regular"}, "vf": "2026-10-01T00:00:00-05:00", "vt": "2026-10-07T23:59:59-05:00",
             "score": 22.5, "dk": "Mart|laptop|300.0|25.0"},
            {"id": 13, "title": "Old cheese", "industries": ["grocery"], "terms": {"price": 2.0, "pct": 20.0},
             "vf": "2026-09-28T00:00:00-05:00", "vt": "2026-10-05T23:59:59-05:00", "score": 1.0, "dk": "x"}]},
        "ads/2.json": {"id": 2, "merchant": "Mart", "excluded": {}, "deals": [
            {"id": 21, "title": "Apples", "industries": ["grocery"], "terms": {"price": 1.0, "pct": 50.0,
             "basis": "store_regular"}, "vf": "2026-10-05T00:00:00-05:00", "vt": "2026-10-11T23:59:59-05:00",
             "score": 45.0, "dk": "Mart|apples|1.0|50.0"}]},
        "ads/3.json": {"id": 3, "merchant": "Mart", "excluded": {}, "deals": [
            {"id": 31, "title": "Chiles", "industries": ["grocery"], "terms": {"price": 1.0, "pct": 10.0},
             "vf": "2026-10-01T00:00:00-05:00", "vt": "2026-10-06T23:59:59-05:00",
             "vtm": "2026-10-06T23:59:59-06:00", "gone": "2026-10-06T23:59:59-04:00", "score": 5.0, "dk": "y"},
            {"id": 32, "title": "Tortillas", "industries": ["grocery"], "terms": {"price": 2.0, "pct": 20.0},
             "vf": "2026-10-01T00:00:00-05:00", "vt": "2026-10-06T23:59:59-05:00",
             "vtm": "2026-10-06T23:59:59-06:00", "score": 6.0, "dk": "z"}]},
        "stores.json": {"built": "2026-10-01", "merchants": {"Mart": [
            [30.0, -97.2, "Mart West", "1 West St", "osm:node/1"], [30.12, -97.0, "Mart North", "2 North St", "osm:node/2"],
            [31.79, -106.4, "Mart El Paso", "3 Sun St", "osm:node/3"]]}},
        "regulars.json": {"excluded": {"regular deal: no evidence recent enough to rely on": 1}, "sources": [],
                          "chains": {"v:cine": {"name": "Cine", "rows": [[30.01, -97.0, "Cine Alpha", "9 Film Rd",
                                                                          "osm:way/9"]]}},
                          "regulars": [{"id": "cine-tue", "brand": "Cine", "offer": "Discount Tuesdays: $5 movies",
                                        "industries": ["dining"], "kind": "cinema", "origin": "registry",
                                        "terms": {"price": 5.0, "conditions": ["rewards members"]},
                                        "link": "https://cine.example/deals", "image_url": "", "note": "",
                                        "source_url": "https://cine.example/deals", "score": 0.0,
                                        "status": "confirmed", "status_text": "Confirmed on cine.example",
                                        "evidence": [], "off": [], "logo": None, "chain": "v:cine", "area": None,
                                        "schedule": {"days": [1], "monthly": "", "until": None, "since": None,
                                                     "windows": {"America/Chicago": [["16:00:00", "18:00:00"]],
                                                                 "America/Denver": [["16:00:00", "18:00:00"]]}},
                                        "days_text": "Every Tuesday",
                                        "time_text": {"America/Chicago": "4–6 pm", "America/Denver": "4–6 pm"}}]},
        "promos.json": {"excluded": {}, "sources": [], "chains": {}, "items": []},
        "online/grocery.json": {"generated_at": "2026-10-06T19:00:00+00:00", "excluded": {"other industry": 3},
                                "sources": [{"name": "dealnews", "ok": True}],
                                "deals": {"grocery": [{"id": "dn:1"}, {"id": "dn:2"}]}},
        "online/tech.json": {"generated_at": "2026-10-06T18:00:00+00:00", "excluded": {"other industry": 5},
                             "sources": [{"name": "dealnews", "ok": True}, {"name": "slickdeals", "ok": False}],
                             "deals": {"tech": [{"id": "dn:3"}]}},
    }
    for rel, content in files.items():
        (data / rel).write_text(json.dumps(content))
    return tmp


def _search(tmp: Path, cases: list[dict]) -> list[dict]:
    site = _site(tmp)
    (tmp / "cases.json").write_text(json.dumps(cases))
    out = subprocess.run(["node", "-e", DRIVER, str(site), str(tmp / "cases.json")], capture_output=True, text=True,
                         check=True)
    return json.loads(out.stdout)


needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="Node isn't installed")


@needs_node
def test_engine_answers_like_the_server_on_a_small_site(tmp_path):
    alpha, beta, wide, gamma = _search(tmp_path, [
        {"city": "alpha", "industries": "grocery,tech,dining", "radius_mi": 10, "limit": 1, "now": NOW},
        {"city": "beta", "industries": "grocery", "radius_mi": 10, "now": NOW},
        {"city": "alpha", "industries": "grocery", "radius_mi": 25, "now": NOW},
        {"city": "gamma", "industries": "grocery", "radius_mi": 10, "now": "2026-10-07T00:30:00-05:00"}])
    L = alpha["local"]
    assert L["window"] == {"start": "2026-10-06T15:00:00-05:00", "end": "2026-10-13T15:00:00-05:00"}
    # The same apples in two ads: the copy that runs longer is kept. Old cheese ended yesterday.
    assert [d["id"] for d in L["deals"]] == ["flipp:21", "flipp:12"]
    apples = L["deals"][0]
    assert apples["store"]["name"] == "Mart North" and apples["store"]["distance_mi"] == 8.3
    assert apples["valid_to"] == "2026-10-11T23:59:59-05:00" and apples["ends_in_days"] == 5
    assert apples["terms"]["qty"] == 1 and apples["terms"]["conditions"] == [] and apples["kind"] == "deal"
    ex = L["excluded"]
    assert ex["same item in another ad"] == 1 and ex["item already ended"] == 1 and ex["no saving amount"] == 2
    assert ex["ad outside the 7-day window"] == 1
    # Regular deals: Tuesdays 4-6 pm. Today's (it's 3 pm) counts; next Tuesday's starts after the window ends.
    reg = L["regulars"][0]
    assert reg["regular"]["next"] == ["2026-10-06"] and reg["valid_from"] == "2026-10-06T16:00:00-05:00"
    assert reg["regular"]["ends"] == "18:00" and reg["store"]["name"] == "Cine Alpha"
    # Online: each industry's list, cut to the limit; shared feeds counted once.
    O = alpha["online"]
    assert O["industries"] == ["grocery", "tech"] and O["counts"] == {"grocery": 1, "tech": 1}
    assert O["generated_at"] == "2026-10-06T18:00:00+00:00" and O["excluded"] == {"other industry": 5}
    assert [s["name"] for s in O["sources"]] == ["dealnews", "slickdeals"]
    # A city that isn't an anchor says whose ads it shows; the radius is measured from the city itself.
    assert beta["local"]["ads_from"] == {"id": "alpha", "name": "Alpha", "mi": 6.9}
    assert [d["store"]["distance_mi"] for d in beta["local"]["deals"]] == [1.4]
    assert [d["id"] for d in wide["local"]["deals"]] == ["flipp:21"] and wide["local"]["beyond_radius"] == []
    # Mountain time, 11:30 PM: an item that ends at the end of the day locally is still on (it ended an hour ago in
    # Central time); one Flipp pulls at 11:59 PM Eastern is gone.
    G = gamma["local"]
    assert G["window"]["start"] == "2026-10-06T23:30:00-06:00"
    assert [d["id"] for d in G["deals"]] == ["flipp:32"] and G["excluded"]["item already ended"] == 1
    assert G["deals"][0]["valid_to"] == "2026-10-06T23:59:59-06:00" and G["deals"][0]["store"]["distance_mi"] == 0.7


@needs_node
def test_engine_regular_deal_whose_hours_are_over_shows_next_week(tmp_path):
    late, = _search(tmp_path, [{"city": "alpha", "industries": "dining", "radius_mi": 10,
                                "now": "2026-10-06T18:30:00-05:00"}])
    reg = late["local"]["regulars"][0]
    assert reg["regular"]["next"] == ["2026-10-13"] and reg["starts_in_days"] == 7
    assert late["online"] is None and late["local"]["deals"] == []
