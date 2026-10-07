"""Restaurant promotions near a city: national chain offers (dealnews Restaurants, Slickdeals) that a branch near the
city honors, valid at some point in the next 7 days.

A promotion is shown only when (a) the chain is identified, (b) OpenStreetMap has a branch of it within the radius,
and (c) its dates overlap the window. Recurring offers ("every Tuesday") count when that weekday falls in the window.
"""
from __future__ import annotations

import asyncio
import re
from collections import Counter
from datetime import date, datetime, time, timedelta
from functools import lru_cache
from typing import Optional
from zoneinfo import ZoneInfo

from .geo import days_between
from .models import City, LocalDeal, Terms
from .reference import norm
from .sources.feeds import DealFeeds, FeedPlan, Post, dealnews_url
from .sources.stores import RestaurantLocator, _restaurants
from .terms import clean

FEEDS = (
    FeedPlan("dealnews", "dealnews c377 restaurants", dealnews_url(377), ["dining"]),
    FeedPlan("slickdeals", "slickdeals q=restaurant",
             "https://slickdeals.net/newsearch.php?mode=frontpage&searcharea=deals&searchin=first&rss=1&q=restaurant", []),
    FeedPlan("slickdeals", "slickdeals freebies", "https://slickdeals.net/forums/external.php?type=RSS2&forumids=4", []),
)
_MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov",
                                        "dec"], 1)}
_MONTH = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"
_DAY = r"(\d{1,2})(?:st|nd|rd|th)?"
_RANGE_MD = re.compile(_MONTH + r"\s+" + _DAY + r"\s*(?:-|–|to|through|thru)\s*(?:" + _MONTH + r"\s+)?" + _DAY + r"\b", re.I)
_RANGE_NUM = re.compile(r"\b(\d{1,2})/(\d{1,2})(?:/\d{2,4})?\s*(?:-|–|to|through|thru)\s*(\d{1,2})/(\d{1,2})(?:/\d{2,4})?\b",
                        re.I)
_UNTIL = re.compile(r"\b(?:through|thru|until|till|ends?|expires?|valid (?:through|thru|until)|by)\s+(?:" + _MONTH +
                    r"\s+" + _DAY + r"|(\d{1,2})/(\d{1,2}))", re.I)
_ON_MD = re.compile(r"\b" + _MONTH + r"\s+" + _DAY + r"\b", re.I)
_ON_NUM = re.compile(r"(?<![\d/])(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?(?![\d/])")
_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
_RECUR = re.compile(r"\b(?:every|on|all day|each)?\s*(" + "|".join(_WEEKDAYS) + r")s\b", re.I)
_TODAY = re.compile(r"\btoday only\b|\btoday\b", re.I)
_NOT_A_PROMO = re.compile(r"\be?-?gift ?cards?\b|\bsubscription\b|\bsweepstakes\b|\binstant win\b|\bscratch (?:to|and) win\b|"
                          r"\bgiveaway\b|\bmonopoly game\b|\bshipping\b|\bmerch\b|\bgrocery\b|\bat (?:walmart|target|"
                          r"amazon|kroger|costco|sam's club)\b|\bk-cups?\b|\bcoffee pods\b|\bsauce\b.*\bamazon\b", re.I)


def _date(month: int, day: int, ref: date) -> Optional[date]:
    """A month/day with no year: the year that puts it nearest the post date."""
    best = None
    for y in (ref.year - 1, ref.year, ref.year + 1):
        try:
            d = date(y, month, day)
        except ValueError:
            continue
        if best is None or abs((d - ref).days) < abs((best - ref).days):
            best = d
    return best


def promo_dates(text: str, posted: date) -> tuple[Optional[date], Optional[date], str]:
    """(first day, last day, how it was read). Either end may be None when the post doesn't say."""
    t = text or ""
    m = _RANGE_MD.search(t)
    if m:
        m1 = _MONTHS[m.group(1)[:3].lower()]
        m2 = _MONTHS[m.group(3)[:3].lower()] if m.group(3) else m1
        return _date(m1, int(m.group(2)), posted), _date(m2, int(m.group(4)), posted), "date range"
    m = _RANGE_NUM.search(t)
    if m:
        return (_date(int(m.group(1)), int(m.group(2)), posted), _date(int(m.group(3)), int(m.group(4)), posted),
                "date range")
    m = _UNTIL.search(t)
    if m:
        end = (_date(_MONTHS[m.group(1)[:3].lower()], int(m.group(2)), posted) if m.group(1)
               else _date(int(m.group(3)), int(m.group(4)), posted))
        return None, end, "end date"
    found: list[date] = []
    for mm in _ON_MD.finditer(t):
        d = _date(_MONTHS[mm.group(1)[:3].lower()], int(mm.group(2)), posted)
        if d:
            found.append(d)
    for mm in _ON_NUM.finditer(t):
        mo, dy = int(mm.group(1)), int(mm.group(2))
        if 1 <= mo <= 12 and 1 <= dy <= 31:
            d = _date(mo, dy, posted)
            if d:
                found.append(d)
    if found:
        return min(found), max(found), "single date" if len(set(found)) == 1 else "dates"
    if _TODAY.search(t):
        return posted, posted, "today (post date)"
    return None, None, ""


def recurring_days(text: str) -> list[int]:
    return sorted({_WEEKDAYS.index(m.group(1).lower()) for m in _RECUR.finditer(text or "")})


@lru_cache(maxsize=1)
def _alias_patterns() -> list[tuple[re.Pattern, str]]:
    out = []
    for qid, b in _restaurants()["brands"].items():
        for a in {b["name"], *b.get("aliases", [])}:
            if len(norm(a)) >= 4:
                out.append((re.compile(r"(?<![\w'])" + re.escape(a) + r"(?![\w])", re.I), qid))
    out.sort(key=lambda x: -len(x[0].pattern))
    return out


def brand_in(text: str) -> Optional[str]:
    for rx, qid in _alias_patterns():
        if rx.search(text or ""):
            return qid
    return None


class RestaurantPromos:
    def __init__(self, feeds: DealFeeds, locator: RestaurantLocator):
        self.feeds, self.locator = feeds, locator

    async def posts(self) -> tuple[list[Post], list[dict]]:
        results = await asyncio.gather(*(self.feeds.read(p) for p in FEEDS))
        posts, sources, seen = [], [], set()
        for p, (got, err) in zip(FEEDS, results):
            sources.append({"name": p.name, "ok": not err, "posts": len(got), **({"error": err} if err else {})})
            for post in got:
                if post.id not in seen:
                    seen.add(post.id)
                    posts.append(post)
        return posts, sources

    def offer(self, p: Post, tz: ZoneInfo, start: datetime, end: datetime,
              excluded: Counter) -> Optional[tuple[str, LocalDeal]]:
        """One post as a mapped restaurant chain's promotion whose dates overlap [start, end], before any branch is
        looked up: (the chain's Wikidata id, the deal), or None with the reason counted in `excluded`."""
        if _NOT_A_PROMO.search(p.title):
            excluded["promotion: gift card, subscription, game or merchandise"] += 1
            return None
        qid = None
        if p.seller:
            hit = self.locator.brand(p.seller)
            qid = hit[0] if hit else None
        qid = qid or brand_in(p.title)
        if not qid:
            excluded["promotion: not a mapped restaurant chain"] += 1
            return None
        posted = (p.posted_at or start).astimezone(tz).date()
        text = f"{p.title}. {p.text[:400]}"
        first, last, how = promo_dates(text, posted)
        if p.expires_stated and p.expires_at:
            stated = p.expires_at.astimezone(tz).date()
            if not first or stated >= first:          # an expiry before the stated start is a feed error
                last, how = stated, how or "stated expiry"
        recur = recurring_days(text)
        if recur and not first:
            # "Every Tuesday": the next such day in the window.
            d0 = start.date()
            nxt = min((d0 + timedelta(days=(wd - d0.weekday()) % 7) for wd in recur))
            first, last, how = nxt, last or end.date(), "recurring weekday"
        if not (first or last):
            age_days = (start.date() - posted).days
            if age_days > 3:
                excluded["promotion: no dates and posted over 3 days ago"] += 1
                return None
            first, last, how = posted, None, "no dates stated"
        if first and last and last < first:
            last = first
        vf = datetime.combine(first or posted, time.min, tz)
        vt = datetime.combine(last, time(23, 59, 59), tz) if last else end
        if vt < start or vf > end:
            excluded["promotion: outside the 7-day window"] += 1
            return None
        name = _restaurants()["brands"][qid]["name"]
        terms = Terms(promo=True, basis="none", summary=clean(p.title)[:140],
                      conditions=[c for c in ("dates not stated" if how == "no dates stated" else "",
                                              "in the app" if re.search(r"\bapp\b", text, re.I) else "",
                                              "dine-in only" if re.search(r"dine-?in", text, re.I) else "") if c])
        return qid, LocalDeal(
            id=f"promo:{p.id}", item_id=0, flyer_id=0, title=clean(p.title), merchant=name, brand=name,
            industries=["dining"], industry_rule="restaurant chain", category="Restaurants", terms=terms, valid_from=vf,
            valid_to=vt, source_url=p.url, image_url=p.image,
            starts_in_days=max(0, days_between(start, vf, tz.key)), ends_in_days=days_between(start, vt, tz.key),
            raw={"source": p.source, "dates": how, "posted": posted.isoformat(), "text": p.text[:600]})

    async def near(self, city: City, radius_mi: float, start: datetime, end: datetime,
                   excluded: Counter) -> tuple[list[LocalDeal], list[dict]]:
        posts, sources = await self.posts()
        tz = ZoneInfo(city.tz)
        out: list[LocalDeal] = []
        for p in posts:
            got = self.offer(p, tz, start, end, excluded)
            if not got:
                continue
            qid, d = got
            branch = self.locator.nearest(qid, city)
            if not branch or branch.distance_mi > radius_mi:
                excluded["promotion: no branch nearby"] += 1
                continue
            d.store, d.store_status, d.merchant, d.brand = branch, "nearby", branch.merchant, branch.merchant
            out.append(d)
        return out, sources
