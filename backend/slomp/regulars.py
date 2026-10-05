"""Regular deals: standing offers that repeat on a schedule (BOGO Wednesdays, discount movie Tuesdays).

Where Slomp learns of them, in the order it trusts them:
  registry   slomp/data/regulars.json: curated entries, each naming the pages that state it and the words to find there
  lists      the day-of-week roundups (sources/roundups.py), read automatically
  yours      ~/.config/slomp/regulars.json: entries you add yourself, shown as "added by you"

Once for the whole state (cached):  collect -> normalize -> confirm -> merge -> gate.
Per search:  locate the nearest branch within the radius -> expand to the dates it runs in the next 7 days -> rank.

A regular deal is shown only while a piece of its evidence is live (LIVE_DAYS). Every card carries its evidence, so
"confirmed on the company's site today" and "listed by one deal site last week" never look the same.
"""
from __future__ import annotations

import asyncio
import hashlib
import html as htmllib
import json
import re
import time as clock
from collections import Counter
from dataclasses import dataclass, field
from functools import lru_cache
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Iterable, Optional
from urllib.parse import quote_plus, urlsplit
from zoneinfo import ZoneInfo

from .config import TTL, Settings
from .db import Store as DB
from .geo import days_between, miles
from .http import Blocked, Disallowed, FetchError, PoliteClient
from .models import BASIS_WEIGHT, City, LocalDeal, Store, Terms
from .reference import DATA, fold
from .schedule import (DAY_KEYS, Schedule, last_day, parse_days, says_recurring, single_dates, time_windows, valid_on,
                       weekdays_in)
from .sources.roundups import QUALIFIES, Listing, Roundups, sentences
from .sources.venues import KIND_INDUSTRIES, Chain, Venues
from .terms import bogo_of, pct as pct_off

# How old a piece of evidence may be and still count, in days: a company page since Slomp last read it and found the
# words; a roundup or article since the page itself was last modified.
LIVE_DAYS = {"official": 7, "rewards": 7, "list": 45, "article": 180}
EVIDENCE_WEIGHT = {"confirmed": 1.0, "listed2": 0.9, "listed": 0.75, "reported": 0.7, "yours": 0.5}
STATUS_ORDER = ("confirmed", "listed", "reported", "yours")
SET_TTL_S = 6 * 3600
WITHIN = 500                 # the words an evidence page must contain have to sit this close together
GEOCODER = "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"


@dataclass
class Evidence:
    kind: str                            # official | rewards | list | article | yours
    source: str                          # "cinemark.com", "The Krazy Coupon Lady", "you"
    url: str = ""
    quote: str = ""                      # the words found on the page
    page_date: Optional[date] = None     # the page's own date, when it gives one
    checked_at: Optional[datetime] = None
    found: Optional[bool] = None         # None: the page could not be read
    live: bool = False
    note: str = ""
    off: list[str] = field(default_factory=list)   # coming dates the page itself marks as sold out (ISO dates)
    until: Optional[date] = None                   # an expiry the page states for this offer ("Expires 10/19/2026")

    def to_dict(self) -> dict:
        return {"kind": self.kind, "source": self.source, "url": self.url, "quote": self.quote,
                "page_date": self.page_date.isoformat() if self.page_date else None,
                "checked_at": self.checked_at.isoformat(timespec="minutes") if self.checked_at else None,
                "found": self.found, "live": self.live, "note": self.note}


@dataclass
class Regular:
    id: str
    brand: str
    offer: str
    schedule: Schedule
    terms: Terms
    industries: list[str]
    origin: str                                  # registry | list | yours
    chain: Optional[Chain] = None
    places: list[dict] = field(default_factory=list)      # named places with coordinates, for single shops
    area: Optional[dict] = None
    conditions: list[str] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    kind: str = "restaurant"
    link: str = ""
    image_url: str = ""
    note: str = ""
    absorbs: list[str] = field(default_factory=list)
    suppress: str = ""                           # why matching list entries must not be shown (and nor is this)
    exact_days: bool = False                     # the company's page gives these days and no others for this offer
    hours_vary: bool = False                     # it has hours, but they differ by day, so none are stated
    wording: str = ""                            # a list entry's whole wording about the offer, shown or not
    site: str = ""                               # the place's own website, for its logo (registry `site`)
    logo: dict = field(default_factory=dict)     # {"url", "fit"} from logos.json, when there is one
    cue_days: list[int] = field(default_factory=list)          # the days the offer's own sentence names
    cue_conditions: list[str] = field(default_factory=list)    # ...and the conditions that sentence states
    clash: bool = False                          # another list gives a different price for the same item
    pages: set = field(default_factory=set)      # list entries: the weekdays whose pages carried this wording
    checks: list[dict] = field(default_factory=list, repr=False)   # registry evidence still to be read

    @property
    def status(self) -> str:
        live = {e.kind for e in self.evidence if e.live}
        if live & {"official", "rewards"}:
            return "confirmed"
        return "listed" if "list" in live else "reported" if "article" in live else "yours" if "yours" in live else ""

    @property
    def weight(self) -> float:
        s = self.status
        if s == "listed" and len({e.source for e in self.evidence if e.live and e.kind == "list"}) >= 2:
            s = "listed2"
        return EVIDENCE_WEIGHT.get(s, 0.0)


@dataclass
class RegularSet:
    regulars: list[Regular] = field(default_factory=list)
    excluded: Counter = field(default_factory=Counter)
    sources: list[dict] = field(default_factory=list)
    built_at: float = 0.0


# --- reading pages ---------------------------------------------------------------------------------------------
def tidy(text: str) -> str:
    """One spelling for quotes and dashes, no trademark signs, single spaces, no space before punctuation."""
    t = (text or "").replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    t = re.sub(r"[–—−]", "-", t)
    t = re.sub(r"[®™]", "", t)
    return re.sub(r"\s+([.,;:!?])", r"\1", re.sub(r"\s+", " ", t)).strip()


def page_texts(page: str) -> tuple[str, str]:
    """(the text a visitor sees, the text inside the page's data blocks). Sites built with JavaScript frameworks keep
    their wording in JSON inside <script>, which is still the page saying it."""
    body = re.sub(r"<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", page, flags=re.S | re.I)
    visible = tidy(htmllib.unescape(re.sub(r"<[^>]+>", " ", body)))
    strings = []
    for m in re.finditer(r"<script[^>]*>(.*?)</script>", page, re.S | re.I):
        if len(m.group(1)) < 40:
            continue
        for s in re.findall(r'"((?:[^"\\]|\\.){12,900})"', m.group(1)):
            if " " in s and not re.search(r"[{};=<>]|function\b|https?:", s[:80]):
                try:
                    s = json.loads('"' + s + '"')
                except ValueError:
                    pass
                strings.append(re.sub(r"<[^>]+>", " ", s))
    return visible, tidy(htmllib.unescape(" ".join(strings)))


def find_phrases(texts: Iterable[str], phrases: list[str], within: int = WITHIN) -> tuple[bool, str]:
    """Whether every phrase is on the page, close together, and the passage that holds them. Case, quote style and
    spacing don't matter; the words do."""
    want = [tidy(p) for p in phrases if p and p.strip()]
    if not want:
        return False, ""
    for text in texts:
        spots = [[m.start() for m in re.finditer(re.escape(p), text, re.I)] for p in want]
        if not all(spots):
            continue
        best: Optional[tuple[int, int]] = None
        for a in spots[0]:
            lo, hi = a, a + len(want[0])
            for p, sp in zip(want[1:], spots[1:]):
                near = min(sp, key=lambda x: abs(x - a))
                lo, hi = min(lo, near), max(hi, near + len(p))
            if (not within or hi - lo <= within) and (best is None or hi - lo < best[1] - best[0]):
                best = (lo, hi)
        if best:
            return True, _passage(text, *best)
    return False, ""


def _passage(text: str, lo: int, hi: int, pad: int = 40, limit: int = 220) -> str:
    a = max(0, lo - pad)
    b = min(len(text), max(hi + pad, a + 60))
    if a > 0:
        a = text.find(" ", a) + 1 or a
    if b < len(text):
        b = text.rfind(" ", a, b) if text.rfind(" ", a, b) > hi else b
    out = text[a:b].strip()
    if len(out) > limit:
        out = out[:limit].rsplit(" ", 1)[0]
        b = 0
    return ("…" if a > 0 else "") + out + ("…" if b < len(text) else "")


_PAGE_DATES = (r'"dateModified"\s*:\s*"(\d{4}-\d{2}-\d{2})', r'article:modified_time"\s+content="(\d{4}-\d{2}-\d{2})',
               r'content="(\d{4}-\d{2}-\d{2})[^"]*"\s+property="article:modified_time',
               r'"datePublished"\s*:\s*"(\d{4}-\d{2}-\d{2})', r'article:published_time"\s+content="(\d{4}-\d{2}-\d{2})',
               r'content="(\d{4}-\d{2}-\d{2})[^"]*"\s+property="article:published_time')


def page_date(page: str) -> Optional[date]:
    """The page's own date: last modified when it says, else published."""
    for rx in _PAGE_DATES:
        m = re.search(rx, page)
        if m:
            try:
                return date.fromisoformat(m.group(1))
            except ValueError:
                continue
    return None


def og_image(page: str) -> str:
    m = re.search(r'property="og:image"\s+content="(https://[^"]+)"', page) or \
        re.search(r'content="(https://[^"]+)"\s+property="og:image"', page)
    return htmllib.unescape(m.group(1)) if m else ""


def host_of(url: str) -> str:
    return urlsplit(url).netloc.lower().removeprefix("www.")


# --- what the offer is ------------------------------------------------------------------------------------------
_BOGO_PROSE = re.compile(
    r"\bbuy (?:one|1|an?|any)\b[^.]{0,70}?\b(?:get|receive)s? (?:one|1|another|a second|the second|a)\b[^.]{0,40}?"
    r"\b(free|(\d{1,2}) ?% off|half[- ](?:price|off))|\b(?:2|two)[- ]for[- ](?:1|one)\b", re.I)
_HALF = re.compile(r"\bhalf[- ]?(?:priced?|off)\b|\b1/2[- ]?(?:priced?|off)\b|(?<!\d)50 ?% off\b", re.I)
_PCT = re.compile(r"(?<![\d.])(\d{1,2}) ?% (?:off|discount)\b|\bsaves? (\d{1,2}) ?%", re.I)
_UP_TO = re.compile(r"\bup to (?:\d{1,2} ?%|half|50)", re.I)
_REF = re.compile(r"\((?:reg(?:ular(?:ly)?)?\.?|menu price|normally|orig(?:inally)?\.?|was)\s*(?:price\s*)?\$\s?"
                  r"(\d+(?:\.\d{1,2})?)\+?[^)]{0,40}\)|\bregularly (?:priced at )?(?:about |around )?\$\s?(\d+(?:\.\d{1,2})?)",
                  re.I)
_PRICE = re.compile(r"(?<![\w$.])\$\s?(\d+(?:\.\d{2})?)(?![\d.]\d)(?!\+?\s?(?:off\b|or more|purchase|minimum|in gift))", re.I)
_VALUE = re.compile(r"\((?:up to )?(?:an? )?\$\s?\d+(?:\.\d{2})? value\)|\$\s?\d+(?:\.\d{2})?\+? value\b", re.I)
_NOT_A_PRICE_BEFORE = re.compile(r"(?:purchase of|orders? of|order of|spend(?:ing)?|saves?(?: about| up to| around)?|"
                                 r"worth|over|minimum(?: of)?|least|every|per|extra|additional|for an)\s*$", re.I)
_CENTS = re.compile(r"(?<![\w$.])(\d{1,2})[- ]?(?:¢|cents?)\b", re.I)
_DOLLARS_OFF = re.compile(r"\$\s?(\d+(?:\.\d{1,2})?) off\b", re.I)
_KIDS_FREE = re.compile(r"\bkids?\b[^.]{0,40}?\beats? (?:for )?free\b|\bfree kids?'? ?(?:meal|entr[ée]e)", re.I)
_FREE = re.compile(r"\bfree (?!shipping|delivery|refills?\b|to join|membership|rewards|app\b|account|tier)"
                   r"([a-z0-9][\w'&-]*(?: [\w'&-]+){0,4})", re.I)


def offer_terms(text: str) -> Terms:
    """The offer in a sentence as v1's Terms. Conservative: a percent is set only when the wording gives one (a
    buy-one-get-one, "half price", "30% off") or gives both the price and the regular price."""
    s = tidy(text)
    t = Terms(promo=True, basis="none")
    label, eff = bogo_of(s)
    if not label:
        m = _BOGO_PROSE.search(s)
        if m:
            kind = (m.group(1) or "free").lower()
            off = 100.0 if kind == "free" else 50.0 if kind.startswith("half") else float(m.group(2))
            label, eff = f"buy 1 get 1 {'free' if off == 100 else f'{off:g}% off'}", round(off / 2, 1)
    refs = list(_REF.finditer(s))
    aside = [m.span() for m in refs] + [m.span() for m in _VALUE.finditer(s)]
    # One stated regular price for the same thing: "(reg. $9.99)". "(reg. $7.99 for a 12-count)" is another quantity.
    ref = float(refs[0].group(1) or refs[0].group(2)) if len(refs) == 1 and \
        not re.search(r"\bfor an?\b|\beach\b|\bper\b", refs[0].group(0), re.I) else None
    price, price_at = None, -1
    for m in _PRICE.finditer(s):
        if any(a <= m.start() < b for a, b in aside) or _NOT_A_PRICE_BEFORE.search(s[max(0, m.start() - 24):m.start()]):
            continue
        price, price_at = float(m.group(1)), m.start()
        break
    if price is None:
        c = _CENTS.search(s)
        price, price_at = (int(c.group(1)) / 100, c.start()) if c else (None, -1)
    if label:
        t.bogo, t.pct, t.basis, t.summary = label, eff, "store_regular", "BOGO" if "free" in label else label
        return t
    half, pc = _HALF.search(s), _PCT.search(s)
    if half or pc:
        t.pct = 50.0 if half and not (pc and pc.start() < half.start()) else float(pc.group(1) or pc.group(2))
        t.basis = "store_regular"
        t.hedge = "up to" if _UP_TO.search(s) else ""
        t.summary = ("up to " if t.hedge else "") + ("half price" if t.pct == 50 else f"{t.pct:g}% off")
        if ref:
            t.regular, t.price = ref, round(ref * (1 - t.pct / 100), 2)
        return t
    if price is not None and ref and price < ref:
        t.price, t.regular, t.savings, t.pct, t.basis = price, ref, round(ref - price, 2), pct_off(price, ref), "store_regular"
        t.summary = _money(price)
        return t
    if _KIDS_FREE.search(s):
        t.summary = "kids eat free"
        return t
    f = _FREE.search(s)
    thing = _free_thing(f.group(1)) if f else ""
    if f and thing and (price is None or f.start() < price_at):
        t.summary = f"free {thing}"                  # "a FREE appetizer (up to an $11.49 value) with a $30 purchase"
        return t
    off = _DOLLARS_OFF.search(s)
    if off and (price is None or off.start() < price_at):
        t.savings, t.basis, t.summary = float(off.group(1)), "claimed_savings", f"{_money(float(off.group(1)))} off"
        return t
    if price is not None:
        t.price, t.summary = price, _money(price)
        t.hedge = "starting at" if re.search(r"\b(?:starting at|start at|starts at|from|as low as)\s*$",
                                             s[max(0, price_at - 14):price_at], re.I) else ""
        return t
    if re.search(r"\bfor free\b|\bfree\b", s, re.I) and not re.search(r"\bfree (?:to join|shipping|delivery)\b", s, re.I):
        t.summary = f"free {thing}" if thing else "free item"
    return t


_FREE_STOP = {"with", "when", "at", "on", "for", "every", "each", "in", "to", "from", "plus", "and", "or", "if", "after",
              "per", "any", "while", "during", "of", "the", "this", "that", "via", "by", "all", "you", "your"}


def _free_thing(words: str) -> str:
    """'tacos with any other purchase' -> 'tacos'; 'at Smoothie King every' -> ''."""
    kept = []
    for w in words.lower().split():
        if w in _FREE_STOP:
            break
        kept.append(w)
    return " ".join(kept[:4])


def _money(v: float) -> str:
    return f"${v:,.2f}" if abs(v - round(v)) > 0.004 else f"${v:,.0f}"


_NOT_ALONE = r"(?!\s*(?:,|/|&|or\b|and\b))"       # "dine-in, to-go and delivery" names three ways, not one
_CONDITIONS = (
    (re.compile(r"\b(?:rewards?|loyalty|royal perks|stubs|crown club|movie rewards|mywalgreens|backstage pass|"
                r"seacret society|club) members?\b|\bmembers (?:can|get|receive)\b|\bmembership (?:required|needed)\b|"
                r"\bregistered user\b|\brewards? program\b|\bmembers (?:that|who)\b", re.I), "rewards members"),
    (re.compile(r"\bprime members?\b", re.I), "Prime members"),
    (re.compile(r"\bonline(?:,| or| and) in[- ](?:the )?app\b|\bonline or (?:in )?the \w+ app\b|\bin[- ]app or online\b|"
                r"\bonline,? in[- ]app,? (?:and|or) in[- ]store\b", re.I), ""),
    (re.compile(r"\bin[- ]app (?:offer|coupon|reward|purchase|only|deal|orders?|exclusive)\b|"
                r"\b(?:in|on|through|via) the (?:\w+ )?app\b|\buse the \w+ app\b|\bapp[- ]only\b|\bwith the app\b", re.I),
     "in the app"),
    (re.compile(r"\bdine[- ]?in only\b|\bfor dine[- ]in only\b|\bwhen you dine in\b|\bdine-in guests\b|"
                r"\b(?:valid|available) for dine[- ]in\b" + _NOT_ALONE + r"|\bdine[- ]in orders only\b|"
                r"\bonly\b[^.;]{0,40}\bdine[- ]in\b" + _NOT_ALONE + r"|\bdine[- ]in\b" + _NOT_ALONE + r"[^.;,]{0,25}\bonly\b",
                re.I), "dine-in only"),
    (re.compile(r"\b(?:signed|sign|logged|log) in(?:to)?\b[^.;]{0,40}\baccount\b|\baccount (?:is )?(?:required|needed)\b|"
                r"\bneed an? (?:\w+ )?account\b", re.I), "signed in to an account"),
    (re.compile(r"\bonly (?:available )?(?:in|at) the bar\b|\b(?:in|at) the bar(?: area)? only\b|\bbar[- ]area only\b",
                re.I), "at the bar only"),
    (re.compile(r"\b(?:valid|available|offered|served)\b(?! only)[^.;]{0,40}\b(?:at|in) the bar\b(?!(?: area)? only)|"
                r"\ba bar special\b|\bhappy hours?\b[^.;]{0,90}\b(?:in|at) the bar\b(?!(?: area)? only)", re.I), "at the bar"),
    (re.compile(r"\bwith (?:any |a |an? additional |any other )?purchase\b(?! of)", re.I), "with a purchase"),
    (re.compile(r"\bwhen you order takeout or delivery\b|\btakeout (?:or|and) delivery only\b", re.I), "takeout or delivery"),
    (re.compile(r"\bin[- ]store only\b|\bvalid in store\b(?! or\b| and\b)|\bin[- ]store orders only\b", re.I),
     "in store only"),
    (re.compile(r"\bparticipating\b|\b(?:select|many|some) (?:[\w'&]+ ){0,4}(?:locations|spots|restaurants|stores)\b|"
                r"\b(?:at )?most (?:\w+ )?locations\b|"
                r"\bvar(?:y|ies) by location\b|\btypical(?:ly)?\b|\bmay vary\b", re.I), "participating locations"),
    (re.compile(r"\bfor a limited time\b|\blimited[- ]time\b", re.I), "limited time"),
    (re.compile(r"\bwith (?:the |any |each |every |an? )?(?:purchase of (?:an? |any )?)?(?:regular[- ]priced |full[- ]priced? )?"
                r"adult (?:entr[ée]e|meal)\b|\bper adult (?:entr[ée]e|meal)\b|\bfor each adult entr[ée]e\b|"
                r"\bpurchase an? (?:full-priced? )?adult entr[ée]e\b", re.I), "with an adult entrée"),
    (re.compile(r"\bwhile supplies last\b", re.I), "while supplies last"),
)
_ONLINE_APP = re.compile(r"\bonline(?:,| or| and) in[- ](?:the )?app\b|\bonline or (?:in |with )?the \w+ app\b|"
                         r"\bin[- ]app or online\b|\bapp or (?:order )?online\b", re.I)
_LUNCH_DINNER = re.compile(r"\$(\d+(?:\.\d\d)?) (?:at )?lunch,? (?:and |or )?\$(\d+(?:\.\d\d)?) (?:at )?dinner", re.I)
_MIN_SPEND = re.compile(r"\bpurchase of \$(\d+(?:\.\d\d)?)(?: or more)?|"
                        r"\$(\d+(?:\.\d\d)?) (?:(?:or more|in|other|minimum|food|item|entr[ée]e|meal|order) ){0,3}purchases?\b", re.I)
_ONE_PER = re.compile(r"\b(?:one|1) (?:[\w'-]+ ){1,3}per (?:check|table|order|transaction|person|customer|visit|guest)\b", re.I)
_ALSO_STORE = re.compile(r"in[- ]store|dine[- ]in", re.I)
_APP_OR_STORE = re.compile(r"\b(?:online|app)\b[^.;]{0,60}\bor in[- ]?store\b", re.I)
_CODE = re.compile(r"\b(?:promo |coupon )?code ([A-Z][A-Z0-9]{3,})\b")
_LIMIT = re.compile(r"\blimit (?:of )?(one|two|three|\d+)\b", re.I)
_KIDS_AGE = re.compile(r"\b(?:kids?|children|ages?)(?: ages?)? (\d{1,2}) (?:and|&) (?:under|younger)\b|\b(\d{1,2}) and under\b",
                       re.I)
_AGE_UP = re.compile(r"\b(?:ages? )?(\d{2})\s?(?:\+|and (?:up|older|over))(?![\d%])|\bseniors? \(?(\d{2})\+?\)?", re.I)
_WORDNUM = {"one": 1, "two": 2, "three": 3}


def regular_conditions(text: str) -> list[str]:
    s = tidy(text)
    out = [label for rx, label in _CONDITIONS if label and rx.search(s)]
    if _ONLINE_APP.search(s) and not _ALSO_STORE.search(s):
        out.append("online or in the app")
        out = [c for c in out if c != "in the app"]
    elif _APP_OR_STORE.search(s):
        out = [c for c in out if c != "in the app"]          # "online, with the app, or in-store at the kiosk"
    m = _CODE.search(s)
    if m:
        out.append(f"code {m.group(1)}")
    m = _LUNCH_DINNER.search(s)
    if m:
        out.append(f"${m.group(1)} at lunch, ${m.group(2)} at dinner")
    m = _MIN_SPEND.search(s)
    if m:
        out.append(f"with a ${m.group(1) or m.group(2)} purchase")
    m = _LIMIT.search(s)
    if m:
        out.append(f"limit {_WORDNUM.get(m.group(1).lower(), m.group(1))}")
    elif _ONE_PER.search(s):
        out.append("limit 1")
    m = _KIDS_AGE.search(s)
    if m:
        out.append(f"kids {m.group(1) or m.group(2)} and under")
    m = _AGE_UP.search(s)
    if m and int(m.group(1) or m.group(2)) >= 50:
        out.append(f"age {m.group(1) or m.group(2)}+")
    return list(dict.fromkeys(out))


_FUN = re.compile(r"\b(?:games?|game play|all you can play|play pass|power card|bowling|laser tag|arcade|movies?|"
                  r"tickets?|admission|golf|attractions?)\b", re.I)
_FOOD = re.compile(r"\b(?:wings?|pizzas?|burgers?|tacos?|kids? (?:eat|meal)|appetizers?|entr[ée]es?|meals?|drinks?|beers?|"
                   r"margaritas?|cocktails?|happy hour|sandwich(?:es)?|fries|desserts?|buffet|lunch|dinner|brunch)\b", re.I)


def industries_for(chain: Optional[Chain], text: str, fallback: Iterable[str] = ()) -> list[str]:
    """A restaurant chain's deal on games is entertainment; its wings are dining; a cinema's deal is entertainment."""
    base = list(chain.industries if chain else fallback) or list(fallback)
    if chain and chain.kind in ("restaurant", "cafe", "bar") and _FUN.search(text):
        return ["entertainment"] + (["dining"] if _FOOD.search(text) else [])
    return base


# --- roundup listings -> regular deals ------------------------------------------------------------------------------
EVERYDAY = "an everyday offer, not tied to a day or time"
_EVERY = re.compile(r"\bevery ?day\b|\bdaily\b|\ball week\b|\b(?:7|seven) days a week\b", re.I)
_ONE_OFF = re.compile(r"\bgrand opening\b|\bfirst \d+ (?:guests?|customers?|people)\b|\bnew location\b|\bnow open\b|"
                      r"\bnational \w+(?: \w+)? day\b", re.I)
_NOT_A_DEAL = re.compile(r"\be?-?gift ?cards?\b|\bsweepstakes\b|\bgiveaways?\b|\benter (?:to|for a chance)\b|"
                         r"\bfree (?:\w+ )?for a year\b|\bdouble (?:rewards? )?points\b|\b\dx points\b|\bbonus points\b", re.I)
_DELIVERY_APPS = {"doordash", "grubhub", "ubereats", "instacart", "postmates", "tmobiletuesday", "tmobiletuesdays"}
_STATES = ("AL|AK|AZ|AR|CA|CO|CT|DE|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|MT|NE|NV|NH|NJ|NM|NY|NC|ND|OH|OK|"
           "OR|PA|RI|SC|SD|TN|UT|VT|VA|WA|WV|WI|WY")
_ELSEWHERE = re.compile(r", (?:" + _STATES + r")\b|\b(?:florida|california|ohio|michigan|arizona|new york|georgia)[- ]"
                        r"(?:based|only|locations)\b", re.M)
_VAGUE = re.compile(r"\b(?:rotating|weekly|new|different|varying|surprise|exclusive|extra) (?:\w+ )?(?:deals?|offers?|"
                    r"rewards?|coupons?|specials?|drops?|discounts?|freebie\w*)\b|\bcoupons?\b[^.]{0,90}\bavailable\b|"
                    r"\bfind \w+ coupons\b|\bwatch for\b|\bpromo code with\b|\ba money-saving promo code\b|"
                    r"\bplay the\b[^.]{0,40}\bgame\b|\bcoupons? (?:like|include)\b|\bdeals? like\b|"
                    r"\bsome (?:spots|locations|restaurants) (?:offer|have)\b", re.I)
# Wording that makes any figure in the sentence an example, not the offer: "usually has a deal, such as 15% off".
_EXAMPLE = re.compile(r"\busually (?:has|have|offers?)\b|\bthey'?ll post\b|\ba recent offer\b|\beach week to see\b|"
                      r"\b(?:deals?|offers?|discounts?)\b[^.]{0,30}\bchanges? (?:each|every) week\b", re.I)
_NEW_OFFER = re.compile(r"\$\s?\d|\d ?% off|\bbogo\b|\bbuy (?:one|1)\b|\bhalf[- ]?(?:priced?|off)\b|\bfree (?!to\b)\w|"
                        r"\balso (?:has|have|offers?|get)\b|\bkids? eat\b", re.I)
_REFERS_BACK = QUALIFIES            # a later sentence of the entry that restricts the offer, not another offer
_ALSO = re.compile(r"\balso (?:has|have|offers?|get)\b", re.I)
# Directions to the offer, not part of it: "Start at the Marco's Menu Page."
_HOW_TO = re.compile(r"^(?:start at|click|tap|read (?:our|more)|see (?:our|the|more)|check out|learn more|go to|from there|"
                     r"head to)\b", re.I)
_HH_ASIDE = re.compile(r",?\s*\b(?:plus|as well as|along with)\b[^.;]*\bhappy hour\b[^.;]*", re.I)
_SOME_WEEKS = re.compile(r"\b(?:select|most|some|certain) (?:mon|tues|wednes|thurs|fri|satur|sun)days\b", re.I)
_CUE = re.compile(r"\$\s?\d|\d ?%|\bbogo\b|\bbuy (?:one|1|an?)\b|\bhalf[- ]?(?:priced?|off)\b|\b1/2[- ]?(?:priced?|off)\b|"
                  r"\bfree\b|\b(?:2|two)[- ]for[- ](?:1|one)\b|\b\d{1,2}[- ]?cents?\b|\bkids? eat\b", re.I)


def _things(sentence: str, brand: str) -> set[str]:
    """The words that say what a sentence is about, for telling whether a later sentence is about the same offer."""
    own = {w for w in re.findall(r"[a-z]+", brand.lower())}
    out = set()
    for w in re.findall(r"[a-z]{4,}", _DAYWORD.sub(" ", tidy(sentence).lower())):
        w = w[:-1] if w.endswith("s") and len(w) > 4 else w
        if w not in _STOP and w not in own and w not in ("free", "special", "deal", "meal", "kids", "kid", "every", "each"):
            out.add(w)
    return out | ({"kids-eat-free"} if re.search(r"\bkids? (?:eat|meal)|\bfree kids?\b", sentence, re.I) else set())


def _hours_vary(text: str) -> bool:
    """The text gives different hours for different days, which one set of hours cannot state."""
    seen = set()
    for part in re.split(r",\s+|;\s+|(?<=[.!?])\s+", text):
        days, hours = tuple(weekdays_in(part, every_day=False)), time_windows(part)[0]
        if days and hours:
            seen.add((days, tuple(str(h) for h in hours)))
    return len({d for d, _ in seen}) >= 2 and len({h for _, h in seen}) >= 2


def _own_part(sentence: str, day: int) -> Optional[str]:
    """A sentence may list several offers, each with its own schedule: "an every day Value Menu starting at $1, taco
    specials on Tuesdays and Thursdays, and more deals". Its part that states an offer for `day`, or None when the
    figures belong to other days. A sentence with one schedule is returned whole."""
    parts = re.split(r",\s+", sentence)
    marks = []
    for c in parts:
        days = weekdays_in(c, every_day=False)
        marks.append(tuple(days) if days else "every" if _EVERY.search(c) else None)
    if len({m for m in marks if m}) < 2:
        return sentence
    mine = [c for c, m in zip(parts, marks) if m not in (None, "every") and day in m and _CUE.search(c)]
    return mine[0][0].upper() + mine[0][1:] if mine else None


def _shown(text: str, limit: int = 220) -> str:
    """The roundup's sentence(s), trimmed at a sentence end."""
    s = tidy(text)
    if len(s) <= limit:
        return s
    cut = max(s.rfind(". ", 0, limit), s.rfind("! ", 0, limit))
    return s[:cut + 1] if cut > 60 else s[:limit].rsplit(" ", 1)[0] + "…"


def from_listing(x: Listing, venues: Venues, today: date) -> Regular | str:
    """A regular deal from one roundup entry, or the reason it is not one."""
    brand = re.sub(r"[®™]", "", x.brand).strip()
    text = tidy(x.text)
    if fold(brand) in _DELIVERY_APPS:
        return "a delivery app's promotion"
    if _ONE_OFF.search(text) or (x.section in ("limited", "weekend") and single_dates(text, x.modified or today)
                                 and not says_recurring(text)):
        return "a one-off date, not a standing offer"
    if x.section == "weekend" and not says_recurring(text):
        return "a one-off date, not a standing offer"      # "this weekend" deals: nothing says they come back
    if _NOT_A_DEAL.search(text):
        return "a gift card, points or sweepstakes offer"
    if _ELSEWHERE.search(x.text):
        return "limited to places outside Texas"
    chain = venues.find(brand)
    if not chain:
        return "the chain has no mapped place in Texas"
    # Start at the first sentence that states an offer: lead-ins like "BJ's has daily specials good every day." carry
    # no offer, and their "every day" is not the schedule.
    sents = sentences(text)
    first = None
    for i, s in enumerate(sents):
        part = _own_part(s, x.day) if _CUE.search(s) else None
        if part:
            sents[i], first = part, i
            break
    if first is None:
        return "no concrete offer stated"
    # ...but keep the sentence just before it when that one gives the schedule: "Typical happy hours are 3-6 pm
    # Mondays through Fridays. Specials usually include $2 off margaritas." That includes "every day": "Endless
    # Shrimp is available every day. Get all-you-can-eat shrimp for $24.99." is no Saturday deal.
    cue = first
    while first > 0 and (weekdays_in(sents[first - 1], every_day=False) or time_windows(sents[first - 1])[0] or
                         (_EVERY.search(sents[first - 1]) and not _CUE.search(sents[first - 1]))):
        first -= 1
    # ...unless the offer's own sentence says when: then the sentence before is another matter ("Social Hour with
    # discounted drinks from 3-5 pm daily. Get a pizza lunch for $10.99 on weekdays."). Its conditions still count
    # ("IKEA Family members can enjoy deals every weekday. On Thursdays, seniors get 20% off.").
    lead_in: list[str] = []
    if weekdays_in(sents[cue], every_day=False) or time_windows(sents[cue])[0]:
        lead_in, first = sents[first:cue], cue
    # ...and stop before the next offer: "BJ's also has a $12 weekday lunch and a happy hour from 3-7 pm" is another
    # deal, and its hours are not this one's. Sentences that only qualify the offer ("Dine-in only.") stay.
    kept = sents[first:cue + 1]
    about_hh = bool(re.search(r"happy hour", " ".join(kept), re.I))
    rest = sents[cue + 1:]
    for s in rest:
        if _NEW_OFFER.search(s) or (not about_hh and re.search(r"happy hour", s, re.I)):
            break
        kept.append(s)
    # Past that point a sentence may still restrict this offer ("You can only get the special for dine-in orders").
    # Its conditions count, though it is not shown; the entry's other offers ("also has ...", other days) end the search.
    limits = []
    thing = _things(sents[cue], brand)
    for s in rest[len(kept) - (cue + 1 - first):]:
        other = weekdays_in(s, every_day=False)
        if _ALSO.search(s) or (other and x.day not in other) or (not about_hh and re.search(r"happy hour", s, re.I)):
            break
        # ...or says more about the same thing: "Huddle House has a free waffle every Wednesday. Get a free waffle with
        # a minimum $6 entree purchase."
        if _REFERS_BACK.search(s) or thing & _things(s, brand):
            limits.append(s)
    text = " ".join(s for i, s in enumerate(kept) if i <= cue - first or not _HOW_TO.match(s))
    # The days: the offer's own sentence if it names any, else the schedule sentence before it, else the page's day.
    own = weekdays_in(sents[cue], every_day=False)
    if own and x.day not in own:
        return "the sentence is about other days"
    named = own or next((d for d in (weekdays_in(s) for s in kept) if x.day in d), [])
    days = named or [x.day]
    # "$8 martinis on Mondays plus Happy Hour specials from 3-6 pm": the hours are the happy hour's, not the martinis'.
    aside = _HH_ASIDE.search(text)
    windows, zone = time_windows(text[:aside.start()] + text[aside.end():] if aside and _CUE.search(text[:aside.start()])
                                 else text)
    until = last_day(text, x.modified or today)
    only = valid_on(" ".join([text] + limits), x.modified or today)       # "every Wednesday ... Offer valid on Sept. 30."
    until = min(until, only) if until and only else until or only
    if until and until < today:
        return "past its stated end date"
    varies = _hours_vary(text)                   # "Monday - Thursday 4-7 pm and 10 pm - midnight, Fridays 4-7 pm"
    if varies:
        windows = []
    terms = offer_terms(text)
    concrete = bool(terms.bogo or terms.pct or terms.price or terms.savings or terms.summary)
    if not concrete or _EXAMPLE.search(text) or (_VAGUE.search(text) and not (terms.bogo or terms.pct or terms.regular)):
        return "no concrete offer stated"
    everyday = len(days) == 7 and not windows and not varies and terms.summary != "kids eat free"
    if _SOME_WEEKS.search(text):
        terms.hedge = terms.hedge or "select weeks"
    fresh = x.modified is not None and (today - x.modified).days <= LIVE_DAYS["list"]
    ev = Evidence("list", x.source_name, x.url, _shown(text, 260), x.modified, None, True, fresh,
                  "" if fresh else "the list page has not been updated lately")
    rid = hashlib.sha1(f"{chain.key}|{x.source}|{x.day}|{text[:80]}".encode()).hexdigest()[:10]
    conditions = regular_conditions(text) + (["not every week"] if _SOME_WEEKS.search(text) else []) + \
        (["hours differ by day"] if varies else [])
    conditions += [c for c in regular_conditions(" ".join(limits + lead_in + [x.context]))
                   if c not in conditions and c != "limited time"]
    # An everyday offer is not a regular deal, but it is kept as a stop: another list may file the same offer under
    # one weekday ("Save with the $1.99 menu" on a Monday page), and that must not turn it into a Monday deal.
    return Regular(id=f"{fold(chain.name)[:24]}-{rid}", brand=chain.name, offer=_shown(text), chain=chain,
                   schedule=Schedule(days=days, windows=windows, zone=zone, until=until), terms=terms,
                   industries=industries_for(chain, text), origin="list", conditions=conditions,
                   evidence=[ev], kind=chain.kind, link=x.brand_url, suppress=EVERYDAY if everyday else "",
                   pages={x.day}, hours_vary=varies, wording=" ".join([text] + limits), cue_days=list(own),
                   cue_conditions=regular_conditions(sents[cue]))


def everyday_stops(x: Listing, venues: Venues, today: date) -> list[Regular]:
    """Offers a list entry says are good every day ("Sonic also has a $1.99 Menu good every day"), wherever in the
    entry they sit. They are never shown; they stop another list's copy of the same offer from becoming one
    weekday's deal."""
    chain = venues.find(re.sub(r"[®™]", "", x.brand).strip())
    out: list[Regular] = []
    if not chain:
        return out
    for s in sentences(tidy(x.text)):
        if not (_CUE.search(s) and _EVERY.search(s)) or weekdays_in(s, every_day=False) or time_windows(s)[0]:
            continue
        terms = offer_terms(s)
        if terms.price or terms.pct or terms.bogo:
            rid = hashlib.sha1(f"{chain.key}|stop|{s[:80]}".encode()).hexdigest()[:10]
            out.append(Regular(id=f"stop-{rid}", brand=chain.name, offer=_shown(s), chain=chain,
                               schedule=Schedule(days=list(range(7))), terms=terms, industries=[], origin="list",
                               kind=chain.kind, suppress=EVERYDAY, pages=set(range(7))))
    return out


# --- same offer? ----------------------------------------------------------------------------------------------------
_STOP = set("a an and any are at be by can each enjoy every for free from get gets has have in is it its just more new "
            "of off offer offers on one only or order orders our per plus price score so that the their this to two up "
            "valid when with you your deal deals special specials day week weekly all day long also available good "
            "online app store dine members rewards member reward purchase regular reg about save".split())
# ...and words about when, where and how, which two different offers can share: "through", "local", "redeem".
_STOP |= set("through thru until till after before during now local time times today tonight grab score redeem redeemed "
             "registered user users valid posted page website site detail details visit story stories starting start "
             "check include includes included including choice enjoy celebrate guest guests customer customers location "
             "locations participating select selected announced chain restaurant restaurants jan feb mar apr may jun jul "
             "aug sep sept oct nov dec january february march april june july august september october november "
             "december".split())
_DAYWORD = re.compile(r"\b(?:mon|tues|wednes|thurs|fri|satur|sun)days?\b", re.I)


def offer_words(r: Regular) -> set[str]:
    text = _DAYWORD.sub(" ", tidy(r.offer).lower()).replace("1/2", "half")
    brand = {w for w in re.findall(r"[a-z]+", r.brand.lower())}
    words = set()
    for w in re.findall(r"[a-z]{3,}|\$?\d+(?:\.\d\d)?", text):
        w = w[:-1] if w.endswith("s") and len(w) > 4 else w
        if w not in _STOP and w not in brand:
            words.add("bogo" if w in ("bogo", "buy") else w)
    return words


def overlap(a: Regular, b: Regular) -> float:
    wa, wb = offer_words(a), offer_words(b)
    return len(wa & wb) / max(1, len(wa | wb))


def same_offer(a: Regular, b: Regular) -> bool:
    """Two entries for one chain on the same day describe the same offer: both buy-one-get-ones or the same price
    (within a few cents) on a shared thing, or mostly the same words."""
    wa, wb = offer_words(a), offer_words(b)
    shared = wa & wb
    things = {w for w in shared if not re.match(r"\$?\d", w) and w != "bogo"}
    if a.terms.bogo and b.terms.bogo:
        return bool(things) or not (wa - {"bogo"}) or not (wb - {"bogo"})
    if a.terms.bogo or b.terms.bogo:
        return False
    if a.terms.summary == b.terms.summary == "kids eat free":
        return True
    pa, pb = _stated_price(a), _stated_price(b)
    if pa and pb:
        # The same price on the same day is the same special, even in other words ("surf and turf for $24.99" and
        # "Tuesday Tails for $24.99"); a small round price needs a shared word, since "$5 beers" and "$5 pies" differ.
        close = abs(pa - pb) <= max(0.05, pa * 0.02)                 # "$3.98" and "$3.99" for the same Whopper
        return (close and bool(things)) or (pa == pb and (pa >= 6 or pa != round(pa)))
    if a.terms.pct and a.terms.pct == b.terms.pct and things:
        return True
    return len(shared) / max(1, len(wa | wb)) >= 0.5


def merge(regs: list[Regular], dropped: Optional[Counter] = None) -> list[Regular]:
    """One regular deal per chain and offer. Registry entries come first and absorb the list entries that match
    them; among list entries the first (most concise) wording wins and the evidence is pooled."""
    dropped = dropped if dropped is not None else Counter()
    out: list[Regular] = []
    by_chain: dict[str, list[Regular]] = {}
    order = {"registry": 0, "yours": 1, "list": 2}
    for r in sorted(regs, key=lambda r: (order[r.origin], not r.suppress,
                                         0 if any(e.source.startswith("The Krazy") for e in r.evidence) else 1, len(r.offer))):
        key = r.chain.key if r.chain else f"place:{r.id}"
        matched = False
        for kept in by_chain.get(key, []):
            if r.origin != "list" or r.suppress or kept.schedule.monthly:
                continue
            same_day = bool(set(r.schedule.days) & set(kept.schedule.days))
            twin = overlap(kept, r) >= 0.8 and kept.schedule.windows == r.schedule.windows and \
                weekdays_in(kept.offer, every_day=False) == weekdays_in(r.offer, every_day=False)     # the same sentence
            absorbed = kept.absorbs and same_day and any(k.lower() in r.offer.lower() for k in kept.absorbs)
            if kept.suppress and not kept.absorbs and not (twin or _shares_a_thing(kept, r)):
                continue                                 # an everyday stop only takes its own offer: same thing, same terms
            if absorbed or twin or (same_day and same_offer(kept, r)):
                if kept.suppress:
                    dropped[f"regular deal: {kept.suppress}"] += 1
                    r.schedule.days = []
                elif kept.origin != "list" and _stated_price(kept) and _stated_price(r) and \
                        _stated_price(kept) != _stated_price(r):
                    dropped["regular deal: a list gives a different price than the company's own page"] += 1
                    r.schedule.days = []
                else:
                    widen = twin and kept.origin == "list" and not kept.suppress
                    _pool(kept, r, widen)
                    # A two-day entry ("Mondays and Tuesdays") supports the other day's entry too: carry on with the
                    # days this one did not cover.
                    r.schedule.days = [] if widen else sorted(set(r.schedule.days) - set(kept.schedule.days))
                    if absorbed and kept.exact_days and r.schedule.days:
                        # The company's page says which days this offer runs; a list that adds days is not followed.
                        if set(r.schedule.days) & r.pages:
                            dropped["regular deal: a list gives other days than the company's own page"] += 1
                        r.schedule.days = []
                matched = True
            elif same_day and kept.origin == "list" and not kept.suppress and _price_clash(kept, r):
                kept.clash = True
                dropped["regular deal: lists disagree on the price, so it is not shown"] += 1
                matched, r.schedule.days = True, []
            if matched and not r.schedule.days:
                break
        # What is left of a matched entry stands alone only on days whose own page carried its wording.
        if matched:
            r.schedule.days = sorted(set(r.schedule.days) & r.pages)
        if not matched or r.schedule.days:
            by_chain.setdefault(key, []).append(r)
            out.append(r)
    keep = []
    for r in out:
        t = r.terms
        if r.suppress:
            continue
        if r.clash and len({e.source for e in r.evidence}) < 2:
            # One list says $14.49 and another $9.99 for the same lunch: one of them is out of date and Slomp can't
            # tell which. A price that two sources agree on survives a third that differs.
            dropped["regular deal: lists disagree on the price, so it is not shown"] += 1
            continue
        if r.origin == "list" and len(set(r.schedule.days)) >= 5 and not r.schedule.windows and not r.hours_vary and \
                not (t.bogo or t.pct or t.summary == "kids eat free"):
            dropped["regular deal: an everyday offer, not tied to a day or time"] += 1     # the same price all week
        else:
            keep.append(r)
    return keep


def _shares_a_thing(a: Regular, b: Regular) -> bool:
    return any(not re.match(r"\$?\d", w) and w != "bogo" for w in offer_words(a) & offer_words(b))


def _stated_price(r: Regular) -> Optional[float]:
    return None if r.terms.pct and not r.terms.regular else r.terms.price


def _price_clash(a: Regular, b: Regular) -> bool:
    """The same thing at two different prices: one of the lists is out of date."""
    pa, pb = _stated_price(a), _stated_price(b)
    if not (pa and pb) or abs(pa - pb) <= max(0.05, pa * 0.02):
        return False
    things = {w for w in offer_words(a) & offer_words(b) if not re.match(r"\$?\d", w) and w != "bogo"}
    return len(things) >= 2 or overlap(a, b) >= 0.5


_IN_PERSON = {"dine-in only", "in store only", "at the bar only", "at the bar"}
_REMOTE = {"online or in the app", "in the app", "takeout or delivery"}
_SAYS_REMOTE = re.compile(r"\b(?:online|take-?out|to-?go|delivery|pick-?up|in-app|app)\b", re.I)
_SAYS_IN_PERSON = re.compile(r"\bdine[- ]in\b|\bin[- ]store\b", re.I)


def _disputed(condition: str, other_wording: str) -> bool:
    """A restriction on how to order that the other list's wording goes against."""
    return (condition in _IN_PERSON and bool(_SAYS_REMOTE.search(other_wording))) or \
        (condition in _REMOTE and bool(_SAYS_IN_PERSON.search(other_wording))) or \
        (condition == "in the app" and bool(re.search(r"\bonline\b", other_wording, re.I)))


def _list_name(r: Regular) -> str:
    return next((e.source for e in r.evidence if e.kind == "list"), "one list")


def _pool(kept: Regular, r: Regular, widen: bool) -> None:
    """Add r's evidence to kept. Its days are added only when the wording is the same sentence seen on another day's
    page (a weekday happy hour): "BOGO traditional wings" on Tuesday must not borrow Thursday from "BOGO boneless"."""
    if widen:
        kept.schedule.days = sorted(set(kept.schedule.days) | set(r.schedule.days))
        kept.pages |= r.pages
        ends = [d for d in (kept.schedule.until, r.schedule.until) if d]
        kept.schedule.until = min(ends) if ends else None
    own_day = widen or bool(set(kept.schedule.days) & r.pages)
    if kept.origin == "list" and (own_day or set(kept.schedule.days) & set(r.cue_days)):
        # Two lists describe one deal: a restriction either states is shown. Where the other list's words go against
        # it ("online and dine-in orders" against "Dine-in only"), it carries the name of the list that says it.
        # An entry that names two days backs the other day's card as well, but there only what its own sentence about
        # both days says counts: "Dine-in only." after "On Tuesdays ..." is Tuesday's.
        mine, theirs = _list_name(kept), _list_name(r)
        kept.conditions = [f"{c}, says {mine} ({theirs} differs)" if own_day and _disputed(c, r.wording) else c
                           for c in kept.conditions]
        for c in (r.conditions if own_day else r.cue_conditions):
            if c != "limited time" and not any(k == c or k.startswith(c + ", says") for k in kept.conditions):
                kept.conditions.append(f"{c}, says {theirs} ({mine} differs)" if _disputed(c, kept.wording) else c)
    kept.link = kept.link or r.link
    have = {(e.url, e.quote[:60]) for e in kept.evidence}
    urls = {e.url for e in kept.evidence}
    for e in r.evidence:
        if e.url in urls and kept.origin == "list":
            continue                                   # the same list page on another weekday: one piece of evidence
        if (e.url, e.quote[:60]) not in have:
            kept.evidence.append(e)
            urls.add(e.url)


# --- registry entries -----------------------------------------------------------------------------------------------
def load_entries(path: Path) -> tuple[list[dict], str]:
    """(entries, error). A missing file is not an error."""
    if not path.exists():
        return [], ""
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError) as e:
        return [], f"could not be read: {e}"
    entries = data.get("regulars", []) if isinstance(data, dict) else data
    return (entries, "") if isinstance(entries, list) else ([], "expected a list of entries")


def from_entry(e: dict, venues: Venues, origin: str, today: date) -> Regular | str:
    """A regular deal from a registry entry or one of your own, or the reason it can't be used."""
    brand, offer = str(e.get("brand") or "").strip(), tidy(str(e.get("offer") or ""))
    if not brand or not offer:
        return "needs a brand and an offer"
    try:
        days, monthly = parse_days(e.get("days") or [])
    except ValueError as err:
        return str(err)
    if not days and not monthly:
        return "needs the days it runs on"
    windows, zone = time_windows(str(e.get("time") or ""))
    until = since = None
    try:
        until = date.fromisoformat(e["until"]) if e.get("until") else None
        since = date.fromisoformat(e["since"]) if e.get("since") else None
    except ValueError:
        return "dates must look like 2026-12-31"
    if until and until < today:
        return "past its stated end date"
    places = [p for p in (e.get("places") or []) if isinstance(p, dict)]
    chain = None if places else venues.find(str(e.get("venue") or brand))
    if not places and not chain:
        return "no mapped place: give `places` with an address, or a chain the map knows"
    # Terms the entry states outright are the whole truth; only an entry that states none is read from its wording.
    stated = any(e.get(k) is not None for k in ("bogo", "pct", "price", "summary"))
    terms = Terms(promo=True, basis="none") if stated else offer_terms(offer)
    if e.get("bogo"):
        label, eff = bogo_of(str(e["bogo"]))
        terms.bogo, terms.pct, terms.basis, terms.summary = label, eff, "store_regular", "BOGO" if "free" in label else label
    if e.get("pct") is not None:
        terms.pct, terms.basis, terms.hedge = float(e["pct"]), "store_regular", str(e.get("hedge") or "")
        terms.summary = (f"{terms.hedge} " if terms.hedge else "") + ("half price" if terms.pct == 50 else f"{terms.pct:g}% off")
    if e.get("price") is not None:
        terms.price = float(e["price"])
        terms.summary = terms.summary or _money(terms.price)
        if e.get("regular"):
            terms.regular = float(e["regular"])
            terms.savings = round(terms.regular - terms.price, 2)
            terms.pct, terms.basis = pct_off(terms.price, terms.regular), "store_regular"
    if e.get("summary"):
        terms.summary = str(e["summary"])
    kind = str(e.get("kind") or (chain.kind if chain else "restaurant"))
    inds = [str(i) for i in (e.get("industries") or [])] or \
        industries_for(chain, offer, KIND_INDUSTRIES.get(kind, ("dining",)))
    rid = str(e.get("id") or f"{fold(brand)[:24]}-{hashlib.sha1((brand + offer).encode()).hexdigest()[:8]}")
    conditions = [tidy(str(c)) for c in e["conditions"]] if "conditions" in e else regular_conditions(offer)
    return Regular(id=rid, brand=brand, offer=offer, chain=chain,
                   places=places, area=e.get("area"), schedule=Schedule(days, monthly, windows, zone, until, since),
                   terms=terms, industries=inds, origin=origin, conditions=conditions, kind=kind,
                   link=str(e.get("link") or ""), image_url=str(e.get("image") or ""), note=str(e.get("note") or ""),
                   absorbs=[str(a) for a in (e.get("absorbs") or [])], suppress=str(e.get("suppress") or ""),
                   exact_days=bool(e.get("exact_days")), site=str(e.get("site") or ""),
                   checks=list(e.get("evidence") or []))


_EXPIRES = re.compile(r"\bexpires?:?\s+(?:on\s+)?(?:(\d{1,2})/(\d{1,2})/(20\d\d)|"
                      r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{1,2}),?\s+(20\d\d))", re.I)


def _expiry_after(texts: Iterable[str], phrase: str, today: date) -> Optional[date]:
    """The expiry a page states right after an offer's own words: "Topping Tuesday ... VIEW COUPON Expires 10/19/2026".
    A weekly coupon carries a date that its page moves forward; Slomp shows the deal until the date on the page."""
    want = tidy(phrase).lower()
    for text in texts:
        low = text.lower()
        i = low.find(want)
        if i < 0:
            continue
        m = _EXPIRES.search(text, i + len(want), i + len(want) + 80)
        if m:
            try:
                if m.group(1):
                    return date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
                months = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")
                return date(int(m.group(6)), months.index(m.group(4)[:3].lower()) + 1, int(m.group(5)))
            except ValueError:
                return None
    return None


def logo_key(r: Regular) -> str:
    """How logos.json names a regular deal's chain or place."""
    return r.chain.key if r.chain else "place:" + fold(r.brand)


@lru_cache(maxsize=1)
def _logos() -> dict[str, dict]:
    path = DATA / "logos.json"
    return json.loads(path.read_text()).get("logos", {}) if path.exists() else {}


def check_key(url: str, find: list[str]) -> str:
    return hashlib.sha1((url + "\n" + "\n".join(find)).encode()).hexdigest()[:16]


class Regulars:
    def __init__(self, http: PoliteClient, db: DB, settings: Optional[Settings] = None,
                 venues: Optional[Venues] = None, registry: Optional[Path] = None):
        self.http, self.db = http, db
        self.settings = settings or Settings()
        self.venues = venues or Venues()
        self.roundups = Roundups(http)
        self.registry = registry or DATA / "regulars.json"
        self._set: Optional[RegularSet] = None
        self._lock = asyncio.Lock()

    # -- the statewide set ---------------------------------------------------------------------------------------
    async def all(self, refresh: bool = False, now: Optional[datetime] = None) -> RegularSet:
        """Every regular deal in the state with live evidence. Built at most every 6 hours; `refresh` rebuilds it now,
        re-reading every page instead of taking it from the cache."""
        if not refresh and self._set and clock.time() - self._set.built_at < SET_TTL_S:
            return self._set
        async with self._lock:
            if not refresh and self._set and clock.time() - self._set.built_at < SET_TTL_S:
                return self._set
            self._set = await self._build(not refresh, now or datetime.now().astimezone())
            return self._set

    async def _build(self, use_cache: bool, now: datetime) -> RegularSet:
        out = RegularSet(built_at=clock.time())
        today = now.date()
        found: list[Regular] = []

        entries, err = load_entries(self.registry)
        mine, my_err = load_entries(self.settings.regulars_path)
        for origin, rows in (("registry", entries), ("yours", mine)):
            for e in rows:
                r = from_entry(e, self.venues, origin, today)
                if isinstance(r, str):
                    out.excluded[f"regular deal ({'yours' if origin == 'yours' else 'registry'}): {r}"] += 1
                    continue
                found.append(r)
        await asyncio.gather(*(self._places(r) for r in found if r.places))
        await asyncio.gather(*(self._confirm(r, use_cache, now) for r in found if not r.suppress))
        # A registry entry whose own pages no longer back it steps aside before the lists are merged in: a list that
        # still carries the deal then shows it in the list's words, not under wording no page confirms any more.
        unbacked = [r for r in found if r.origin == "registry" and not r.suppress and not r.status]
        out.excluded["regular deal: no evidence recent enough to rely on"] += len(unbacked)
        found = [r for r in found if not any(r is u for u in unbacked)]

        listings, pages = await self.roundups.read(use_cache)
        for x in listings:
            if x.source == "edd":
                found += everyday_stops(x, self.venues, today)
            r = from_listing(x, self.venues, today)
            if isinstance(r, str):
                out.excluded[f"regular deal: {r}"] += 1
                continue
            if r.suppress:
                out.excluded[f"regular deal: {r.suppress}"] += 1
            r.evidence[0].checked_at = now
            found.append(r)

        for r in merge(found, out.excluded):
            if r.status:
                r.logo = _logos().get(logo_key(r)) or {}
                out.regulars.append(r)
            else:
                out.excluded["regular deal: no evidence recent enough to rely on"] += 1
        by_status = Counter(r.status for r in out.regulars)
        out.sources = pages + [
            {"name": "Regular deals registry", "ok": not err, "entries": len(entries),
             **({"error": err} if err else {}), **{k: by_status[k] for k in STATUS_ORDER if by_status[k]}},
            {"name": "Your regular deals", "ok": not my_err, "entries": len(mine), "path": str(self.settings.regulars_path),
             **({"error": my_err} if my_err else {})},
            {"name": self.venues.name, "ok": bool(self.venues.built()), "built": self.venues.built()}]
        return out

    async def _places(self, r: Regular) -> None:
        """Coordinates for places given by street address (the Census Bureau's geocoder; no key)."""
        for p in r.places:
            if p.get("lat") is not None and p.get("lon") is not None:
                continue
            addr = str(p.get("address") or "")
            try:
                resp = await self.http.get(f"{GEOCODER}?address={quote_plus(addr)}&benchmark=Public_AR_Current&format=json",
                                           ttl_s=TTL["geocode"])
                hit = (resp.json().get("result", {}).get("addressMatches") or [None])[0]
            except (FetchError, ValueError):
                hit = None
            if hit:
                p["lat"], p["lon"] = round(hit["coordinates"]["y"], 6), round(hit["coordinates"]["x"], 6)

    async def _confirm(self, r: Regular, use_cache: bool, now: datetime) -> None:
        if r.origin == "yours":
            r.evidence.append(Evidence("yours", "you", r.link, r.note, None, None, None, True))
        for spec in r.checks:
            ev = await self.check(spec, use_cache, now, r)
            r.evidence.append(ev)
            if ev.live and ev.until and (r.schedule.until is None or ev.until < r.schedule.until):
                r.schedule.until = ev.until

    async def check(self, spec: dict, use_cache: bool = True, now: Optional[datetime] = None,
                    r: Optional[Regular] = None) -> Evidence:
        """Read one evidence page and look for the words. The result is recorded, so the last successful read
        stands for a while when the page is briefly unreadable. A page that is read and no longer says it ends the
        deal at once (after three reads, for a page that said it before)."""
        now = now or datetime.now().astimezone()
        url, kind = str(spec.get("url") or ""), str(spec.get("kind") or "official")
        find = [str(p) for p in (spec.get("find") or [])]
        ev = Evidence(kind, str(spec.get("source") or host_of(url)), url)
        key = check_key(url, find)
        stated = date.fromisoformat(spec["dated"]) if spec.get("dated") else None
        if await self.http.turns_away_ai(url):
            # The registry is researched and kept up with an AI assistant's help. A site that tells such assistants to
            # keep out is not used as evidence, though the general rule would let Slomp's own reader in.
            ev.note = "the site's robots.txt turns away AI assistants, which help keep this registry"
            return ev
        try:
            resp = await self.http.get(url, ttl_s=TTL["evidence"], html=True, use_cache=use_cache)
            if resp.status != 200:
                raise FetchError(url, f"HTTP {resp.status}", resp.status)
        except Disallowed:
            ev.note = "the site's robots.txt does not allow reading this page"
        except Blocked:
            ev.note = "the site answered with a bot check"
        except FetchError as e:
            ev.note = e.reason
        else:
            page = resp.text
            ev.checked_at = datetime.fromtimestamp(resp.fetched_at).astimezone()
            texts = page_texts(page)
            ev.found, ev.quote = find_phrases(texts, find, int(spec.get("within", WITHIN)))
            for _ in range(2):
                # Some sites serve two versions of a page at random (Fuzzy's home page carries its promotions in one
                # and not the other). A miss is read again before it counts, where a hit is on record.
                if ev.found or kind not in ("official", "rewards") or not self.db.check_history(key):
                    break
                try:
                    again = await self.http.get(url, ttl_s=TTL["evidence"], html=True, use_cache=False)
                except FetchError:
                    break
                if again.status == 200:
                    page, resp = again.text, again
                    texts = page_texts(page)
                    ev.found, ev.quote = find_phrases(texts, find, int(spec.get("within", WITHIN)))
            if ev.found and spec.get("expires_after"):
                ev.until = _expiry_after(texts, str(spec["expires_after"]), now.date())
            if ev.found and spec.get("sold_out"):
                # A free day that needs a ticket can run out: "October 6 - SOLD OUT" on the zoo's own page.
                for k in range(9):
                    day = (now + timedelta(days=k)).date()
                    said = str(spec["sold_out"]).format(month=f"{day:%B}", mon=f"{day:%b}", day=day.day)
                    if find_phrases(texts, [said], 0)[0]:
                        ev.off.append(day.isoformat())
            ev.page_date = page_date(page) or stated
            if r is not None and ev.found and kind in ("official", "rewards") and not r.image_url:
                r.image_url = og_image(page)
            self.db.check_record(key, url, bool(ev.found), ev.page_date.isoformat() if ev.page_date else None, ev.quote,
                                 resp.fetched_at)
        history = self.db.check_history(key)
        last_hit = next((h for h in history if h["found"]), None)
        age = lambda t: (now.timestamp() - t) / 86400                                  # noqa: E731
        if kind in ("official", "rewards"):
            limit = LIVE_DAYS[kind]
            if ev.found:
                ev.live = age(ev.checked_at.timestamp()) <= limit
            elif ev.found is None and last_hit and age(last_hit["checked_at"]) <= limit:
                # unreadable today (a bot check, an outage): the last successful read still stands
                ev.live = True
                ev.quote = ev.quote or last_hit["quote"]
                ev.checked_at = datetime.fromtimestamp(last_hit["checked_at"]).astimezone()
                ev.note += "; last confirmed earlier"
            elif ev.found is False:
                # read (three times, where it had been found before) and the words are gone: the deal is not shown
                ev.note = "the page no longer says this"
        else:
            ev.page_date = ev.page_date or (date.fromisoformat(last_hit["page_date"]) if last_hit and
                                            last_hit["page_date"] else stated)
            if ev.found and ev.page_date:
                ev.live = (now.date() - ev.page_date).days <= LIVE_DAYS.get(kind, 180)
                if not ev.live:
                    ev.note = f"dated {ev.page_date:%b %-d, %Y}: too old to rely on"
            elif ev.found:
                ev.note = "the page carries no date, so its age is unknown"
            elif ev.found is False:
                ev.note = "the page no longer says this"
        return ev

    # -- one search ----------------------------------------------------------------------------------------------
    async def near(self, city: City, industries: list[str], radius_mi: float, start: datetime, end: datetime,
                   excluded: Counter, refresh: bool = False) -> tuple[list[LocalDeal], list[dict]]:
        rset = await self.all(refresh, start)
        excluded.update(rset.excluded)
        wanted = set(industries)
        tz = ZoneInfo(city.tz)
        out: list[LocalDeal] = []
        for r in rset.regulars:
            inds = [i for i in r.industries if i in wanted]
            if not inds:
                continue
            store = self.place(r, city)
            if not store or store.distance_mi > radius_mi:
                excluded["regular deal: no branch within the radius"] += 1
                continue
            dates = r.schedule.occurrences(start, end)
            if not dates:
                excluded["regular deal: does not run in the next 7 days"] += 1
                continue
            off = {d for e in r.evidence if e.live for d in e.off}
            dates = [d for d in dates if d.isoformat() not in off]
            if not dates:
                excluded["regular deal: its page says the coming date is sold out"] += 1
                continue
            out.append(self._deal(r, inds, store, dates, city, start, tz))
        out.sort(key=lambda d: (d.starts_in_days, -d.score, d.merchant, d.title))
        return out, rset.sources

    def place(self, r: Regular, city: City) -> Optional[Store]:
        if r.places:
            best: Optional[Store] = None
            for p in r.places:
                if p.get("lat") is None or p.get("lon") is None:
                    continue
                d = miles(city.lat, city.lon, float(p["lat"]), float(p["lon"]))
                if best is None or d < best.distance_mi:
                    best = Store(merchant=r.brand, name=str(p.get("name") or r.brand), lat=float(p["lat"]),
                                 lon=float(p["lon"]), address=str(p.get("address") or ""), distance_mi=round(d, 1),
                                 source="entry", ref=f"entry:{r.id}")
            return best
        return self.venues.nearest(r.chain, city, r.area) if r.chain else None

    @staticmethod
    def _deal(r: Regular, inds: list[str], store: Store, dates: list[date], city: City, start: datetime,
              tz: ZoneInfo) -> LocalDeal:
        first, last = dates[0], dates[-1]
        w = r.schedule.local_windows(first, tz)
        opens = min((a for a, _ in w if a), default=None) if w and all(a for a, _ in w) else None
        closes = max((b for _, b in w if b), default=None) if w and all(b for _, b in w) else None
        vf = max(start, datetime.combine(first, opens or time.min, tz))
        vt = datetime.combine(last, closes or time(23, 59, 59), tz)
        t = r.terms
        weight = BASIS_WEIGHT.get(t.basis, 0.0) * (0.5 if t.hedge else 1.0)
        t.conditions = list(r.conditions)
        status = r.status
        live = [e for e in r.evidence if e.live]
        lead = next((e for k in ("official", "rewards", "list", "article", "yours") for e in live if e.kind == k), None)
        return LocalDeal(
            id=f"regular:{r.id}", item_id=0, flyer_id=0, title=r.offer, merchant=r.brand, brand=r.brand,
            industries=inds, industry_rule=f"regular deal at a {r.kind}", category=r.kind, terms=t, valid_from=vf,
            valid_to=vt, source_url=(lead.url if lead else "") or r.link, retailer_url=r.link, image_url=r.image_url,
            store=store, store_status="nearby", score=round((t.pct or 0.0) * weight * r.weight, 2),
            starts_in_days=max(0, days_between(start, vf, city.tz)), ends_in_days=days_between(start, vt, city.tz),
            regular={"days": [DAY_KEYS[d] for d in sorted(set(r.schedule.days))], "monthly": r.schedule.monthly,
                     "days_text": r.schedule.days_text().replace("Every ", "Some ", t.hedge == "select weeks") +
                     ("s" if t.hedge == "select weeks" and len(r.schedule.days) == 1 else ""),
                     "time_text": r.schedule.time_text(first, tz),
                     "next": [d.isoformat() for d in dates],
                     "until": r.schedule.until.isoformat() if r.schedule.until else None,
                     "ends": closes.strftime("%H:%M") if closes else None,     # when its hours end on a day it runs
                     "logo": {"url": r.logo["url"], "fit": r.logo.get("fit", "contain")} if r.logo.get("url") else None,
                     "status": status, "status_text": status_text(r), "origin": r.origin, "kind": r.kind,
                     "note": r.note, "evidence": [e.to_dict() for e in r.evidence]},
            raw={"origin": r.origin})


def status_text(r: Regular) -> str:
    """How Slomp knows, in a few words: 'Confirmed on cinemark.com', 'Listed by 2 deal sites', 'Added by you'."""
    live = [e for e in r.evidence if e.live]
    s = r.status
    if s == "confirmed":
        e = next(e for e in live if e.kind in ("official", "rewards"))
        return f"Confirmed on {e.source}"
    if s == "listed":
        names = list(dict.fromkeys(e.source for e in live if e.kind == "list"))
        return f"Listed by {names[0]}" if len(names) == 1 else f"Listed by {len(names)} deal sites"
    if s == "reported":
        e = next(e for e in live if e.kind == "article")
        return f"Reported by {e.source}"
    return "Added by you" if s == "yours" else ""
