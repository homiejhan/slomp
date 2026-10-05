"""Live tests for regular deals. Like checks.py, each re-checks one result against a source through its own fetch
and its own reading of the page, never the pipeline's parser or its cached copy.

  R-SRC   the evidence page, fetched fresh, states this chain, this day and this offer
  R-X     another source (the other deal-site list) states the same offer, or contradicts it
  R-DAY   the dates shown are the dates a separate calendar computes
  R-GEO   the chain's own store locator (AllThePlaces) has a branch nearby, and the distance is right
  R-REC   a deal from an independently researched answer key is in Slomp's results
The two blind-judge tests (industry, faithful summary) are packets built here and labelled by a separate model run.
"""
from __future__ import annotations

import calendar
import html as htmllib
import json
import re
import urllib.parse
import urllib.request
from datetime import date, datetime, time, timedelta
from typing import Optional

from ..geo import miles
from ..http import Blocked, Disallowed, FetchError, PoliteClient
from ..local import LocalResult
from ..models import LocalDeal
from ..reference import fold
from ..sources import venues as venues_data
from ..sources.venues import Venues
from . import atp
from .checks import FAIL, INCONCLUSIVE, PASS, Verdict

DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
KEYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
# The other list's page for a weekday (Krazy Coupon Lady has no weekend pages).
LISTS = {
    "The Krazy Coupon Lady": {0: "monday-restaurant-deals", 1: "tuesday-meal-deals", 2: "wednesday-food-deals",
                              3: "thirsty-thursday-food-deals", 4: "friday-food-deals"},
    "EatDrinkDeals": {0: "daily-deals-monday-restaurant-specials-deals", 1: "daily-deals-tuesday-restaurant-specials",
                      2: "daily-deals-wednesday-restaurant-specials", 3: "daily-deals-thursday-restaurant-specials",
                      4: "daily-deals-friday-restaurant-specials", 5: "daily-deals-saturday-restaurant-specials",
                      6: "daily-deals-sunday-restaurant-specials"},
}
LIST_BASE = {"The Krazy Coupon Lady": "https://thekrazycouponlady.com/tips/money/{}",
             "EatDrinkDeals": "https://www.eatdrinkdeals.com/{}/"}
# Slomp's name for a chain -> its store-locator dataset at AllThePlaces.
ATP_SPIDERS = {
    "Schlotzsky's": "schlotzskys", "Sonic Drive-In": "sonic_drivein_us", "Buffalo Wild Wings": "buffalo_wild_wings_us",
    "AMC": "amc_theatres_us", "Cinemark": "cinemark", "Regal": "regal_theaters", "Topgolf": "topgolf_us",
    "Dave & Buster's": "dave_and_busters", "Chuck E. Cheese": "chuck_e_cheese", "Torchy's Tacos": "torchys_tacos_us",
    "Taco Cabana": "taco_cabana_us", "Fuzzy's Taco Shop": "fuzzys_taco_shop_us", "Wingstop": "wingstop",
    "Freebirds": "freebirds_us", "Burger King": "burger_king", "Wendy's": "wendys", "Main Event": "main_event",
    "Outback Steakhouse": "outback_steakhouse", "P.F. Chang's": "pf_changs", "Saltgrass Steak House":
    "saltgrass_steak_house_us", "Goodwill Central Texas": "goodwill", "Walgreens": "walgreens", "Savers": "savers_ca_us",
    "Jack in the Box": "jack_in_the_box", "Denny's": "dennys_us", "Applebee's": "applebees", "Chili's": "chilis",
    "Einstein Bros. Bagels": "einstein_bros_us", "Logan's Roadhouse": "logans_roadhouse_us", "Which Wich": "which_wich_us",
    "Panera Bread": "panera_bread_us", "Marco's Pizza": "marcos", "Papa Murphy's": "papa_murphys",
    "McCormick & Schmick's": "mccormick_and_schmicks_us", "Carrabba's Italian Grill": "carrabbas_italian_grill",
    "The Cheesecake Factory": "the_cheesecake_factory", "California Pizza Kitchen": "california_pizza_kitchen",
    "Quiznos": "quiznos", "Macaroni Grill": "macaroni_grill_us", "Buca di Beppo": "buca_di_beppo_us",
    "Rosa's Café": "rosas_cafe_us", "B&B Theatres": "bb_theatres_us", "Kona Grill": "kona_grill_us",
    "Shake Shack": "shake_shack", "Golden Corral": "golden_corral", "Texas Roadhouse": "texas_roadhouse",
    "Dickey's Barbecue Pit": "dickeys_barbecue_pit", "Ross Dress for Less": "ross_dress_for_less_us", "KFC": "kfc_us",
    "Pizza Hut": "pizza_hut_us", "Taco Bell": "taco_bell_us", "Red Lobster": "red_lobster_us", "Chuy's": "chuys_us",
    "Cracker Barrel": "cracker_barrel_us", "Baskin-Robbins": "baskin_robbins_us", "Smoothie King":
    "smoothie_king_ky_us_tt", "Ruth's Chris Steak House": "ruths_chris_steak_house_us", "Yard House": "yard_house",
    "Cheddar's": "cheddars_scratch_kitchen", "Olive Garden": "olive_garden",
    "Whole Foods Market": "whole_foods", "Hopdoddy Burger Bar": "hopdoddy_burger_bar_us", "Famous Dave's": "famous_daves_us",
    "Bonefish Grill": "bonefish_grill", "Del Taco": "del_taco_us", "IKEA": "ikea", "Village Inn": "village_inn_us",
    "Moe's Southwest Grill": "moes_southwest_grill", "Beef O'Brady's": "beef_o_bradys", "Black Bear Diner":
    "black_bear_diner_us", "Morton's The Steakhouse": "mortons_the_steakhouse_us", "Grimaldi's Pizzeria":
    "grimaldis_pizzeria", "Huddle House": "huddle_house_us", "Sbarro": "sbarro",
}
GEOCODER = "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"
UA = {"User-Agent": "Mozilla/5.0 (compatible; Slomp/1.0)"}


# --- reading a page, independently of the pipeline -----------------------------------------------------------------
def simple(text: str) -> str:
    t = (text or "").lower()
    for a, b in (("’", "'"), ("‘", "'"), ("“", '"'), ("”", '"'), ("–", "-"), ("—", "-"), ("−", "-"), (" ", " ")):
        t = t.replace(a, b)
    return re.sub(r"\s+", " ", t)


def everything(page: str) -> str:
    """All the words on a page: the visible text, then the strings inside its script data."""
    body = re.sub(r"<(script|style|noscript)[^>]*>.*?</\1>", " ", page, flags=re.S | re.I)
    visible = htmllib.unescape(re.sub(r"<[^>]+>", " ", body))
    data = []
    for m in re.finditer(r"<script[^>]*>(.*?)</script>", page, re.S | re.I):
        for s in re.findall(r'"((?:[^"\\]|\\.){15,900})"', m.group(1)):
            if " " not in s:
                continue
            try:
                s = json.loads(f'"{s}"')
            except ValueError:
                pass
            data.append(re.sub(r"<[^>]+>", " ", s))
    return simple(visible + " ‖ " + htmllib.unescape(" ".join(data)))


async def fresh(http: PoliteClient, url: str, ttl_s: float = 60, use_cache: bool = False) -> tuple[Optional[str], str]:
    try:
        r = await http.get(url, ttl_s=ttl_s, html=True, use_cache=use_cache)
    except Disallowed:
        return None, "robots.txt"
    except Blocked:
        return None, "bot check"
    except FetchError as e:
        return None, e.reason
    return (r.text, "") if r.status == 200 else (None, f"HTTP {r.status}")


def lead(d: LocalDeal) -> Optional[dict]:
    """The live evidence Slomp leans on most: the company's page, else a list, else an article."""
    live = [e for e in d.regular["evidence"] if e["live"] and e["url"]]
    for kind in ("official", "rewards", "list", "article"):
        for e in live:
            if e["kind"] == kind:
                return e
    return None


def facts(d: LocalDeal) -> dict:
    """What the card claims, read from its own words: amounts, percents, buy-one-get-one, and a few content words."""
    title = simple(d.title)
    amounts = sorted(set(re.findall(r"\$\d+(?:\.\d{2})?", title)))
    percents = sorted(set(re.findall(r"\d{1,2}%", title)))
    half = bool(re.search(r"\bhalf[- ]?(?:priced?|off)\b|\b1/2[- ]?(?:priced?|off)\b", title))
    bogo = bool(d.terms.bogo) or bool(re.search(r"\bbogo\b|\bbuy one\b", title))
    brand = {w for w in re.findall(r"[a-z]{3,}", simple(d.merchant))}
    stop = brand | set(DAYS) | {x + "s" for x in DAYS} | set(
        "the and for with every from your you get all day free off price priced half deal deals special specials offer "
        "members rewards order online app when that this are has have its can per plus each week only until after "
        "night happy hour valid available enjoy grab score any more than about most also".split())
    words = [w for w in dict.fromkeys(re.findall(r"[a-z]{4,}", title)) if w not in stop]
    return {"amounts": amounts, "percents": percents, "half": half, "bogo": bogo, "words": words[:8]}


def day_words(d: LocalDeal) -> list[str]:
    r = d.regular
    if r["monthly"]:
        kind, n = r["monthly"].split(":")
        if kind == "d":
            return [f"{n}st", f"{n}nd", f"{n}rd", f"{n}th"]
        return [DAYS[int(n)]]
    days = [KEYS.index(k) for k in r["days"]]
    out = [DAYS[k] for k in days]
    if len(days) >= 4:
        out += ["weekday", "daily", "every day", "everyday", "mon-", "monday-", "monday through", "mon -", "monday -",
                "sun-", "sunday-", "sunday through", "sunday to"]
    return out


_GENERIC = {"the", "and", "of", "cafe", "café", "bar", "grill", "restaurant", "restaurants", "steakhouse", "steak", "house",
            "kitchen", "pizza", "tacos", "taco", "shop", "subs", "coffee", "bagels", "deli", "cinema", "theatres", "wing",
            "drive", "in", "bros", "burgers", "lounge", "place", "museum", "art", "brewhouse"}


def brand_keys(name: str, loose: bool = False) -> list[str]:
    """Ways a page may spell the chain: the full name, and its first distinctive word. `loose` also takes a short
    first word ("BJ's"), for matching a heading or the start of a list item, where little else can match."""
    full = simple(name)
    words = [w for w in re.findall(r"[a-z0-9']+", full.replace(".", "")) if w not in _GENERIC]
    keys = [full, full.replace("'", ""), full.replace("-", " "), full.replace(".", "")]
    if words and (len(words[0]) >= 5 or (loose and len(words[0]) >= 3)):
        keys.append(words[0])
    return list(dict.fromkeys(k for k in keys if len(k) >= 3))


def entries(page: str, name: str) -> list[str]:
    """The chain's own entries on a list page: list items that begin with its name ("Chain: sentence"), and
    sections under a heading that carries its name, each up to the next heading."""
    keys = brand_keys(name, loose=True)
    strip = lambda x: simple(htmllib.unescape(re.sub(r"<[^>]+>", " ", x)))                      # noqa: E731
    body = re.sub(r"<(script|style|noscript)[^>]*>.*?</\1>", " ", page, flags=re.S | re.I)
    out = []
    for block in re.findall(r"<li[^>]*>(.*?)</li>", body, re.S | re.I):
        text = strip(block)
        head, colon, _ = text[:80].partition(":")
        if colon and any(k in head for k in keys):
            out.append(text)
    for sec in re.split(r"<h2[^>]*>", body)[1:]:
        if "</h2>" in sec:
            head, rest = sec.split("</h2>", 1)
            if any(k in strip(head) for k in keys):
                out.append(strip(head) + ": " + strip(rest)[:3000])
    return out


def windows(text: str, needles: list[str], pad: int = 520, before: Optional[int] = None) -> list[str]:
    """The text around each place a needle occurs: `before` characters ahead of it (default `pad`) and `pad` after."""
    out = []
    lead_in = pad if before is None else before
    for n in needles:
        for m in re.finditer(re.escape(n), text):
            out.append(text[max(0, m.start() - lead_in):m.end() + pad])
            if len(out) >= 60:
                return out
    return out


_ENDS = re.compile(r"\b(?:through|thru|until|ends?|expires?)\s+(?:(?:mon|tues|wednes|thurs|fri|satur|sun)day,?\s+)?"
                   r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{1,2})(?:,?\s*(20\d\d))?")
_MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")


def ended(passage: str, today: date) -> Optional[date]:
    """An end date the passage states that has already passed ("through Sept. 30" read in October)."""
    last = None
    for m in _ENDS.finditer(passage):
        years = [int(m.group(3))] if m.group(3) else [today.year - 1, today.year, today.year + 1]
        near = None
        for y in years:                                          # no year given: the one that puts it nearest today
            try:
                d = date(y, _MONTHS.index(m.group(1)) + 1, int(m.group(2)))
            except ValueError:
                continue
            near = d if near is None or abs((d - today).days) < abs((near - today).days) else near
        if near:
            last = near if last is None or near > last else last
    return last if last and last < today else None


def sentences_of(passage: str) -> list[str]:
    return [x.strip() for x in re.split(r"(?<=[.!?])\s+", passage) if len(x.strip()) > 12]


def has_facts(passage: str, f: dict) -> list[str]:
    """Which of the card's claims a passage does not contain."""
    # "$6" is not "$6.75", but "$1" is "$1.00"
    missing = [a for a in f["amounts"] if not re.search(re.escape(a) + r"(?:\.00)?(?!\d|\.\d)", passage)]
    missing += [p for p in f["percents"] if p not in passage and not (p == "50%" and re.search(r"half|1/2", passage))]
    if f["half"] and not re.search(r"half|1/2|50 ?%", passage):
        missing.append("half price")
    if f["bogo"] and not re.search(r"\bbogo\b|buy (?:one|1|a|an|any)\b|get (?:one|1|another)|two for one|2 for 1", passage):
        missing.append("buy one get one")
    return missing


def one_schedule(text: str) -> bool:
    """The page names at most two weekdays (one day, or one "Monday - Friday" span): it is about a single schedule."""
    return len({x for x in DAYS if re.search(rf"\b{x}s?\b", text)}) <= 2


async def regular_source(http: PoliteClient, d: LocalDeal) -> Verdict:
    """The evidence page, read now with this module's own reader, states the chain, a day it runs on, and every
    amount, percent and buy-one-get-one the card shows."""
    e = lead(d)
    if not e:
        return INCONCLUSIVE, {"why": "your own entry: there is no page to re-read"}
    page, err = await fresh(http, e["url"])
    if page is None:
        return INCONCLUSIVE, {"why": f"evidence page unreadable now ({err})", "url": e["url"]}
    text = everything(page)
    f, days = facts(d), day_words(d)
    detail = {"url": e["url"], "kind": e["kind"], "claims": {k: v for k, v in f.items() if v and k != "words"},
              "days": d.regular["days_text"]}
    if e["kind"] == "list":
        head = simple(" ".join(re.findall(r"<title[^>]*>(.*?)</title>|<h1[^>]*>(.*?)</h1>", page, re.S | re.I)[0])) \
            if re.search(r"<title|<h1", page, re.I) else ""
        weekend = "friday" in head and "krazycoupon" in e["url"] and set(d.regular["days"]) <= {"sat", "sun"}
        if not weekend and not any(DAYS[KEYS.index(k)] in head for k in d.regular["days"]):   # the Friday page lists weekends
            return FAIL, {**detail, "why": f"the list page is not for a day this runs on (page: {head[:70]!r})"}
        spots = entries(page, d.merchant)
        if not spots:
            return FAIL, {**detail, "why": "the list page no longer has an entry for this chain"}
        good = [w for w in spots if not has_facts(w, f)]
        if not good:
            best = min((has_facts(w, f) for w in spots), key=len)
            return FAIL, {**detail, "why": f"the chain's entry on the page lacks {best}"}
        # An end date inside the entry's sentence about this offer that has passed.
        over = []
        for w in good:
            mine = [x for x in sentences_of(w) if not has_facts(x, {**f, "bogo": False, "half": False}) or len(sentences_of(w)) == 1]
            over.append(next((ended(x, datetime.now().date()) for x in mine if ended(x, datetime.now().date())), None))
        if all(over):
            return FAIL, {**detail, "why": f"the page says it ended {over[0]:%b %-d}"}
        return PASS, detail
    # A company page or an article: the claims and a day must sit together (and, in an article, with the place's name).
    anchors = f["amounts"] + f["percents"] + (["bogo", "buy one"] if f["bogo"] else []) + (["half"] if f["half"] else [])
    anchors = anchors or [w for w in ("free", "happy hour", "discount", "special") if w in simple(d.title)] or f["words"][:2]
    if e["kind"] == "article":
        # A guide lists many places: read from where it names this one, to the end of that place's passage.
        spots = windows(text, brand_keys(d.merchant), pad=700, before=120)
        if not spots:
            return FAIL, {**detail, "why": "the article does not name this place"}
    else:
        spots = windows(text, anchors, pad=700)
    ok = [w for w in spots if not has_facts(w, f) and any(x in w for x in days)]
    for _ in range(3):
        # Some company sites serve two versions of a page at random (Fuzzy's home page carries its promotions in one
        # and not in the other): read it again, up to three more times, before failing.
        if ok or e["kind"] == "article":
            break
        again, _ = await fresh(http, e["url"])
        if again is not None:
            text = everything(again)
            spots = windows(text, anchors, pad=700)
            ok = [w for w in spots if not has_facts(w, f) and any(x in w for x in days)]
            detail["reads"] = detail.get("reads", 1) + 1
    if not spots:
        return FAIL, {**detail, "why": f"the page has none of {anchors}"}
    if ok:
        return PASS, detail
    if e["kind"] != "article" and one_schedule(text) and not has_facts(text, f) and any(x in text for x in days):
        # A page about one promotion may give its day once, far from the terms: Walgreens' Seniors Day page says
        # "20%" some 2,900 characters before "the first Tuesday". With one schedule on the page that is unambiguous.
        return PASS, {**detail, "whole_page": True}
    with_facts = [w for w in spots if not has_facts(w, f)]
    why = "the claims are on the page but no day this runs on is near them" if with_facts else \
        f"no passage has all of the claims; closest lacks {min((has_facts(w, f) for w in spots), key=len)}"
    return FAIL, {**detail, "why": why}


async def regular_cross(http: PoliteClient, d: LocalDeal) -> Verdict:
    """Does a source Slomp did not use for this deal state the same offer? The other deal-site list for that day is
    read, sentence by sentence within the chain's entry. The same item at a different price is a conflict."""
    used = {e["source"] for e in d.regular["evidence"] if e["live"]}
    official = any(e["kind"] in ("official", "rewards") and e["live"] for e in d.regular["evidence"])
    f = facts(d)
    stated = bool(f["amounts"] or f["percents"] or f["bogo"] or f["half"])
    days = [KEYS.index(k) for k in d.regular["days"]]
    if not days:
        return INCONCLUSIVE, {"why": "a monthly deal: the weekday lists don't cover it"}
    need = max(2, (len(f["words"]) + 1) // 2)            # shared content words that make two sentences the same item
    looked, conflict = [], None
    for site, pages in LISTS.items():
        if site in used:
            continue
        for day in days[:3]:
            if day not in pages:
                continue
            page, _ = await fresh(http, LIST_BASE[site].format(pages[day]), ttl_s=1800, use_cache=True)   # once a run
            if page is None:
                continue
            looked.append(f"{site} {DAYS[day]}")
            for w in entries(page, d.merchant):
                sents = sentences_of(w)
                for i, sent in enumerate(sents):
                    shared = [x for x in f["words"] if x in sent or x.rstrip("s") in sent]
                    block = sent + " " + (sents[i + 1] if i + 1 < len(sents) else "")
                    if stated and shared and not has_facts(block, f):
                        return PASS, {"agrees": f"{site} ({DAYS[day]} page)", "their_words": sent[:200]}
                    if not stated and len(shared) >= need:
                        return PASS, {"agrees": f"{site} ({DAYS[day]} page)", "their_words": sent[:200]}
                    theirs = set(re.findall(r"\$\d+(?:\.\d{2})?", sent))
                    if f["amounts"] and theirs and len(shared) >= need and not set(f["amounts"]) & theirs:
                        conflict = {"site": f"{site} ({DAYS[day]} page)", "shows": f["amounts"], "theirs": sorted(theirs),
                                    "their_words": sent[:200]}
    if conflict and not official:
        return FAIL, {"why": "another list gives a different price for the same item", **conflict}
    if conflict:
        return INCONCLUSIVE, {"why": "a list disagrees with the company's page; Slomp shows the company's figure", **conflict}
    return INCONCLUSIVE, {"why": "no other source covers this offer", "looked_at": looked}


# --- the calendar ----------------------------------------------------------------------------------------------------
_CLOCK = r"(noon|midnight|\d{1,2}(?::\d{2})?(?: ?[ap]m)?)"


def _clock(text: str, half: str = "") -> Optional[time]:
    if text == "noon":
        return time(12, 0)
    if text == "midnight":
        return time(23, 59)
    m = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?(?: ?([ap])m)?", text)
    ap = m.group(3) or half
    return time(int(m.group(1)) % 12 + (12 if ap == "p" else 0), int(m.group(2) or 0))


def shown_windows(time_text: str) -> list[tuple[Optional[time], Optional[time]]]:
    """Slomp's own wording for hours, read back: 'after 5 pm', 'until 4 pm', '2–5 pm', '11 am–9 pm'."""
    out = []
    for part in (time_text or "").split(" and "):
        part = part.strip()
        m = re.fullmatch(r"after " + _CLOCK, part)
        if m:
            out.append((_clock(m.group(1)), None))
            continue
        m = re.fullmatch(r"until " + _CLOCK, part)
        if m:
            out.append((None, _clock(m.group(1))))
            continue
        m = re.fullmatch(_CLOCK + "–" + _CLOCK, part)
        if m:
            end = _clock(m.group(2))
            half = "a" if end.hour < 12 else "p"
            out.append((_clock(m.group(1), half), end))
    return out


def regular_schedule(d: LocalDeal, res: LocalResult) -> Verdict:
    """The dates shown are exactly the dates in the window on which the stated days fall, minus a day whose hours are
    already over (today) or have not begun when the window closes (the last day), minus days past the end date."""
    r = d.regular
    start, end = res.window_start, res.window_end
    days = {KEYS.index(k) for k in r["days"]}
    until = date.fromisoformat(r["until"]) if r["until"] else None
    hours = shown_windows(r["time_text"])
    if r["time_text"] and not hours:
        return INCONCLUSIVE, {"why": f"could not read the hours back: {r['time_text']!r}"}
    expect, cur = [], start.date()
    while cur <= end.date():
        if r["monthly"]:
            kind, n = r["monthly"].split(":")
            if kind == "d":
                on = cur.day == int(n)
            elif int(kind) == -1:
                on = cur.weekday() == int(n) and cur.day + 7 > calendar.monthrange(cur.year, cur.month)[1]
            else:
                on = cur.weekday() == int(n) and (cur.day - 1) // 7 + 1 == int(kind)
        else:
            on = cur.weekday() in days
        if on and until and cur > until:
            on = False
        if on and hours and cur == start.date() and all(b and b <= start.time() for _, b in hours):
            on = False
        if on and hours and cur == end.date() and all(a and a >= end.time() for a, _ in hours):
            on = False
        if on:
            expect.append(cur.isoformat())
        cur += timedelta(days=1)
    issues = []
    if expect != r["next"]:
        issues.append(f"dates: calendar says {expect}, shown {r['next']}")
    if r["next"] and d.starts_in_days != (date.fromisoformat(r["next"][0]) - start.date()).days:
        issues.append(f"starts in {d.starts_in_days} days, but the first date is {r['next'][0]}")
    if r["next"] and (d.valid_from.date().isoformat() != r["next"][0] or d.valid_to.date().isoformat() != r["next"][-1]):
        issues.append(f"valid {d.valid_from.date()} to {d.valid_to.date()} does not span {r['next'][0]} to {r['next'][-1]}")
    if not (start <= d.valid_to and d.valid_from <= end):
        issues.append("outside the 7-day window")
    detail = {"days": r["days_text"], "hours": r["time_text"], "next": r["next"], "now": start.isoformat(timespec="minutes")}
    return (PASS, detail) if not issues else (FAIL, {**detail, "issues": issues})


# --- the place -------------------------------------------------------------------------------------------------------
def _geocode(address: str) -> Optional[tuple[float, float]]:
    q = urllib.parse.urlencode({"address": address, "benchmark": "Public_AR_Current", "format": "json"})
    with urllib.request.urlopen(urllib.request.Request(f"{GEOCODER}?{q}", headers=UA), timeout=40) as r:
        hits = json.load(r)["result"]["addressMatches"]
    return (hits[0]["coordinates"]["y"], hits[0]["coordinates"]["x"]) if hits else None


def regular_vicinity(d: LocalDeal, city_lat: float, city_lon: float, radius_mi: float) -> Verdict:
    """The branch shown is within the radius, its distance is right, and a source other than Slomp's map agrees it is
    there: the chain's own store locator, or for a single place the Census geocoder on its address."""
    st = d.store
    again = miles(city_lat, city_lon, st.lat, st.lon)
    detail = {"branch": st.name, "address": st.address, "shown_mi": st.distance_mi, "recomputed_mi": round(again, 2)}
    if abs(again - st.distance_mi) > 0.11:
        return FAIL, {**detail, "why": "the distance shown is wrong"}
    if st.distance_mi > radius_mi:
        return FAIL, {**detail, "why": f"beyond the {radius_mi:g}-mile radius"}
    if st.source == "entry":
        try:
            hit = _geocode(st.address)
        except Exception as e:
            return INCONCLUSIVE, {**detail, "why": f"geocoder unavailable ({type(e).__name__})"}
        if not hit:
            return INCONCLUSIVE, {**detail, "why": "the geocoder does not know this address"}
        off = miles(hit[0], hit[1], st.lat, st.lon)
        return (PASS, {**detail, "geocoder_offset_mi": round(off, 2)}) if off <= 0.3 else \
            (FAIL, {**detail, "why": f"the address geocodes {off:.1f} mi from the point used"})
    spider = ATP_SPIDERS.get(d.merchant)
    pts = atp._spider_points(spider) if spider else None
    if not pts:
        return INCONCLUSIVE, {**detail, "why": "no independent store list for this chain"}
    chain = Venues().find(d.merchant)
    mapped = len(venues_data._chains(False)[0][chain.key].locations) if chain else 0     # closed branches included
    if len(pts) < 0.8 * mapped:
        # Some locator scrapes are partial (14 Jack in the Box branches near Texas against 504 on the map).
        return INCONCLUSIVE, {**detail, "why": f"the chain's store list looks incomplete ({len(pts)} near Texas against "
                                               f"{mapped} on the map)"}
    nearest_branch = min(miles(st.lat, st.lon, p[0], p[1]) for p in pts)
    nearest_city = min(miles(city_lat, city_lon, p[0], p[1]) for p in pts)
    detail.update(locator=spider, locator_nearest_to_branch_mi=round(nearest_branch, 2),
                  locator_nearest_to_city_mi=round(nearest_city, 1))
    if nearest_branch <= 0.75:
        return PASS, detail
    return FAIL, {**detail, "why": "the chain's own locator lists no branch where Slomp shows one"}


# --- recall ----------------------------------------------------------------------------------------------------------
def key_days(item: dict) -> tuple[set[int], str]:
    days, monthly = set(), ""
    for raw in item.get("days") or []:
        s = raw.lower().strip()
        if s.startswith("monthly"):
            monthly = s
        elif s in ("daily", "every day"):
            days |= set(range(7))
        elif s == "weekdays":
            days |= {0, 1, 2, 3, 4}
        elif s in ("weekends", "weekend"):
            days |= {5, 6}
        elif s[:3] in KEYS:
            days.add(KEYS.index(s[:3]))
    return days, monthly


_RECALL_STOP = set(DAYS) | {x + "s" for x in DAYS} | set(
    "every with from their they this that when your have each only also more than into over about most some after "
    "before until through during plus available valid offer offers deal deals special specials posted location "
    "locations purchase price priced regular items item menu order orders night nights week weekly".split())


def offer_tokens(text: str) -> set[str]:
    """The words and figures that say what an offer is, for telling one deal at a place from another."""
    t = simple(text).replace("1/2", "half").replace("50%", "half")
    t = re.sub(r"\bbuy (?:one|1),? get (?:one|1)\b", "bogo", t)
    out = {w.rstrip("s") for w in re.findall(r"[a-z]{4,}", t) if w not in _RECALL_STOP}
    return out | set(re.findall(r"\d+(?:\.\d\d)?", t))


def regular_recall(item: dict, regulars: list[LocalDeal], venues: Venues, today: date,
                   held: list[tuple[str, str, set, str]] = ()) -> Verdict:
    """A deal a local would expect, from an answer key researched without sight of Slomp's data: is it in Slomp's
    results for that metro? The place, a shared day and something of the offer itself must match. `held` lists deals
    Slomp knows within the radius but is not showing (brand, offer, weekdays, monthly rule): no date in the next 7
    days, or a date its page marks sold out. Absent counts as a fail, with the reason."""
    detail = {"key": f"{item['brand']}: {item.get('offer', '')[:110]}", "days": item.get("days"), "url": item.get("url")}
    dated = item.get("page_date") or ""
    if item.get("kind") != "official" and dated[:4].isdigit():
        try:
            if (today - date.fromisoformat(dated[:10])).days > 180:
                return INCONCLUSIVE, {**detail, "why": "the answer key's own source is over 180 days old"}
        except ValueError:
            pass
    want_days, monthly = key_days(item)
    name = fold(item["brand"])
    chain = venues.find(item["brand"])
    is_it = lambda brand: (fold(brand) == name or name in fold(brand) or fold(brand) in name or      # noqa: E731
                           (chain is not None and fold(chain.name) == fold(brand)))
    want = offer_tokens(item.get("offer", ""))
    same = [d for d in regulars if is_it(d.merchant)]
    on_day = [d for d in same if (monthly and d.regular["monthly"]) or
              (want_days & {KEYS.index(k) for k in d.regular["days"]})]
    best = max(on_day, key=lambda d: len(want & offer_tokens(d.title)), default=None)
    if best is not None and want & offer_tokens(best.title):
        return PASS, {**detail, "slomp": f"{best.merchant}: {best.title[:90]} ({best.regular['days_text']})",
                      "shared": sorted(want & offer_tokens(best.title))[:6]}
    for brand, offer, days, rule in held:
        if is_it(brand) and ((monthly and rule) or (want_days & days)) and want & offer_tokens(offer):
            return PASS, {**detail, "slomp": f"{brand}: {offer[:90]}",
                          "note": "in Slomp's data; not shown this week (no date in the next 7 days, or sold out)"}
    if same:
        return FAIL, {**detail, "why": "Slomp has this place, but not this deal or not on these days",
                      "slomp_has": [f"{d.title[:60]} ({d.regular['days_text']})" for d in same[:4]]}
    if chain is None and item.get("scope") == "chain":
        return FAIL, {**detail, "why": "the chain is not on Slomp's map"}
    return FAIL, {**detail, "why": "not in the registry and not on the deal-site lists Slomp reads" if chain or
                  item.get("scope") == "chain" else "a local place Slomp has no entry for"}


# --- packets for the blind judge -------------------------------------------------------------------------------------
OTHER_PAGE = " ‖ [another page the app cites] "


async def source_passage(http: PoliteClient, d: LocalDeal) -> str:
    """What the pages a card cites say about its deal, for a judge to compare with the card. A card can rest on more
    than one page (a location page for the hours and a menu page for the offer; two deal sites' lists), so each live
    page gives a passage, the one Slomp leans on first, up to three."""
    order = {"official": 0, "rewards": 0, "list": 1, "article": 2}
    parts, seen = [], set()
    for e in sorted((e for e in d.regular["evidence"] if e["live"] and e["url"]), key=lambda e: order.get(e["kind"], 3)):
        if e["url"] in seen or len(parts) >= 3:
            continue
        seen.add(e["url"])
        best = ""
        for attempt in range(3):             # a page served in two versions: read again when the claims are missing
            page, _ = await fresh(http, e["url"], ttl_s=1800, use_cache=attempt == 0)
            got = _passage(page, d, e) if page is not None else ""
            if got and (not best or len(has_facts(got, facts(d))) < len(has_facts(best, facts(d)))):
                best = got
            if best and not has_facts(best, facts(d)) or e["kind"] != "official":
                break
        if best:
            parts.append(best)
    return OTHER_PAGE.join(parts)


def _passage(page: str, d: LocalDeal, e: dict) -> str:
    """One page's passage: the chain's entry (a list), the place's passage (an article), or the page around the claims."""
    text, f = everything(page), facts(d)
    if e["kind"] == "list":
        # A weekday list gives each entry's day in its title, not in the entry: the judge needs both.
        spots = sorted((w[:900] for w in entries(page, d.merchant)), key=lambda w: len(has_facts(w, f)))
        return f"[from the list page titled: {heading(page)}] {spots[0].strip()}" if spots else ""
    visible = text.split(" ‖ ")[0]
    if e["kind"] != "article" and len(visible) <= 7000 and not has_facts(visible, f) and \
            any(w in visible for w in f["words"][:3] or [simple(d.merchant)]):
        return visible.strip()               # a short company page, whole: its conditions can sit far from the offer
    # (a page whose words live in its script data, such as BJ's, falls through to the passages around the claims)
    anchors = f["amounts"] + f["percents"] + (["bogo", "buy one"] if f["bogo"] else []) + f["words"][:3]
    near = windows(text, brand_keys(d.merchant), pad=620, before=80) if e["kind"] == "article" else \
        windows(text, anchors, pad=520)
    # Where on a long page to look: the words Slomp itself quotes from it, found again in this fresh read. (Uchi's menu
    # page is 25,000 characters; its happy-hour tasting is one line of it.)
    # The pointer must be words the page has once: "see Sunday for details." is on a guide twelve times.
    quoted = simple(e.get("quote") or "").strip("… ")
    pieces = (quoted[i:i + 40] for i in range(0, max(1, len(quoted) - 30), 12))
    pointer = [q for q in pieces if len(q) >= 24 and text.count(q) == 1][:2]
    near = windows(text, pointer, pad=620, before=260) + near
    names = brand_keys(d.merchant)[:1] if e["kind"] == "article" else []
    spots = sorted(near, key=lambda w: (len(has_facts(w, f)), -any(q in w for q in pointer), -any(k in w for k in names),
                                        -sum(x in w for x in f["words"])))
    if not spots:
        return "" if e["kind"] == "article" else text[:7000].strip()      # nothing to anchor on: the top of the page
    parts = [spots[0].strip()]
    # A long page may state the offer's terms in a block of its own ("Winning Wednesday ... VIEW COUPON Expires
    # 10/19/2026 ... Limit one use per transaction"): the block under the offer's name, the one with the most terms.
    name = simple(d.title.split(":")[0]) if ":" in d.title[:45] else ""
    if len(name) >= 8:
        blocks = sorted(windows(text, [name], pad=640, before=20),
                        key=lambda w: -sum(k in w for k in ("expires", "limit", "valid", "only", "participating")))
        if blocks and not any(blocks[0][:120] in p for p in parts):
            parts.append(blocks[0].strip())
    for c in d.terms.conditions:             # ...and on a long page, the words around each condition the card states
        for w in re.findall(r"[a-z]{5,}", simple(c)):
            i = text.find(w)
            if i >= 0 and not any(text[max(0, i - 40):i + 40] in p for p in parts):
                parts.append(text[max(0, i - 200):i + 300].strip())
                break
    return " … ".join(parts)


def heading(page: str) -> str:
    m = re.search(r"<h1[^>]*>(.*?)</h1>", page, re.S | re.I) or re.search(r"<title[^>]*>(.*?)</title>", page, re.S | re.I)
    return simple(htmllib.unescape(re.sub(r"<[^>]+>", " ", m.group(1)))).strip() if m else ""
