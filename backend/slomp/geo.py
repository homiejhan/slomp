"""Distances, and dates in a city's own time zone (El Paso and Hudspeth counties are on Mountain time)."""
from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

EARTH_MI = 3958.8
KM_PER_MI = 1.609344


def miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return EARTH_MI * 2 * math.asin(min(1.0, math.sqrt(a)))


def parse_time(raw) -> Optional[datetime]:
    """An ISO timestamp with an offset; naive times can't be compared honestly with 'now', so they are rejected."""
    if not raw:
        return None
    try:
        d = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else None


def local_day(d: datetime, tz: str) -> str:
    return d.astimezone(ZoneInfo(tz)).strftime("%a %b %-d")


def _utc(d: datetime) -> bool:
    return d.utcoffset() == timedelta(0)


def ad_end_local(d: datetime, tz: str) -> datetime:
    """Ads end at 11:59 PM on their last day in the store's own zone. Flipp states that in Eastern time
    ('23:59:59-04:00', which is 22:59 Central) or in UTC ('03:59:59Z' the next morning); either way the last day is
    the date the ad names, so the end becomes 11:59:59 PM of that date in the city's zone."""
    if _utc(d) and d.hour < 12:
        day = (d - timedelta(hours=12)).date()
    elif d.hour == 23 and d.minute == 59:
        day = d.date()
    else:
        return d.astimezone(ZoneInfo(tz))
    return datetime(day.year, day.month, day.day, 23, 59, 59, tzinfo=ZoneInfo(tz))


def ad_start_local(d: datetime, tz: str) -> datetime:
    """Ads start at midnight on their first day in the store's own zone ('00:00-04:00', or '04:00Z' the same day)."""
    if (_utc(d) and 3 <= d.hour <= 8) or (d.hour == 0 and d.minute == 0):
        day = d.date()
    else:
        return d.astimezone(ZoneInfo(tz))
    return datetime(day.year, day.month, day.day, tzinfo=ZoneInfo(tz))


def days_between(a: datetime, b: datetime, tz: str) -> int:
    """Calendar days from a to b in the city's zone (0 = same day)."""
    z = ZoneInfo(tz)
    return (b.astimezone(z).date() - a.astimezone(z).date()).days
