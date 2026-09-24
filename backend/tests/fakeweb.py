"""An offline stand-in for Nominatim, Flipp and Overpass, shaped like their real responses (Austin, Sept 2026)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Union
from urllib.parse import parse_qs

import httpx

NOW = datetime(2026, 9, 24, 17, 0, tzinfo=timezone.utc)
WEEK = ("2026-09-22T00:00:00-04:00", "2026-09-28T23:59:59-04:00")
NEXT_WEEK = ("2026-09-27T00:00:00-04:00", "2026-10-03T23:59:59-04:00")
LAT, LON = 30.2711286, -97.7436995

Route = Union[dict, list, httpx.Response, Callable[[httpx.Request], Any]]


class FakeWeb:
    """Routes by host + path; records every request."""

    def __init__(self, routes: dict[str, Route]):
        self.routes = routes
        self.calls: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        route = self.routes.get(request.url.host + request.url.path)
        if route is None:
            return httpx.Response(404, json={"error": "no route"})
        body = route(request) if callable(route) else route
        return body if isinstance(body, httpx.Response) else httpx.Response(200, json=body)

    def hits(self, fragment: str) -> int:
        return sum(fragment in str(r.url) for r in self.calls)


def flyer(fid: int, merchant: str, span=WEEK, cats=("General Merchandise",)) -> dict:
    return {"id": fid, "merchant": merchant, "merchant_id": fid * 10, "valid_from": span[0], "valid_to": span[1],
            "categories": ["All Flyers", *cats], "postal_code": "78701"}


def listing(iid: int, name: str, price: str = "", discount=None, display_type: int = 1, span=WEEK) -> dict:
    return {"id": iid, "flyer_id": iid // 100, "name": name, "price": price, "discount": discount,
            "display_type": display_type, "valid_from": span[0], "valid_to": span[1], "ttm_url": ""}


def detail(iid: int, merchant: str, name: str, *, price="", original=None, pre=None, post=None, story=None,
           pct=None, dollars=None, link="", disclaimer=None, span=WEEK) -> dict:
    return {"item": {"id": iid, "flyer_id": iid // 100, "merchant": merchant, "name": name, "display_type": 1,
                     "current_price": price, "original_price": original, "pre_price_text": pre, "price_text": post,
                     "sale_story": story, "percent_off": pct, "dollars_off": dollars, "ttm_url": link,
                     "disclaimer_text": disclaimer, "in_store_only": False, "valid_from": span[0], "valid_to": span[1],
                     "cutout_image_url": f"http://f.wishabi.net/page_items/{iid}/extra_large.jpg"}}


def osm_node(nid: int, name: str, lat: float, lon: float, **tags: str) -> dict:
    return {"type": "node", "id": nid, "lat": lat, "lon": lon, "tags": {"name": name, **tags}}


def overpass(near: list[dict], wide: list[dict]) -> Callable[[httpx.Request], Any]:
    """Near queries also match names; the wide second look is brand-only (see adapters/osm.py)."""
    def answer(request: httpx.Request) -> Any:
        q = parse_qs(request.content.decode())["data"][0]
        return {"elements": near if '["name"~' in q else wide}
    return answer


def austin_routes() -> dict[str, Route]:
    api = "backflipp.wishabi.com/flipp"
    bb, cvs, belk = 81, 82, 83
    return {
        "nominatim.openstreetmap.org/search": [
            {"lat": str(LAT), "lon": str(LON), "addresstype": "city", "display_name": "Austin, Travis County, Texas",
             "address": {"city": "Austin", "state": "Texas", "country_code": "us"}}],
        "nominatim.openstreetmap.org/reverse": {"address": {"postcode": "78701", "city": "Austin"}},
        f"{api}/flyers": {"flyers": [flyer(bb, "Best Buy", cats=("Electronics",)), flyer(cvs, "CVS Pharmacy", cats=("Pharmacy",)),
                                     flyer(belk, "Belk"), flyer(84, "Walgreens", span=NEXT_WEEK)]},
        f"{api}/flyers/{bb}": {"items": [
            listing(8101, "Sony - ULT WEAR Wireless Noise Cancelling Headphones - Black", "148.0", 40),
            listing(8102, "Barbie - Movie Ken Collector Doll", "8.49", 68),
            listing(8103, "Apple - EarPods (USB-C) - White", "19.99"),                  # a price, no saving
            listing(8104, "BESBU093025990119", display_type=5),                          # page furniture
            listing(8105, "Sony - ULT WEAR Wireless Noise Cancelling Headphones - Black", "148.0", 40),   # repeat
            listing(8106, "Insignia - 3.1 Cu. Ft. Mini Fridge", "179.99", 18)]},
        f"{api}/flyers/{cvs}": {"items": [
            listing(8201, "So De La Renta by OSCAR DE LA RENTA EDT spray 3.4 oz.", "24.99", 75),
            listing(8202, "ALL Osteo Bi-Flex", "", 50),
            listing(8203, "Brach's candy corn, autumn mix or pumpkins", "8.0")]},
        f"{api}/flyers/{belk}": {"items": [listing(8301, "Regular Fit Stretch Button Down Shirt", "29.99", 50)]},
        f"{api}/items/8101": detail(8101, "Best Buy", "Sony - ULT WEAR Wireless Noise Cancelling Headphones - Black",
                                    price="148.0", story="Headphones", pct=40.0, dollars=100.0,
                                    link="https://www.bestbuy.com/product/sony-ult-wear/J7XSRH5P56/sku/6576179"),
        f"{api}/items/8102": detail(8102, "Best Buy", "Barbie - Movie Ken Collector Doll", price="8.49", pct=68.0,
                                    dollars=18.5, link="https://www.bestbuy.com/product/barbie-movie-ken/JJ85Q58W86"),
        f"{api}/items/8106": detail(8106, "Best Buy", "Insignia - 3.1 Cu. Ft. Mini Fridge", price="179.99", pct=18.0,
                                    dollars=40.0, link="https://www.bestbuy.com/product/insignia-fridge/J1"),
        f"{api}/items/8201": detail(8201, "CVS Pharmacy", "So De La Renta by OSCAR DE LA RENTA EDT spray 3.4 oz.",
                                    price="24.99", post="WITH CARD", story="You save 76.00", pct=75.0, dollars=76.01),
        f"{api}/items/8202": detail(8202, "CVS Pharmacy", "ALL Osteo Bi-Flex", story="Buy 1 get 1 50% OFF* WITH CARD",
                                    pct=50.0),
        f"{api}/items/8301": detail(8301, "Belk", "Regular Fit Stretch Button Down Shirt", price="29.99", pct=50.0,
                                    dollars=30.0, link="https://www.belk.com/p/shirt"),
        f"{api}/items/search": {"items": [
            {"id": 9001, "flyer_id": 90, "merchant_name": "Randalls", "name": "Boneless, Skinless Chicken Breasts or Thighs",
             "current_price": 1.79, "post_price_text": "lb", "valid_from": "2026-09-23T04:00:00+00:00",
             "valid_to": "2026-09-30T03:59:59+00:00", "clean_image_url": "https://f.wishabi.net/9001.jpg"},
            {"id": 9002, "flyer_id": 91, "merchant_name": "H-E-B", "name": "H-E-B Natural Boneless Skinless Chicken Breasts",
             "current_price": 3.99, "post_price_text": "lb.", "valid_from": "2026-09-23T04:00:00+00:00",
             "valid_to": "2026-09-30T03:59:59+00:00"},
            {"id": 9003, "flyer_id": 91, "merchant_name": "H-E-B", "name": "Silicone Chicken Breast Holder",
             "current_price": 6.99, "valid_from": "2026-09-23T04:00:00+00:00", "valid_to": "2026-09-30T03:59:59+00:00"},
            {"id": 9004, "flyer_id": 92, "merchant_name": "Restaurant Depot", "name": None, "current_price": None,
             "valid_from": "2026-09-01T04:00:00+00:00", "valid_to": "2026-10-01T03:59:59+00:00"}]},
        f"{api}/items/9001": detail(9001, "Randalls", "Boneless, Skinless Chicken Breasts or Thighs", price="1.79", post="lb",
                                    disclaimer="Limit 10 lbs. Each"),
        f"{api}/items/9002": detail(9002, "H-E-B", "H-E-B Natural Boneless Skinless Chicken Breasts", price="3.99",
                                    post="lb."),
        "overpass-api.de/api/interpreter": overpass(
            near=[osm_node(1, "Best Buy", 30.30, -97.70, brand="Best Buy", shop="electronics",
                           **{"addr:housenumber": "1201", "addr:street": "Barbara Jordan Boulevard", "addr:city": "Austin"}),
                  osm_node(2, "CVS Pharmacy", 30.2715, -97.7440, brand="CVS Pharmacy", amenity="pharmacy"),
                  osm_node(3, "Belk Beauty", 30.11, -97.32, shop="beauty"),                   # a salon, not Belk
                  osm_node(4, "Randalls", 30.29, -97.77, brand="Randalls", shop="supermarket"),
                  osm_node(5, "H-E-B Pharmacy", 30.2600, -97.7100, brand="H-E-B", amenity="pharmacy"),
                  osm_node(6, "H-E-B", 30.2601, -97.7102, brand="H-E-B", shop="supermarket")],
            wide=[osm_node(7, "Belk", 29.45, -98.60, brand="Belk", shop="department_store")]),
    }
