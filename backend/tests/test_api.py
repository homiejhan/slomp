import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from plum.api import create_app
from plum.demo_data import build_service


@pytest.fixture
def client():
    return TestClient(create_app(build_service(budget_s=1.0)))


def test_home_page(client):
    r = client.get("/")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    assert "<title>Plum" in r.text and "/local/deals?" in r.text and "/local/search?" in r.text


def test_health_and_retailers(client):
    assert client.get("/health").json()["ok"] is True
    assert "bestbuy" in client.get("/retailers").json()


def test_search_text_and_product_id(client):
    j = client.get("/search", params={"q": "sony xm5"}).json()
    assert j["product"]["id"] == "sony-xm5" and j["how"] == "text" and j["product"]["glyph"]
    assert {a["retailer"] for a in j["adapters"]} == {"amazon", "walmart", "bestbuy", "target", "ebay", "bh", "dyson", "nike", "lego", "zappos"}
    assert all(a["status"] == "done" for a in j["adapters"])
    counts = {a["retailer"]: a["count"] for a in j["adapters"]}
    assert counts["amazon"] == 1 and counts["ebay"] == 2 and counts["nike"] == 0
    best = j["offers"][0]
    assert best["listing"]["retailer"] == "bestbuy" and best["code"] == "SAVE15" and best["pay_today"] == 280.49 and best["net"] == 274.88
    assert best["ship_cost"] == 0 and best["match"]["tier"] == "exact"
    assert any(c["code"] == "FREESHIP" and c["type"] == "freeship" for c in best["codes"])
    assert {s["why"] for s in j["skipped"]} >= {"refurbished (hidden)"}
    assert all("id" in s and "condition" in s for s in j["skipped"])
    j2 = client.get("/search", params={"product_id": "sony-xm5", "include_used": "true"}).json()
    assert j2["how"] == "id" and any(o["listing"]["condition"] == "refurbished" for o in j2["offers"])


def test_search_miss(client):
    assert client.get("/search", params={"q": "toaster"}).status_code == 404
    assert client.get("/search", params={"product_id": "nope"}).status_code == 404


def test_probe_marks_verified(client):
    j = client.get("/search", params={"q": "sony xm5"}).json()
    lid = j["offers"][0]["listing"]["id"]
    r = client.post(f"/probe/{lid}", params={"product_id": "sony-xm5"}).json()
    assert r["listing_id"] == lid and r["winner"] == "SAVE15" and r["discount"] == 49.5
    assert {s["code"] for s in r["steps"]} >= {"SAVE15", "LABORDAY10"}
    j2 = client.get("/search", params={"q": "sony xm5"}).json()
    top = j2["offers"][0]
    assert top["listing"]["id"] == lid and top["verified"] is True and top["code"] == "SAVE15"
    assert client.post("/probe/nope", params={"product_id": "sony-xm5"}).status_code == 404


def test_coupons_and_deals(client):
    cs = client.get("/coupons/bestbuy").json()
    assert {c["code"] for c in cs} == {"SAVE15", "LABORDAY10", "FREESHIP", "BB20OFF"}
    assert all(0 <= c["reliability"] <= 1 for c in cs)
    d = client.get("/deals").json()
    assert len(d["events"]) == 8 and len(d["deals"]) == 10
    assert d["deals"][0]["product_id"] == "kindle-pw" and d["deals"][0]["product_title"].startswith("Kindle")
    heats = [x["heat"] for x in d["deals"]]
    assert heats == sorted(heats, reverse=True)
    assert all(x["glyph"] for x in d["deals"])
