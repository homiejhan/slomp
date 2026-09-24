import time

import httpx
import pytest

from plum.adapters.osm import bbox, is_merchant, main_store, names_for, overpass_query
from plum.geo import haversine_km
from plum.models import Store
from plum.net import MISS, DiskCache, HttpClient, HttpError


@pytest.mark.parametrize("value,merchant,expected", [
    ("Walmart Neighborhood Market", "Walmart", True),
    ("H-E-B plus!", "H-E-B", True),
    ("HEB", "H-E-B", True),
    ("Kohl’s", "Kohl's", True),
    ("Lowe's Home Improvement", "Lowe's", True),
    ("The Home Depot", "Home Depot", True),
    ("Michaels", "Michaels USA", True),
    ("Randalls 2485", "Randalls", True),
    ("Harbor Freight Tools Austin", "Harbor Freight Tools", True),       # the place name may follow
    ("Target - Mueller", "Target", True),
    ("Belk Beauty", "Belk", False),                                     # an eyelash salon in Bastrop
    ("La Michoacana Paleteria y Neveria", "La Michoacana Meat Market", False),   # a different business
    ("Targeted Fitness", "Target", False),
    ("Best Buy Mobile", "Best Buy", False),
])
def test_store_names_match_strictly(value, merchant, expected):
    assert is_merchant(value, names_for(merchant), frozenset({"austin", "texas"})) is expected


def test_a_brand_tag_names_the_chain_even_with_a_longer_name():
    assert is_merchant("Coastal Farm & Ranch", ["Coastal Farm"], brand=True)          # Portland: brand outruns name
    assert not is_merchant("Coastal Farm & Ranch", ["Coastal Farm"])
    assert not is_merchant("Belkin", ["Belk"], brand=True)                            # whole words only


def test_overpass_query_tolerates_punctuation_and_uses_a_box():
    q = overpass_query(["Kohl's", "Bath & Body Works"], bbox(30.27, -97.74, 40.2))
    assert "kohl[^a-zA-Z0-9]*s" in q and "bath[^a-zA-Z0-9]*(and|&)[^a-zA-Z0-9]*body" in q
    assert "around" not in q and '["name"~' in q
    assert '["name"~' not in overpass_query(["Belk"], bbox(30.27, -97.74, 160), names=False)
    s, w, n, e = bbox(30.27, -97.74, 40.2)
    assert haversine_km(30.27, -97.74, n, -97.74) == pytest.approx(40.2, rel=0.01)
    assert haversine_km(30.27, -97.74, 30.27, e) == pytest.approx(40.2, rel=0.01)


def test_main_store_prefers_the_building_over_a_department_pin():
    pharmacy = Store("H-E-B", "H-E-B Pharmacy", 30.2600, -97.7100, "", 3.40)
    store = Store("H-E-B", "H-E-B", 30.2601, -97.7102, "2701 East 7th Street", 3.41)
    elsewhere = Store("H-E-B", "H-E-B", 30.40, -97.80, "", 15.0)
    assert main_store([pharmacy, store, elsewhere]) is store
    assert main_store([pharmacy, elsewhere]) is pharmacy          # nothing else at that spot


def _client(handler, **kw):
    return HttpClient(transport=httpx.MockTransport(handler), backoff_s=0, **kw)


async def test_retries_transient_failures_and_html_error_pages():
    answers = [httpx.Response(503), httpx.Response(200, text="<html>too busy</html>"), httpx.Response(200, json={"ok": 1})]
    seen = []

    def handler(request):
        seen.append(request)
        return answers[len(seen) - 1]

    async with _client(handler) as http:
        assert await http.get_json("https://example.org/x") == {"ok": 1}
    assert len(seen) == 3


async def test_client_errors_are_not_retried_and_retries_run_out():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(404 if "missing" in str(request.url) else 502)

    async with _client(handler) as http:
        with pytest.raises(HttpError, match="404"):
            await http.get_json("https://example.org/missing")
        with pytest.raises(HttpError, match="502"):
            await http.get_json("https://example.org/down")
    assert len(seen) == 1 + 3


async def test_disk_cache_serves_repeat_requests(tmp_path):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"n": len(seen)})

    async with _client(handler, cache=DiskCache(tmp_path)) as http:
        first = await http.get_json("https://example.org/a", {"q": 1}, ttl_s=60)
        again = await http.get_json("https://example.org/a", {"q": 1}, ttl_s=60)
        other = await http.get_json("https://example.org/a", {"q": 2}, ttl_s=60)
        uncached = await http.get_json("https://example.org/a", {"q": 1})
    assert (first, again, other, uncached) == ({"n": 1}, {"n": 1}, {"n": 2}, {"n": 3})
    cache = DiskCache(tmp_path)
    cache.set("k", {"v": 1}, ttl_s=-1)
    assert cache.get("k") is MISS                                          # expired entries read as missing


async def test_requests_to_one_host_are_spaced_out():
    async with _client(lambda r: httpx.Response(200, json={}), min_interval_s={"example.org": 0.05}) as http:
        t0 = time.monotonic()
        for _ in range(3):
            await http.get_json("https://example.org/x")
        assert time.monotonic() - t0 >= 0.1
