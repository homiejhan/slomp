"""When a regular deal runs, and the wording that says so.

A schedule is a set of weekdays or a monthly rule, optional times of day and an optional last day. The reading
functions take sentences as deal sites and company pages write them: "After 5 p.m. local time on Wednesdays",
"Mondays through Fridays", "every day but Saturday", "through Dec. 31", "every Wednesday in September".
"""
from __future__ import annotations

import calendar
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Iterable, Optional
from zoneinfo import ZoneInfo

DAY_KEYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
DAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
ORDINALS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "last": -1, "1st": 1, "2nd": 2, "3rd": 3, "4th": 4}
ZONES = {"p": "America/Los_Angeles", "m": "America/Denver", "c": "America/Chicago", "e": "America/New_York"}
Window = tuple[Optional[time], Optional[time]]          # (from, to); None is "from opening" or "until close"


@dataclass
class Schedule:
    days: list[int] = field(default_factory=list)       # 0 = Monday ... 6 = Sunday
    monthly: str = ""                                     # "1:1" first Tuesday, "-1:4" last Friday, "d:7" the 7th
    windows: list[Window] = field(default_factory=list)
    zone: str = ""                                        # set when the source states its times in another zone
    until: Optional[date] = None                          # the last day it runs, when the source gives one
    since: Optional[date] = None

    def runs_on(self, d: date) -> bool:
        if (self.since and d < self.since) or (self.until and d > self.until):
            return False
        if self.monthly:
            kind, n = self.monthly.split(":")
            if kind == "d":
                return d.day == int(n)
            if d.weekday() != int(n):
                return False
            if int(kind) == -1:
                return d.day + 7 > calendar.monthrange(d.year, d.month)[1]
            return (d.day - 1) // 7 + 1 == int(kind)
        return d.weekday() in self.days

    def local_windows(self, d: date, tz: ZoneInfo) -> list[Window]:
        """The day's time windows in the city's zone."""
        if not self.zone or not self.windows:
            return self.windows
        src = ZoneInfo(self.zone)

        def shift(t: Optional[time]) -> Optional[time]:
            return datetime.combine(d, t, src).astimezone(tz).time().replace(tzinfo=None) if t else None
        return [(shift(a), shift(b)) for a, b in self.windows]

    def occurrences(self, start: datetime, end: datetime) -> list[date]:
        """The dates in [start, end] on which it runs and has not already finished. Both ends carry the city's zone."""
        tz = start.tzinfo if isinstance(start.tzinfo, ZoneInfo) else ZoneInfo("America/Chicago")
        out: list[date] = []
        d = start.date()
        while d <= end.date():
            if self.runs_on(d):
                w = self.local_windows(d, tz)
                over = d == start.date() and w and all(b is not None and b <= start.time() for _, b in w)
                not_yet = d == end.date() and w and all(a is not None and a >= end.time() for a, _ in w)
                if not over and not not_yet:
                    out.append(d)
            d += timedelta(days=1)
        return out

    # -- wording ------------------------------------------------------------------------------------------------
    def days_text(self) -> str:
        if self.monthly:
            kind, n = self.monthly.split(":")
            if kind == "d":
                return f"The {_ordinal(int(n))} of each month"
            nth = {1: "First", 2: "Second", 3: "Third", 4: "Fourth", -1: "Last"}[int(kind)]
            return f"{nth} {DAY_NAMES[int(n)]} of the month"
        days = sorted(set(self.days))
        if len(days) == 7:
            return "Every day"
        if len(days) == 1:
            return f"Every {DAY_NAMES[days[0]]}"
        run = _run(days)
        if run and len(days) >= 3:
            return f"{DAY_NAMES[run[0]]} to {DAY_NAMES[run[-1]]}"
        names = [DAY_NAMES[d] + "s" for d in (run or days)]
        return " and ".join(names) if len(names) == 2 else ", ".join(names[:-1]) + " and " + names[-1]

    def time_text(self, d: Optional[date] = None, tz: Optional[ZoneInfo] = None) -> str:
        windows = self.local_windows(d, tz) if (d and tz) else self.windows
        parts = []
        for a, b in windows:
            if a and b:
                parts.append(f"{_clock(a, b)}–{_clock(b)}")
            elif a:
                parts.append(f"after {_clock(a)}")
            elif b:
                parts.append(f"until {_clock(b)}")
        return " and ".join(dict.fromkeys(parts))

    def to_dict(self) -> dict:
        return {"days": [DAY_KEYS[d] for d in sorted(set(self.days))], "monthly": self.monthly,
                "windows": [[a.strftime("%H:%M") if a else None, b.strftime("%H:%M") if b else None]
                            for a, b in self.windows],
                "zone": self.zone, "until": self.until.isoformat() if self.until else None,
                "since": self.since.isoformat() if self.since else None,
                "days_text": self.days_text(), "time_text": self.time_text()}


def _ordinal(n: int) -> str:
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def _run(days: list[int]) -> list[int]:
    """The days as one consecutive run (wrapping past Sunday), or [] when they aren't one. [6, 0, 1] -> [6, 0, 1]."""
    s = set(days)
    for first in days:
        seq = [(first + k) % 7 for k in range(len(days))]
        if set(seq) == s:
            return seq
    return []


def _clock(t: time, other: Optional[time] = None) -> str:
    """'5 pm', '10:30 am', 'noon', 'midnight'. In a range, the first time drops its am/pm when the second shares it."""
    if (t.hour, t.minute) == (12, 0):
        return "noon"
    if (t.hour, t.minute) in ((0, 0), (23, 59)):
        return "midnight"
    h = t.hour % 12 or 12
    text = f"{h}:{t.minute:02d}" if t.minute else str(h)
    half = "am" if t.hour < 12 else "pm"
    shared = other is not None and (other.hour < 12) == (t.hour < 12) and (other.hour, other.minute) not in \
        ((12, 0), (0, 0), (23, 59))
    return text if shared else f"{text} {half}"


# --- weekdays ----------------------------------------------------------------------------------------------------
_FULL = r"(mon|tues|wednes|thurs|fri|satur|sun)days?"
_ABBR = r"(mon|tues?|wed(?:nes)?|thu(?:rs?)?|fri|sat(?:ur)?|sun)(?:days?)?\.?"
_SEP = r"\s*(?:-|–|—|to|through|thru)\s*"
_DAY_RANGE = re.compile(r"\b" + _ABBR + _SEP + _ABBR + r"(?![a-z])", re.I)
_DAY_NAME = re.compile(r"\b" + _FULL + r"\b", re.I)
_ALL_BUT = re.compile(r"\bevery ?day (?:but|except)\s+((?:" + _FULL + r"(?:\s*(?:,|and|or)\s*)?)+)", re.I)
_EVERY_DAY = re.compile(r"\bevery ?day\b|\bdaily\b|\ball week\b|\b(?:7|seven) days a week\b|\bevery single day\b", re.I)
_WEEKDAYS = re.compile(r"\bweekdays?\b", re.I)
_WEEKENDS = re.compile(r"\bweekends?\b", re.I)
# Day names that are not a schedule: brands, holidays, shows.
_NOT_A_DAY = re.compile(
    r"\bruby tuesday'?s?\b|\bt\.?g\.?i\.? ?friday'?s\b|\btuesday morning\b|\bwednesday addams\b|\bblack friday\b|"
    r"\bgood friday\b|\bcyber monday\b|\beaster sunday\b|\bsuper bowl sunday\b|\bash wednesday\b|\bfat tuesday\b|"
    r"\bgiving tuesday\b|\bsunday ticket\b|\b(?:monday|thursday|sunday) night football\b|\bfriday the 13th\b|"
    r"\bsmall business saturday\b", re.I)


def _day(token: str) -> int:
    return ("mon", "tue", "wed", "thu", "fri", "sat", "sun").index(token.lower()[:3])


def weekdays_in(text: str, every_day: bool = True) -> list[int]:
    """Every weekday a sentence names, ranges and exceptions included.
    'Mondays through Fridays' -> [0..4]; 'every day but Saturday' -> all but 5; 'Tuesdays and Thursdays' -> [1, 3].
    With `every_day` off, "every day" and "daily" alone name no days (they are often just a turn of phrase)."""
    t = _NOT_A_DAY.sub(" ", text or "")
    found: set[int] = set()
    m = _ALL_BUT.search(t)
    if m:
        found |= set(range(7)) - {_day(x.group(1)) for x in _DAY_NAME.finditer(m.group(1))}
        t = t[:m.start()] + " " + t[m.end():]
    for m in _DAY_RANGE.finditer(t):
        a, b = _day(m.group(1)), _day(m.group(2))
        found |= {(a + k) % 7 for k in range((b - a) % 7 + 1)}
    t = _DAY_RANGE.sub(" ", t)
    found |= {_day(m.group(1)) for m in _DAY_NAME.finditer(t)}
    if _WEEKDAYS.search(t):
        found |= {0, 1, 2, 3, 4}
    if _WEEKENDS.search(t):
        found |= {5, 6}
    if not found and every_day and _EVERY_DAY.search(t):
        found = set(range(7))
    return sorted(found)


def parse_days(items: Iterable[str]) -> tuple[list[int], str]:
    """Registry wording -> (weekdays, monthly rule): ['tue', 'thu'], ['daily'], ['weekdays'], ['first tue'], ['7th']."""
    days: set[int] = set()
    monthly = ""
    for raw in items:
        s = raw.strip().lower()
        m = re.fullmatch(r"(first|second|third|fourth|last|1st|2nd|3rd|4th)\s+([a-z]+)", s)
        if m:
            monthly = f"{ORDINALS[m.group(1)]}:{_day(m.group(2))}"
        elif re.fullmatch(r"\d{1,2}(?:st|nd|rd|th)", s):
            monthly = f"d:{int(s[:-2])}"
        elif s in ("daily", "every day", "everyday"):
            days |= set(range(7))
        elif s == "weekdays":
            days |= {0, 1, 2, 3, 4}
        elif s in ("weekend", "weekends"):
            days |= {5, 6}
        elif s[:3] in DAY_KEYS:
            days.add(_day(s))
        else:
            raise ValueError(f"not a day: {raw!r}")
    return sorted(days), monthly


# --- times of day ------------------------------------------------------------------------------------------------
_AP = r"(a\.?\s?m\.?|p\.?\s?m\.?)"
_T = r"(\d{1,2})(?::(\d{2}))?"
_ZONE = r"(?:\s*\(?\b([pmce])[sd]?t\b\)?)?"
_END_WORD = r"(noon|midnight|close|closing)"
_TIME_RANGE = re.compile(
    r"(?<![\d$.:/])(?:" + _T + r"\s*" + _AP + r"?|(open|opening|noon))\s*(?:-|–|—|to|until|till|'?til)\s*"
    r"(?:" + _T + r"\s*" + _AP + r"|" + _END_WORD + r")" + _ZONE, re.I)
_AFTER = re.compile(r"\b(?:after|from|starting at|beginning at|starts at)\s+(?:" + _T + r"\s*" + _AP + r"|(noon))" + _ZONE,
                    re.I)
_UNTIL = re.compile(r"\b(?:until|till|'?til|before|ends at)\s+(?:" + _T + r"\s*" + _AP + r"|" + _END_WORD + r")" + _ZONE,
                    re.I)


def _time(h: str, mnt: Optional[str], ap: str) -> Optional[time]:
    hour, minute = int(h), int(mnt or 0)
    if not 1 <= hour <= 12 or minute > 59:
        return None
    pm = ap.lower().startswith("p")
    return time((hour % 12) + (12 if pm else 0), minute)


def _word_time(word: str) -> Optional[time]:
    w = word.lower()
    return time(12, 0) if w == "noon" else time(23, 59) if w == "midnight" else None      # open / close: no bound


def time_windows(text: str) -> tuple[list[Window], str]:
    """(windows, zone) from wording like 'from 2-5PM', 'after 5 p.m.', 'until 4 p.m.', '4 pm to close'.
    A time counts only with am/pm (or noon/midnight) attached, so '6, 10 or 15 piece' and '12 and under' don't."""
    t = text or ""
    out: list[Window] = []
    zone = ""
    spans: list[tuple[int, int]] = []
    for m in _TIME_RANGE.finditer(t):
        h1, m1, ap1, w1, h2, m2, ap2, w2, z = m.groups()
        end = _time(h2, m2, ap2) if h2 else _word_time(w2)
        if h2 and end is None:
            continue
        if w1:
            start = _word_time(w1)
        else:
            start = _time(h1, m1, ap1 or ap2 or "pm")
            if start and not ap1 and end and start >= end:      # "10-2 pm" is 10 am to 2 pm
                start = time(start.hour - 12, start.minute) if start.hour >= 12 else start
        if start is None and not w1:
            continue
        if start is None and end is None:
            continue
        if start and end and end <= start:               # "9 pm - 2 am" runs past midnight: open-ended for the day
            end = None
        out.append((start, end))
        spans.append(m.span())
        zone = zone or ZONES.get((z or "").lower(), "")
    for rx, is_start in ((_AFTER, True), (_UNTIL, False)):
        for m in rx.finditer(t):
            if any(a <= m.start() < b or a < m.end() <= b for a, b in spans):
                continue
            g = m.groups()
            when = _time(g[0], g[1], g[2]) if g[0] else _word_time(g[3])
            if when is None:
                continue
            out.append((when, None) if is_start else (None, when))
            spans.append(m.span())
            zone = zone or ZONES.get((g[-1] or "").lower(), "")
    out = list(dict.fromkeys(out))
    # "after 4 pm" plus "until 10 pm" in one sentence is one window.
    if len(out) == 2 and out[0][1] is None and out[1][0] is None and out[0][0] and out[1][1] and out[0][0] < out[1][1]:
        out = [(out[0][0], out[1][1])]
    return out, zone


# --- end dates ---------------------------------------------------------------------------------------------------
_MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")
_MONTH = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"
_DOM = r"(\d{1,2})(?:st|nd|rd|th)?"
_YEAR = r"(?:,?\s*(20\d\d))?"
_THROUGH = r"\b(?:through|thru|until|till|'?til|ends?|ending|expires?|expiring|valid (?:through|thru|until)|good through)"
_UNTIL_MD = re.compile(_THROUGH + r"\s+(?:(?:" + _FULL + r"),?\s+)?" + _MONTH + r"\s+" + _DOM + _YEAR, re.I)
_UNTIL_NUM = re.compile(_THROUGH + r"\s+(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?", re.I)
_UNTIL_MONTH = re.compile(_THROUGH + r"\s+(?:the end of\s+)?(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b"
                          r"(?!\.?\s*\d)", re.I)
_IN_MONTH = re.compile(r"\b(?:in|all|during|throughout|this|for the month of|all of)\s+(january|february|march|april|may|"
                       r"june|july|august|september|october|november|december)\b(?!\s*\d)", re.I)
_A_DATE = re.compile(r"(?<![a-z])" + _MONTH + r"\s+" + _DOM + r"(?![\d%])" + _YEAR, re.I)


def _nearest(month: int, day: int, ref: date, year: Optional[int] = None) -> Optional[date]:
    """A month and day with no year: the year that puts the date nearest the reference date."""
    best = None
    for y in ([year] if year else (ref.year - 1, ref.year, ref.year + 1)):
        try:
            d = date(y, month, day)
        except ValueError:
            continue
        if best is None or abs((d - ref).days) < abs((best - ref).days):
            best = d
    return best


def _month_end(month: int, ref: date) -> date:
    first = _nearest(month, 1, ref)
    return date(first.year, month, calendar.monthrange(first.year, month)[1])


def last_day(text: str, ref: date) -> Optional[date]:
    """The last day an offer runs, when the wording gives one: 'through Dec. 31', 'every Wednesday in September',
    'thru 10/31'. `ref` is the date the page was written, which settles the year. An explicit end date beats a
    month ("This October ... Offer valid through Oct. 4" ends Oct 4), and the first one stated is the offer's
    ("Through Oct. 3 ... Reward redeemable through Oct. 31" ends Oct 3)."""
    t = text or ""
    stated: list[tuple[int, date]] = []
    for m in _UNTIL_MD.finditer(t):
        d = _nearest(_MONTHS.index(m.group(2)[:3].lower()) + 1, int(m.group(3)), ref,
                     int(m.group(4)) if m.group(4) else None)
        if d:
            stated.append((m.start(), d))
    for m in _UNTIL_NUM.finditer(t):
        mo, dy = int(m.group(1)), int(m.group(2))
        if 1 <= mo <= 12 and 1 <= dy <= 31:
            yr = int(m.group(3)) if m.group(3) else None
            d = _nearest(mo, dy, ref, (2000 + yr if yr and yr < 100 else yr))
            if d:
                stated.append((m.start(), d))
    if stated:
        return min(stated)[1]
    found: list[date] = []
    for m in _UNTIL_MONTH.finditer(t):
        found.append(_month_end(_MONTHS.index(m.group(1)[:3].lower()) + 1, ref))
    for m in _IN_MONTH.finditer(t):
        if m.group(1).lower() == "may" and not re.search(r"\b(?:in|during|throughout|all of) may\b", m.group(0), re.I):
            continue                                        # "this may", "all may" are not the month
        found.append(_month_end(_MONTHS.index(m.group(1)[:3].lower()) + 1, ref))
    return max(found) if found else None


_VALID_ON = re.compile(r"\b(?:valid|good|available|redeemable)(?: only)? on\s+(?:[a-z]+day,?\s+)?"
                       r"(?P<mon>jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(?P<day>\d{1,2})(?:st|nd|rd|th)?"
                       r"(?![\d%])(?:,?\s*(?P<year>20\d\d))?", re.I)


def valid_on(text: str, ref: date) -> Optional[date]:
    """The one date an offer says it is valid on: 'Offer valid on Sept. 30.' An entry that also says 'every Wednesday'
    is still good for that date only, so the date is its last day."""
    m = _VALID_ON.search(text or "")
    if not m:
        return None
    return _nearest(_MONTHS.index(m.group("mon").lower()) + 1, int(m.group("day")), ref,
                    int(m.group("year")) if m.group("year") else None)


def single_dates(text: str, ref: date) -> list[date]:
    """Calendar dates a sentence names outright ('On Tuesday, Sept. 29', 'Oct. 3 - 4'), leaving out end dates
    ('through Dec. 31'). An offer with such dates and no 'every' is a one-off, not a regular deal."""
    t = _UNTIL_MD.sub(" ", text or "")
    out = []
    for m in _A_DATE.finditer(t):
        d = _nearest(_MONTHS.index(m.group(1)[:3].lower()) + 1, int(m.group(2)), ref,
                     int(m.group(3)) if m.group(3) else None)
        if d:
            out.append(d)
    return sorted(set(out))


def says_recurring(text: str) -> bool:
    """Wording that states a repeat: 'every', 'each week', 'weekly', or a plural day ('Tuesdays')."""
    t = _NOT_A_DAY.sub(" ", text or "")
    return bool(re.search(r"\bevery\b|\beach (?:week|mon|tues|wednes|thurs|fri|satur|sun)|\bweekly\b|"
                          r"\b(?:mon|tues|wednes|thurs|fri|satur|sun)days\b", t, re.I))
