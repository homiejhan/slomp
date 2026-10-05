"""Day-of-week roundups: pages where deal editors list restaurant chains' standing offers, one page per weekday.

  The Krazy Coupon Lady   Monday to Friday. Two lists per page, "Limited-Time ..." and "Every-...", one item per
                          chain: `Chain: sentence`. The Friday page adds "Weekend Food Deals".
  EatDrinkDeals           all seven days. A heading per chain, then paragraphs that often describe the chain's
                          whole week, so only the sentences that name the page's day are kept. A chain's bulleted
                          list ("Thursdays - Turkey n' Dressing $9.99 lunch") gives one entry per item for that day.

Both sites allow automated readers in robots.txt, and every page states when it was last modified. A page is the
editors' reading of the chains' own announcements: good for finding regular deals, checked against company pages by
the verification harness.
"""
from __future__ import annotations

import asyncio
import html as htmllib
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional
from urllib.parse import urlsplit

from ..config import TTL
from ..http import FetchError, PoliteClient
from ..schedule import DAY_NAMES, weekdays_in

MIN_ENTRIES = 5             # fewer than this from a page means its layout changed: report it, don't trust it
KCL = "https://thekrazycouponlady.com/tips/money/"
EDD = "https://www.eatdrinkdeals.com/"
PAGES: tuple[tuple[str, int, str], ...] = (
    ("kcl", 0, KCL + "monday-restaurant-deals"), ("kcl", 1, KCL + "tuesday-meal-deals"),
    ("kcl", 2, KCL + "wednesday-food-deals"), ("kcl", 3, KCL + "thirsty-thursday-food-deals"),
    ("kcl", 4, KCL + "friday-food-deals"),
    ("edd", 0, EDD + "daily-deals-monday-restaurant-specials-deals/"),
    ("edd", 1, EDD + "daily-deals-tuesday-restaurant-specials/"),
    ("edd", 2, EDD + "daily-deals-wednesday-restaurant-specials/"),
    ("edd", 3, EDD + "daily-deals-thursday-restaurant-specials/"),
    ("edd", 4, EDD + "daily-deals-friday-restaurant-specials/"),
    ("edd", 5, EDD + "daily-deals-saturday-restaurant-specials/"),
    ("edd", 6, EDD + "daily-deals-sunday-restaurant-specials/"),
)
SOURCE_NAMES = {"kcl": "The Krazy Coupon Lady", "edd": "EatDrinkDeals"}


@dataclass
class Listing:
    source: str                 # "kcl" | "edd"
    url: str                    # the roundup page
    day: int                    # the page's weekday, 0 = Monday
    brand: str                  # the chain as the page spells it
    text: str                   # what the page says about it for that day
    section: str                # "every" | "limited" | "weekend"
    modified: Optional[date]    # when the page says it was last modified
    brand_url: str = ""         # the chain's own site, when the entry links to it
    context: str = ""           # the paragraph that introduces a bulleted list this entry is an item of

    @property
    def source_name(self) -> str:
        return SOURCE_NAMES[self.source]


def _text(fragment: str) -> str:
    return re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def _body(page: str) -> str:
    return re.sub(r"<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", page, flags=re.S | re.I)


def page_modified(page: str) -> Optional[date]:
    """The page's own last-modified date (schema.org `dateModified`, else the Open Graph tag)."""
    m = re.search(r'"dateModified"\s*:\s*"(\d{4}-\d{2}-\d{2})', page) or \
        re.search(r'property="article:modified_time"\s+content="(\d{4}-\d{2}-\d{2})', page)
    try:
        return date.fromisoformat(m.group(1)) if m else None
    except ValueError:
        return None


def _outbound(fragment: str, own_host: str) -> str:
    for href in re.findall(r'href="(https?://[^"]+)"', fragment):
        host = urlsplit(href).netloc.lower().removeprefix("www.")
        if host and own_host not in host and not re.search(r"facebook|instagram|twitter|x\.com|tiktok|apple\.com|"
                                                           r"google\.com|youtube", host):
            return htmllib.unescape(href)
    return ""


_KCL_ITEM = re.compile(r"^([^:]{2,60}?)\s*:\s*(\S.{15,})$", re.S)


def parse_kcl(page: str, day: int, url: str) -> list[Listing]:
    modified = page_modified(page)
    out: list[Listing] = []
    section = ""
    for tag, inner in re.findall(r"<(h2|h3|li)[^>]*>(.*?)</\1>", _body(page), flags=re.S | re.I):
        if tag.lower() != "li":
            head = _text(inner).lower()
            section = ("limited" if "limited-time" in head else "weekend" if head.startswith("weekend") else
                       "every" if head.startswith("every") else "")
            continue
        if not section:
            continue
        m = _KCL_ITEM.match(_text(inner))
        if not m:
            continue
        brand = re.sub(r"\s*\([^)]*\)\s*$", "", m.group(1)).strip()          # "Buffalo Wild Wings (B'Dubs)"
        if re.search(r"\d", brand) and re.search(r"(?i)\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)", brand):
            continue                                                         # a date where the chain should be
        text = m.group(2).strip()
        # "Weekend Food Deals" sit on the Friday page: each belongs to the Saturday and/or Sunday it names.
        days = ([d for d in weekdays_in(text) if d >= 5] or [5, 6]) if section == "weekend" else [day]
        out += [Listing("kcl", url, d, brand, text, section, modified, _outbound(inner, "krazycoupon")) for d in days]
    return out


_EDD_SKIP_HEAD = re.compile(r"\?|deals going|you may also|related|comment|newsletter|subscribe|leave a reply|"
                            r"more restaurant|search|categories|recent posts", re.I)
_EDD_FILLER = re.compile(r"^(?:for (?:more|info|details)|check out|click here|visit our|see our|you can (?:see|find|view)|"
                         r"to (?:see|view|find)|read our|want other|don.t have the app|they sent|more details)", re.I)


# A sentence that restricts the offer before it rather than stating another: "You can only get the special for dine-in
# orders", "You'll need to be signed into your account", "The offer is valid all day at the bar".
QUALIFIES = re.compile(r"\b(?:the|this) (?:special|deal|offer|discount|promotion|promo|bogo|freebie|coupon)\b|"
                       r"^(?:you(?:'ll| will| must| need| have to)\b|must\b|requires?\b|valid\b|available\b|"
                       r"good (?:for|at|on)\b|offer (?:is )?(?:valid|good|available)\b|only\b|"
                       r"not (?:valid|available)\b|limit\b|redeem\b|order\b|use\b|enter\b|mention\b|show\b|present\b|"
                       r"sign\b|at checkout\b|fine print\b|one \w+(?: \w+)? per\b|"
                       r"(?:dine[- ]in|in[- ]store|in[- ]app|app|online|(?:rewards )?members?) only\b)|"
                       r"\b(?:promo|coupon) code\b|\bminimum \$\d", re.I)
_OTHER_OFFER = re.compile(r"\balso (?:has|have|offers?|get)\b", re.I)
_HOW_KNOWN = re.compile(r"\b(?:announced|posted|spotted|shared)\b", re.I)     # "The chain announced the special on Facebook."

_NO_BREAK = re.compile(r"(?:\b[A-Z]|\b[ap]\.m|\b(?:St|Jr|Sr|Dr|Mr|Mrs|Ms|vs|No|Inc|Co|approx|reg|oz|lb|lbs|pc|pcs|ct|"
                       r"Sept|Oct|Nov|Dec|Jan|Feb|Aug))\.$")


def tidy_quotes(text: str) -> str:
    return text.replace("’", "'").replace("‘", "'")


def sentences(text: str) -> list[str]:
    """Split at sentence ends, not at initials or abbreviations ("Chuck E. Cheese", "P.F. Chang's", "5 p.m. Tuesday")."""
    out: list[str] = []
    for part in re.split(r"(?<=[.!?])\s+(?=[A-Z“\"'$\d])", text):
        if out and _NO_BREAK.search(out[-1]):
            out[-1] += " " + part
        elif part.strip():
            out.append(part.strip())
    return out


def parse_edd(page: str, day: int, url: str) -> list[Listing]:
    modified = page_modified(page)
    out: list[Listing] = []
    for sec in re.split(r"<h2[^>]*>", _body(page))[1:]:
        if "</h2>" not in sec:
            continue
        head, rest = sec.split("</h2>", 1)
        brand = _text(head)
        if not brand or len(brand) > 45 or _EDD_SKIP_HEAD.search(brand):
            continue
        kept: list[str] = []
        link = _outbound(rest, "eatdrinkdeals")
        # A bulleted list of days, and the paragraph before it: "these deals are good only for Prime members".
        intro = ""
        for para, items in re.findall(r"<p[^>]*>(.*?)</p>|<ul[^>]*>(.*?)</ul>", rest, flags=re.S | re.I):
            if para:
                intro = _text(para)
                continue
            for item in re.findall(r"<li[^>]*>(.*?)</li>", items, flags=re.S | re.I):
                text = _text(item)
                if 12 <= len(text) <= 400 and day in weekdays_in(text, every_day=False):
                    out.append(Listing("edd", url, day, brand, text, "every", modified, link, intro))
        lead = ""
        for para in re.findall(r"<p[^>]*>(.*?)</p>", rest, flags=re.S | re.I):
            sents = sentences(_text(para))
            lead = lead or (sents[0] if sents else "")
            gap = 99                               # sentences since the last one kept in this paragraph
            for i, s in enumerate(sents):
                if _EDD_FILLER.match(s):
                    continue
                if day in weekdays_in(s):
                    kept.append(s)
                    gap = 99 if _OTHER_OFFER.search(s) else 0      # nothing follows on from "Sonic also has ..."
                    continue
                gap += 1
                if weekdays_in(s) or _OTHER_OFFER.search(s):
                    gap = 99                       # another day's offer, or another offer: what follows is not ours
                elif gap == 1 and len(s) <= 70:
                    kept.append(s)                 # a short follow-on: "Dine-in only."
                    gap = 0
                elif gap <= 3 and len(s) <= 220 and QUALIFIES.search(tidy_quotes(s)) and not _HOW_KNOWN.search(s):
                    kept.append(s)                 # a restriction a sentence or two on: "Redeem online or in the app ..."
                    gap = 0
        if kept:
            # The section's opening sentence can say who the deals are for ("IKEA Family members can enjoy ...").
            out.append(Listing("edd", url, day, brand, " ".join(dict.fromkeys(kept))[:700], "every", modified, link,
                               "" if lead in kept else lead))
    return out


PARSERS = {"kcl": parse_kcl, "edd": parse_edd}


class Roundups:
    def __init__(self, http: PoliteClient):
        self.http = http

    async def read(self, use_cache: bool = True) -> tuple[list[Listing], list[dict]]:
        """Every listing on every page, and one status row per page for the response's `sources`."""
        async def one(source: str, day: int, url: str) -> tuple[list[Listing], dict]:
            name = f"{SOURCE_NAMES[source]}: {DAY_NAMES[day]}"
            try:
                r = await self.http.get(url, ttl_s=TTL["roundup"], html=True, use_cache=use_cache)
            except FetchError as e:
                return [], {"name": name, "ok": False, "error": e.reason, "url": url}
            if r.status != 200:
                return [], {"name": name, "ok": False, "error": f"HTTP {r.status}", "url": url}
            found = PARSERS[source](r.text, day, r.final_url or url)
            row = {"name": name, "ok": len(found) >= MIN_ENTRIES, "entries": len(found), "url": r.final_url or url,
                   "modified": found[0].modified.isoformat() if found and found[0].modified else None,
                   "read": datetime.fromtimestamp(r.fetched_at).astimezone().isoformat(timespec="minutes")}
            if len(found) < MIN_ENTRIES:
                row["error"] = "the page's layout may have changed: too few entries found"
                found = []
            return found, row
        results = await asyncio.gather(*(one(*p) for p in PAGES))
        return [x for found, _ in results for x in found], [row for _, row in results]
