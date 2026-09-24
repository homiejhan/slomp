import json

import httpx
import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from fakeweb import NOW, FakeWeb, austin_routes
from plum import cli
from plum.api import create_app
from plum.demo_data import build_service
from plum.local import LocalDealService
from plum.net import HttpClient


def fake_service(routes=None) -> LocalDealService:
    web = FakeWeb(routes or austin_routes())
    return LocalDealService(HttpClient(transport=httpx.MockTransport(web), backoff_s=0), clock=lambda: NOW)


def test_local_endpoints():
    client = TestClient(create_app(build_service(), local=fake_service()))
    j = client.get("/local/deals", params={"where": "Austin, TX", "limit": 2}).json()
    assert j["place"]["postal_code"] == "78701" and len(j["deals"]) == 2
    assert j["deals"][0]["price_label"] == "$8.49" and j["deals"][0]["terms"]["was"] == 26.99
    j = client.get("/local/search", params={"q": "chicken breast", "where": "78701"}).json()
    assert [r["merchant"] for r in j["results"]] == ["Randalls", "H-E-B"]
    assert client.get("/local/deals", params={"where": "Austin", "radius_mi": 500}).status_code == 422
    assert client.get("/health").json()["ok"] is True


def test_local_endpoint_unknown_place():
    routes = austin_routes()
    routes["nominatim.openstreetmap.org/search"] = []
    client = TestClient(create_app(build_service(), local=fake_service(routes)))
    assert client.get("/local/deals", params={"where": "Nowhere"}).status_code == 404


def test_cli_deals_and_search(monkeypatch, capsys):
    monkeypatch.setattr(LocalDealService, "live", classmethod(lambda cls, **kw: fake_service()))
    assert cli.main(["deals", "Austin, TX", "--limit", "3"]) == 0
    out = capsys.readouterr().out
    assert "BEST DEALS" in out and "Barbie - Movie Ken Collector Doll" in out
    assert cli.main(["search", "chicken breast", "--near", "78701", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["results"][0]["terms"]["unit"] == "lb"


def test_cli_reports_failed_sources_and_unknown_places(monkeypatch, capsys):
    routes = austin_routes()
    routes["overpass-api.de/api/interpreter"] = httpx.Response(504)
    monkeypatch.setattr(LocalDealService, "live", classmethod(lambda cls, **kw: fake_service(routes)))
    assert cli.main(["deals", "Austin, TX"]) == 1                       # deals still printed, exit code flags the gap
    assert "FAILED" in capsys.readouterr().out
    routes["nominatim.openstreetmap.org/search"] = []
    assert cli.main(["deals", "Nowhere"]) == 2
    assert "couldn't find" in capsys.readouterr().err


def test_cli_demo(capsys):
    assert cli.main(["demo", "sony", "xm5"]) == 0
    out = capsys.readouterr().out
    assert "SIMULATED" in out and "BEST Best Buy" in out and "after probe" in out
