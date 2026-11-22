"""The days stores name sales after (slomp/days.py)."""
from datetime import date

from slomp import days


def test_the_days_fall_where_the_calendar_puts_them():
    assert days.thanksgiving(2026) == date(2026, 11, 26) and days.thanksgiving(2025) == date(2025, 11, 27)
    assert days.day_of("Belk Black Friday Sale", date(2026, 11, 14)) == ("Black Friday", date(2026, 11, 27))
    assert days.day_of("Cyber Monday Deals", date(2026, 11, 20)) == ("Cyber Monday", date(2026, 11, 30))
    assert days.day_of("Memorial Day Sale", date(2026, 5, 18)) == ("Memorial Day", date(2026, 5, 25))
    assert days.day_of("Labor Day Sale", date(2026, 9, 1)) == ("Labor Day", date(2026, 9, 7))
    assert days.day_of("Easter Sale", date(2026, 3, 30)) == ("Easter", date(2026, 4, 5))
    assert days.day_of("Lowe's Halloween Clearance", date(2026, 10, 12)) == ("Halloween", date(2026, 10, 31))
    # a holiday's name on the goods bought for it names no day's sale
    for goods in ("Christmas Decor Sale", "Halloween Costumes Deals", "Thanksgiving Dinner Kit", "Easter Basket Sale"):
        assert days.day_of(goods, date(2026, 3, 30)) is None and not days.named(goods), goods
    assert days.day_of("Presidents' Day Sale", date(2027, 2, 10)) == ("Presidents' Day", date(2027, 2, 15))


def test_a_post_names_the_day_ahead_of_it_and_the_last_of_several():
    assert days.day_of("Black Friday & Cyber Monday Deals", date(2026, 11, 20)) == ("Cyber Monday", date(2026, 11, 30))
    assert days.day_of("Black Friday Sale", date(2026, 11, 28)) is None            # posted after the day
    assert days.day_of("New Year's Sale", date(2026, 12, 28)) == ("New Year's", date(2027, 1, 1))
    assert days.day_of("Fall Sale", date(2026, 10, 1)) is None
    assert days.named("Black Friday Ad Preview") == ["Black Friday"] and not days.named("Friday Flash Sale")


def test_a_wave_before_a_day_is_told_from_the_day():
    for name in ("Early Black Friday Sale", "Pre-Black Friday Deals", "Black Friday Preview", "Countdown to Black Friday",
                 "Black Friday Warm-Up Sale", "Black Friday Sneak Peek"):
        assert days.BEFORE.search(name), name
    for name in ("Black Friday Sale", "Black Friday Prepaid Phone Deals", "Cyber Monday Deals"):
        assert not days.BEFORE.search(name), name
