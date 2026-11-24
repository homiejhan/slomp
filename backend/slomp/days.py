"""The days stores name sales after, and when each falls.

"Belk Black Friday Sale" says when it is: Black Friday is the day after the fourth Thursday of November. A sale named
for a day is the store's sale for that day, so the name tells Slomp two things a post often leaves out: that this is
the store's own event (sales.py shows a store's event named for a day even when its post states no discount), and
how long it lasts at least (through the day, when the post states no end). The calendar is the United States' own;
nothing in it is about one store.
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Callable, Optional


def _nth(year: int, month: int, weekday: int, n: int) -> date:
    """The n-th `weekday` (Monday is 0) of a month."""
    first = date(year, month, 1)
    return first + timedelta(days=(weekday - first.weekday()) % 7 + 7 * (n - 1))


def _last(year: int, month: int, weekday: int) -> date:
    d = date(year, month + 1, 1) - timedelta(days=1)
    return d - timedelta(days=(d.weekday() - weekday) % 7)


def _easter(year: int) -> date:
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    g = (8 * b + 13) // 25
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    m = (a + 11 * h) // 319
    r = (2 * e + 2 * i - h - k + m + 32) % 7
    month = (h - m + r + 90) // 25
    return date(year, month, (h - m + r + month + 19) % 32)


def thanksgiving(year: int) -> date:
    return _nth(year, 11, 3, 4)


# A holiday's name is also on what people buy for it ("Christmas Decor", "Halloween Costumes", "Thanksgiving Dinner
# Kit"), so it names a sale only as the sale's own name: "Christmas Sale", "Halloween Clearance", "Easter Weekend
# Deals". A shopping day's name (Black Friday) is on nothing else.
_AS_A_SALE = r"(?:\s+(?:day|eve|weekend|week))?\s+(?:sales?|deals|events?|savings|specials|doorbusters?|clearance)\b"
_HOLIDAYS = {"New Year's", "Valentine's Day", "Easter", "Mother's Day", "Father's Day", "Halloween", "Thanksgiving",
             "Christmas"}
# (the day's name, how posts write it, when it falls). A week named for a day ends with its last day.
DAYS: tuple[tuple[str, re.Pattern, Callable[[int], date]], ...] = tuple(
    (name, re.compile(f"(?:{rx}){_AS_A_SALE}" if name in _HOLIDAYS else rx, re.I), when) for name, rx, when in (
        ("New Year's", r"\bnew year'?s?\b", lambda y: date(y, 1, 1)),
        ("Valentine's Day", r"\bvalentine'?s?(?: day)?\b", lambda y: date(y, 2, 14)),
        ("Presidents' Day", r"\bpresident'?s'? day\b", lambda y: _nth(y, 2, 0, 3)),
        ("Easter", r"\beaster\b", _easter),
        ("Mother's Day", r"\bmother'?s day\b", lambda y: _nth(y, 5, 6, 2)),
        ("Memorial Day", r"\bmemorial day\b", lambda y: _last(y, 5, 0)),
        ("Father's Day", r"\bfather'?s day\b", lambda y: _nth(y, 6, 6, 3)),
        ("the Fourth of July", r"\b(?:fourth|4th) of july\b|\bjuly 4th\b|\bindependence day\b", lambda y: date(y, 7, 4)),
        ("Labor Day", r"\blabor day\b", lambda y: _nth(y, 9, 0, 1)),
        ("Columbus Day", r"\bcolumbus day\b|\bindigenous peoples'? day\b", lambda y: _nth(y, 10, 0, 2)),
        ("Halloween", r"\bhalloween\b", lambda y: date(y, 10, 31)),
        ("Veterans Day", r"\bveterans'? day\b", lambda y: date(y, 11, 11)),
        ("Singles' Day", r"\bsingles'? day\b", lambda y: date(y, 11, 11)),
        ("Thanksgiving", r"\bthanksgiving\b", thanksgiving),
        ("Black Friday", r"\bblack friday\b", lambda y: thanksgiving(y) + timedelta(days=1)),
        ("Small Business Saturday", r"\bsmall business saturday\b", lambda y: thanksgiving(y) + timedelta(days=2)),
        ("Cyber Monday", r"\bcyber monday\b", lambda y: thanksgiving(y) + timedelta(days=4)),
        ("Cyber Week", r"\bcyber week\b", lambda y: thanksgiving(y) + timedelta(days=10)),
        ("Green Monday", r"\bgreen monday\b", lambda y: _nth(y, 12, 0, 2)),
        ("Christmas", r"\bchristmas\b|\bxmas\b", lambda y: date(y, 12, 25)),
        ("Boxing Day", r"\bboxing day\b", lambda y: date(y, 12, 26)),
    ))
# A sale named as the wave before a day ("Early Black Friday Sale", "Pre-Black Friday Deals", "Black Friday Preview",
# "Countdown to Black Friday", "Black Friday Warm-Up Sale") says it ends before the day, not when.
BEFORE = re.compile(r"\bearly\b|\bpre(?:-\s?|\s+)(?=[a-z])|\bpreview\b|\bsneak peek\b|\bcountdown\b|\bwarm[- ]?up\b|\bkick-?off\b|"
                    r"\bahead of\b|\bbefore\b", re.I)
# A day's name as a web address writes it: "/overtexas/black-friday-deal".
SLUG = re.compile(r"black-?friday|cyber-?(?:monday|week)|(?:memorial|labor|presidents|veterans|columbus|mothers|fathers|"
                  r"valentines|boxing)-?day|fourth-of-july|thanksgiving|halloween|easter|christmas|new-?years", re.I)
AHEAD_DAYS = 60            # a day further ahead of the post than this is next year's: the post is about this year's


def named(text: str) -> list[str]:
    """The days a text names, in the calendar's order."""
    return [name for name, rx, _ in DAYS if rx.search(text)]


def day_of(text: str, posted: date) -> Optional[tuple[str, date]]:
    """The last of the days a text names that had not passed when it was posted: (its name, its date). A post names
    this year's day, or the coming one's when the year is about to turn ("New Year's Sale" on December 28)."""
    best: Optional[tuple[str, date]] = None
    for name, rx, when in DAYS:
        if not rx.search(text):
            continue
        d = when(posted.year)
        if d < posted and when(posted.year + 1) <= posted + timedelta(days=AHEAD_DAYS):
            d = when(posted.year + 1)
        if posted <= d <= posted + timedelta(days=AHEAD_DAYS) and (best is None or d > best[1]):
            best = (name, d)
    return best
