from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from plum import industries as ind
from plum.geo import ad_end_local, ad_start_local
from plum.promos import promo_dates, recurring_days
from plum.reference import cities, city, find_cities
from plum.service import InputError, resolve_city, resolve_industries


def test_taxonomy_mapping():
    assert ind.from_taxonomy("Electronics", "Audio").industries == ["tech"]
    assert ind.from_taxonomy("Health & Beauty", "Personal Care").industries == ["beauty"]
    assert ind.from_taxonomy("Home & Garden", "Household Supplies").industries == ["grocery"]
    assert ind.from_taxonomy("Mature", "Weapons").industries == ["sports"]


def test_sporting_goods_apparel_is_also_sports():
    c = ind.classify_ad_item("Apparel & Accessories", "Clothing", "Nike Men's Club Fleece Hoodie", "Nike", ["sports"])
    assert c.industries == ["fashion", "sports"]


def test_keyword_rules():
    assert "tech" in ind.from_text("Samsung - 48\" Class OLED 4K TV").industries
    assert ind.from_text("Advil 200mg Tablets").industries[0] == "health"
    assert "tech" in ind.from_text("Lenovo Idea Tab Pro 12.7\" Tablet").industries
    assert ind.from_text("Juniors' Denim").industries == ["fashion"]
    assert ind.from_text("Men's Flannels").industries == ["fashion"]          # apparel cue
    assert "grocery" in ind.from_text("Kellogg's Cereals").industries          # plurals


def test_dealnews_leaf_categories():
    assert ind.from_dealnews("Portable Speakers").industries == ["tech"] or ind.from_dealnews("TVs").industries == ["tech"]
    assert ind.from_dealnews("Pry Bars").industries == ["home"]


def test_ad_dates_in_the_city_zone():
    # Flipp states an ad ending 11:59 PM as "-04:00" (Eastern) or as UTC the next morning; both mean that day locally
    end = ad_end_local(datetime.fromisoformat("2026-10-05T23:59:59-04:00"), "America/Chicago")
    assert end == datetime(2026, 10, 5, 23, 59, 59, tzinfo=ZoneInfo("America/Chicago"))
    end_utc = ad_end_local(datetime(2026, 10, 7, 3, 59, 59, tzinfo=timezone.utc), "America/Denver")
    assert end_utc.date() == date(2026, 10, 6) and end_utc.hour == 23
    start_utc = ad_start_local(datetime(2026, 9, 30, 4, 0, tzinfo=timezone.utc), "America/Chicago")
    assert start_utc == datetime(2026, 9, 30, tzinfo=ZoneInfo("America/Chicago"))


def test_promo_dates():
    p = date(2026, 10, 4)
    assert promo_dates("Moe's $2 tacos Oct 6-11", p)[:2] == (date(2026, 10, 6), date(2026, 10, 11))
    assert promo_dates("Free entrée at Chuy's - October 6", p)[:2] == (date(2026, 10, 6), date(2026, 10, 6))
    assert promo_dates("Buy three by Oct 21, get 4th free", p)[1] == date(2026, 10, 21)
    assert promo_dates("Arby's B1G1 (Valid Thru 10/4)", p)[1] == date(2026, 10, 4)
    assert recurring_days("KFC 8pc bucket for $10 on Tuesdays") == [1]


def test_city_list():
    cs = cities()
    assert len(cs) > 1200 and len({c.id for c in cs}) == len(cs)
    assert city("austin").zip.startswith("787") and city("el-paso").tz == "America/Denver"
    assert find_cities("san an")[0].id == "san-antonio"
    assert {c.id for c in cs if c.name == "Reno"} == {"reno-lamar-county", "reno-parker-county"}


def test_inputs_must_come_from_the_fixed_lists():
    with pytest.raises(InputError):
        resolve_city("atlantis")
    with pytest.raises(InputError):
        resolve_industries("tech,crypto")
    assert resolve_industries("tech,sports,tech") == ["tech", "sports"]
