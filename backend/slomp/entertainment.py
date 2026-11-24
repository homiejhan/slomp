"""Entertainment bought online: subscriptions to watch, listen and play, and tickets, passes and memberships for
places to go. docs/DESIGN-online-stores.md 4.6 has the design.

Movies & Entertainment was discount days at places near you and nothing else. In Black Friday week of 2026 a search by
hand found 30 entertainment offers; 15 were subscriptions and 9 were tickets, passes and memberships, and Slomp showed
none: its sales are at stores that ship, so it left subscriptions and tickets out by design. They are listed now, on
the Sales tab under Movies & Entertainment, each marked for what it is.

What is one is the source's to say, not a list of services': dealnews files these posts under Streaming Services,
Movie Tickets and Things to Do, and Slomp reads those three feeds for them. A post from a site that gives no category
is one only when its title says so in plain words ("... Streaming Service Plan $1/Month", "Movie Ticket Offer").
Gift cards stay out, as everywhere in Slomp, and so does anything for one group of people (students, the military).

A place's own sale on its tickets is on no deal site, so the second half of this module reads the places' own pages:
slomp/data/venue_pages.json says where each sells its tickets, and what is on sale comes from the page, in its words.
"""
from __future__ import annotations

import asyncio
import html as htmllib
import json
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Optional
from urllib.parse import urljoin, urlsplit

from . import days
from .models import StoreSale
from .reference import DATA, norm
from .sources.feeds import ADDRESS, SOURCE_NAMES, FeedPlan, Post, dealnews_url, written_name
from .stores_online import _straight, store_named
from .terms import clean, post_reference

ENTERTAINMENT = "entertainment"
SUBSCRIPTION, TICKETS = "subscription", "tickets"
# dealnews' categories for them (and every category under these): the feed Slomp reads, and what its posts are.
CATEGORIES = {1183: SUBSCRIPTION, 654: TICKETS, 333: TICKETS}      # Streaming Services, Movie Tickets, Things to Do
FEEDS = tuple(FeedPlan("dealnews", f"dealnews c{cid} {what}", dealnews_url(cid), [ENTERTAINMENT])
              for cid, what in ((1183, "streaming services"), (654, "movie tickets"), (333, "things to do")))


@lru_cache(maxsize=1)
def _leaves() -> dict[str, str]:
    """dealnews' leaf category -> what a post under it is ("Video Streaming Services" is under Streaming Services)."""
    cats = json.loads((DATA / "dealnews_categories.json").read_text())["categories"]
    out: dict[str, str] = {}
    for cid, kind in CATEGORIES.items():
        root = cats[str(cid)]["path"]
        for v in cats.values():
            if v["path"] == root or v["path"].startswith(root + "/"):
                out[norm(v["leaf"])] = kind
    return out


# A title that says so itself, for a site that gives no category (Slickdeals, Hip2Save): a streaming service priced by
# the month or called a subscription, and tickets, admission or a pass to somewhere.
_MONTHLY = r"(?:\$\s?\d[\d,.]*|\d+\s?¢)\s*(?:/|\s+per\s+|\s+a\s+)\s*mo(?:nth)?\b"
_SAYS_STREAMING = re.compile(r"\bstreaming\b(?=.*(?:" + _MONTHLY + r"|\bsubscriptions?\b))|"
                             r"(?:" + _MONTHLY + r"|\bsubscriptions?\b).*\bstreaming\b", re.I)
_SAYS_TICKETS = re.compile(r"\b(?:movie|event|concert|theat(?:er|re)|theme[- ]park|amusement[- ]park|zoo|museum|aquarium)s?"
                           r"(?:/\w+)?\s+tickets?\b|\bseason pass(?:es)?\b|\bannual pass(?:es)?\b|\badmission\b", re.I)


# A video game's "season pass" is more of the game, not a pass to somewhere.
_A_GAME = re.compile(r"\bdigital\b|\bdownload\b|\bdlc\b|\bxbox\b|\bplaystation\b|\bps[45]\b|\bnintendo\b|\bsteam\b|\bpc\b", re.I)


def kind_of(p: Post) -> str:
    """"subscription", "tickets", or "" for a post that is neither."""
    if p.source == "dealnews" and p.category:
        return _leaves().get(norm(p.category), "")          # dealnews says what its post is
    title = _straight(p.title)
    if _SAYS_STREAMING.search(title):
        return SUBSCRIPTION
    return TICKETS if _SAYS_TICKETS.search(title) and not _A_GAME.search(title) else ""


# --- what is offered ----------------------------------------------------------------------------------------------
_PER = r"\s*(?:/|\s+per\s+|\s+a\s+)\s*(mo(?:nth)?|yr|year)\b\.?"
_BY_TERM = re.compile(r"(\bfrom\s+)?\$\s?(\d[\d,]*(?:\.\d\d)?)" + _PER, re.I)                # "$5.49/month", "From $2.99/mo."
_NUMBER = r"(\d+|one|two|three|four|five|six|twelve)"
_FOR_TERM = re.compile(r"\bfor\s+(?:the\s+)?(?:first\s+)?" + _NUMBER + r"[- ](month|year)s?\b", re.I)   # "for 12 months"
_LEAD_TERM = re.compile(r"\b" + _NUMBER + r"[- ](month|year)s?\b", re.I)                    # "6-Month Membership for $45"
_ONE_PRICE = re.compile(r"(?:\bfor|\bjust|\bonly|:)\s+(from\s+)?\$\s?(\d[\d,]*(?:\.\d\d)?)(?![\d.,+])(?!\s?(?:off\b|/|per\b|a\s+mo))",
                        re.I)
_FREE = re.compile(r":\s*free\b|\bfor\s+free\b|\bfree\s+(?:trial|w/|with|to\s+claim)\b|^\W*free\b|\$0\b", re.I)
_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "twelve": 12}
# What makes a post under Streaming Services a subscription and not a film to buy: it is priced by the month or year,
# or says what it is.
_A_TERM = re.compile(_PER + r"|\b(?:\d+|one|two|three|six|twelve)[- ](?:month|year)s?\b|\bannual\b|\bsubscriptions?\b|"
                     r"\bplans?\b|\bmemberships?\b|\btrial\b|\bpass(?:es)?\b|\bchannels?\b", re.I)
_SHIPPED = re.compile(r"(?<!no )\bshipping\b|\bshipped\b|\bs&h\b", re.I)
# The regular price as dealnews words it, beside the ways terms.post_reference reads.
_REGULAR = re.compile(r"\bregular(?:ly)?\s+(?:price\s+(?:of\s+)?)?\$\s?(\d[\d,]*(?:\.\d\d)?)|\bdown\s+from\s+\$\s?(\d[\d,]*(?:\.\d\d)?)|"
                      r"\bthen\s+\$\s?(\d[\d,]*(?:\.\d\d)?)\s+(?:per|a)\s+month\b|\bgoes\s+up\s+to\s+\$\s?(\d[\d,]*(?:\.\d\d)?)", re.I)
_PCT_SAID = re.compile(r"\b(?:takes?|is|are|knocks?|cuts?)\s+(\d{1,2})% off\b", re.I)
_NEW = re.compile(r"\bnew\s*(?:(and|&|or|/)\s*(?:returning|former|eligible|lapsed)\s+)?(?:subscribers?|customers?|users?|members?)\b", re.I)


def _n(word: str) -> int:
    return int(word) if word.isdigit() else _WORDS.get(word.lower(), 0)


def _usd(v: float) -> str:
    return f"${v:,.2f}".replace(".00", "")


def offer_of(p: Post) -> tuple[str, str, Optional[float], Optional[float], str]:
    """(the offer in words, its badge, the price, the percent it saves when the post gives the regular price, the
    sentence that gives it). ("", ...) when the title states no price, no discount and nothing free. A percent or
    dollars off is read as for any sale (the price is None then; `offer` keeps its parts)."""
    from .sales import _SHIP_TAIL, offer_text, parse_offer, rank_pct
    title = _SHIP_TAIL.sub("", _straight(p.title))
    text = clean(p.text)[:600]
    m, price, words, badge = _BY_TERM.search(title), None, "", ""
    if m:
        price, unit = float(m.group(2).replace(",", "")), "month" if m.group(3).lower().startswith("mo") else "year"
        lead = "From " if m.group(1) else ""
        term = _FOR_TERM.search(title, m.end()) or _FOR_TERM.search(text)
        words = f"{lead}{_usd(price)} a {unit}" + (f" for {_n(term.group(1))} {term.group(2).lower()}s" if term and _n(term.group(1)) > 1
                                                     else f" for a {term.group(2).lower()}" if term else "")
        badge = f"{lead}{_usd(price)}/{'mo' if unit == 'month' else 'yr'}"
    else:
        m = _ONE_PRICE.search(title)
        if m:
            price, lead = float(m.group(2).replace(",", "")), "From " if m.group(1) else ""
            term = _LEAD_TERM.search(title[:m.start()])
            words = f"{lead}{_usd(price)}" + (f" for {_n(term.group(1))} {term.group(2).lower()}{'s' if _n(term.group(1)) > 1 else ''}"
                                               if term and _n(term.group(1)) else "")
            badge = f"{lead}{_usd(price)}"
    if price == 0:
        return "Free", "Free", 0.0, None, ""
    if price is not None:
        ref, _, said = post_reference(p.text, price)
        if not ref:
            r = _REGULAR.search(text)
            ref = float(next(g for g in r.groups() if g).replace(",", "")) if r else None
            said = _sentence_of(text, r) if r else ""
        if ref and ref > price * 1.02:
            return f"{words}, regularly {_usd(ref)}", badge, price, round(100 * (1 - price / ref), 1), said
        r = _PCT_SAID.search(text[:320])                 # "Prime Video takes 75% off STARZ subscriptions ..."
        if r:
            return f"{words}, {r.group(1)}% off", badge, price, float(r.group(1)), _sentence_of(text, r)
        return words, badge, price, None, ""
    o = parse_offer(p.title)
    if o.any:
        words, badge, _ = offer_text(o)
        return words, badge, None, rank_pct(o), ""
    if _FREE.search(title):
        return "Free", "Free", 0.0, None, ""
    return "", "", None, None, ""


def name_of(title: str) -> str:
    """What is offered, in the title's own words without the price: "Disney+, Hulu, & HBO Max Bundle (No Ads)". The
    seller's name stays: it is often the service's ("Peacock Black Friday Subscription Deals" at Peacock TV)."""
    from .sales import sale_name
    t = re.sub(r":\s*free\b.*$|\s+for\s+free\b.*$", "", sale_name(title, None, ""), flags=re.I).strip(" ,:")
    return t + ")" if t.count("(") > t.count(")") else t


def _sentence_of(text: str, m: re.Match) -> str:
    start = max(text.rfind(". ", 0, m.start()), text.rfind("! ", 0, m.start())) + 1
    ends = [i for i in (text.find(". ", m.end()), text.find("! ", m.end())) if i >= 0]
    return text[start:min(ends) + 1 if ends else len(text)].strip()[:220]


def conditions_of(p: Post) -> list[str]:
    """Who the offer is for and what it is, where the title or the post's first words say."""
    said = _straight(f"{p.title}. {clean(p.text)[:300]}")
    from .sales import conditions_of as sale_conditions, parse_offer
    out = [c for c in sale_conditions(parse_offer(p.title), clean(p.title), p.text) if not c.startswith("on orders")]
    m = _NEW.search(said)
    if m:
        out.append("new or returning subscribers" if m.group(1) else "new subscribers")
    if re.search(r"\bw/\s*ads\b|\bwith\s+ads\b|\bad-supported\b", _straight(p.title), re.I):
        out.append("with ads")
    return [c for c in dict.fromkeys(out) if c != "new customers" or not m]


def offer(p: Post, kind: str, now: datetime, excluded: Counter) -> Optional[StoreSale]:
    """One post as an entertainment offer, or None with the reason counted in `excluded`."""
    from .sales import (CENTRAL, POSTED_DAYS, UNDATED_DAYS, _DEAL_SITES, _NOT_SALE, _SHIP_TAIL, Offer, _end_of, code_of,
                        days, find_store, parse_offer, sale_dates)
    title = _straight(p.title)
    goods = _SHIP_TAIL.sub("", title)
    for rx, why in _NOT_SALE:
        if why in ("a gift card", "a credit card offer", "a discount for a group of people", "a giveaway", "an auction") \
                and rx.search(goods):
            excluded[f"entertainment: {why}"] += 1
            return None
    if kind == TICKETS and _SHIPPED.search(title):
        excluded["entertainment: goods that ship, not a ticket"] += 1       # a roll of paper tickets, a board game
        return None
    words, badge, price, pct, said = offer_of(p)
    if not words:
        excluded["entertainment: no price or discount stated"] += 1
        return None
    if kind == SUBSCRIPTION and price is not None and not _A_TERM.search(title):
        excluded["entertainment: not a subscription"] += 1      # one price or free, and no term: a film to buy, a free channel
        return None
    seller = "" if _DEAL_SITES.match((p.seller or "").strip()) else clean(p.seller or "")
    store = store_named(seller) if seller else find_store(p)[0]
    if not store and ADDRESS.fullmatch(seller):
        # A seller the registry doesn't know, given as its web address ("disneyplus.com"): the post writes its name
        # beside it, and that is what a card shows. Failing that the address stays.
        seller = written_name(_straight(p.text), seller) or seller
    name = store.name if store else seller
    if not name:
        excluded["entertainment: seller not named"] += 1
        return None
    starts, ends, ends_how = sale_dates(p, now)
    posted = (p.posted_at or now).astimezone(CENTRAL).date()
    day = days.day_of(title, posted)
    through = _end_of(day[1]) if day and not ends and not days.BEFORE.search(title) else None
    if ends and ends < now:
        excluded["sale: ended"] += 1
        return None
    if p.posted_at and now - p.posted_at > timedelta(days=POSTED_DAYS):
        excluded[f"sale: posted over {POSTED_DAYS} days ago"] += 1
        return None
    if not ends and (not p.posted_at or now - p.posted_at > timedelta(days=UNDATED_DAYS)) and not (through and now <= through):
        excluded[f"sale: no end date and posted over {UNDATED_DAYS} days ago"] += 1
        return None
    code, code_note, code_conditions = code_of(p.title, p.text, store, posted, now.astimezone(CENTRAL).date())
    o = parse_offer(p.title) if price is None else Offer()         # a percent or dollars off keeps its parts, as a sale's
    conditions = conditions_of(p) + [c for c in code_conditions if c != "the code is for new customers"]
    shown = clean(p.title)
    return StoreSale(
        id=f"sale:{p.id}", store=store.key if store else "", store_name=name, title=shown, name=name_of(shown),
        offer=words, badge=badge, badge_soft=badge.startswith("From ") or badge.startswith("Up to"), what=kind, code=code,
        pct=o.pct, upto=o.upto, extra=o.extra, extra_upto=o.extra_upto, off=o.off, off_upto=o.off_upto, min_spend=o.min_spend,
        bogo=o.bogo, bogo_pct=o.bogo_pct,
        code_note=code_note, conditions=list(dict.fromkeys(conditions)), starts_at=starts, ends_at=ends, ends_how=ends_how,
        event=day[0] if day else "", event_ends_at=through, offer_how=f"the post says “{said}”" if said else "",
        posted_at=p.posted_at, source=SOURCE_NAMES.get(p.source, p.source), source_url=p.url, image_url=p.image,
        industries=[ENTERTAINMENT],
        industry_rule=f"dealnews: {p.category}" if p.source == "dealnews" and p.category else "the title says what it is",
        discount_pct=pct, score=round(pct or 0.0, 2), raw={"feeds": p.feeds, "store_how": "the post's seller", "text": p.text[:1500]})


# --- a venue's own page ----------------------------------------------------------------------------------------------
# A place's own sale on its tickets, passes and memberships is on no deal site: in Black Friday week of 2026 Six Flags
# Over Texas, SeaWorld San Antonio, Texas Tides and two zoos each ran one, and only their own pages said so. So Slomp
# reads those pages itself. slomp/data/venue_pages.json says where a venue sells its tickets; what the offer is comes
# from the page, each build, in the page's words. A page that states no saving shows nothing.
#
# The hard part is telling a sale from a perk. The same pages list what a pass holder gets ("10% off in our Cafe",
# "20% off admission for friends and family who visit with you"), and read as one run of words a perk sits right
# beside the next pass's name. So a page is read block by block, as it is laid out: a heading, a tile's label, a
# paragraph are each a line, and what a percent is off is settled by its own line and the lines touching it.
_BLOCK = re.compile(r"</?(?:p|div|li|ul|ol|h[1-6]|section|article|header|footer|nav|main|aside|table|tr|td|th|br|button|form|"
                    r"label|figure|figcaption|blockquote|dl|dt|dd|hr|title|option|summary|details|caption)\b[^>]*>", re.I)
_PASS_WORD = r"(?:tickets?|pass(?:es)?|memberships?)"
_PASS = re.compile(r"\b" + _PASS_WORD + r"\b", re.I)
# A saving as a percent: "Save up to 55% on Tickets, Passes and More!", "50% Off Texas Annual Pass". A perk is often
# worded otherwise ("20% Food and Beverage Discount") and then never comes up.
_SAVING = re.compile(r"\bsave\s+(up\s?to\s+)?(\d{1,2})\s?%|\b(up\s?to\s+)?(\d{1,2})\s?%\s+off\b", re.I)
# What the percent is off, when the line goes on to say and it is the ticket: "off Texas Annual Pass", "on Tickets,
# Passes and More", "off * a membership". A few words may come between, but none that turns the ticket into the way
# to get the saving ("10% off select items with your pass").
_ON_IT = re.compile(r"\s*(?:off\s+)?(?:on\s+)?(?:[*+]\s*)?((?:(?!(?:with|for|at|in|to|when|using|by|per|and)\b)[\w'’&+-]+,?\s+){0,4}?"
                    + _PASS_WORD + r")\b", re.I)
# ... or the line says nothing about what it is off ("Black Friday: Save up to 50%", "20% off + 2 free months",
# "15% off for a limited time"), and the ticket is named beside it.
_BARE = re.compile(r"\s*(?:$|[!.*+|,;:–—-]|(?:for a limited time|today|now|during|this|ends?|through|until|when you|"
                   r"with (?:promo )?code|online)\b)", re.I)
# A line that names a ticket, as a tile's label does: "Single-Day Ticket", "SeaWorld 2027 Season Pass (1 Park)".
_NAMED = re.compile(r"\b(?:Tickets?|Pass(?:es)?|Memberships?|Admission|TICKETS?|PASS(?:ES)?|MEMBERSHIPS?|ADMISSION)\b")
# The ticket's own name: the capitalized words that end at it ("Texas Annual Pass", "Portal Passes").
_ITS_NAME = re.compile(r"((?:[A-Z0-9][\w'’&+-]*\s+){1,4}(?:Tickets?|Pass(?:es)?|Memberships?))\b")
# Not the visitor's own ticket: one for whoever a pass holder brings, or the second of two.
_NOT_OURS = re.compile(r"\bfriends?\b|\bguests?\b|\bbring-a-friend\b|\bwho visit with you\b|\bwhen visiting with\b|"
                       r"\b(?:second|2nd|additional|extra|companion)\b", re.I)
# Half off the second ticket is a quarter off two, and a page's headline may still call it "up to 50% off tickets".
_TWO_FOR = re.compile(r"\bbuy\s+one\b|\bbogo\b|\b(?:second|2nd)\b", re.I)
# Not everyone's: an offer for one group of people, or what a member or pass holder gets.
_ONE_GROUP = re.compile(r"\b(?:military|first responders?|veterans?|seniors?|students?|teachers?|educators?|groups?|"
                        r"(?:members?|pass\s?holders?|pass members?)\s+(?:\w+\s+){0,2}(?:save|enjoy|receive|get)|"
                        r"as an? (?:\w+\s+)?(?:member|pass\s?holder))\b", re.I)
# A list of what a pass or membership comes with says so above it.
_COMES_WITH = re.compile(r"\b(?:benefits?|perks?|includes?|included)\b", re.I)
# What a percent is off of when it is a perk and not the ticket.
_PERK = re.compile(r"\b(?:food|beverages?|dining|drinks?|meals?|retail|merchandise|gift shop|shop(?:ping)?|parking|photos?|"
                   r"cabanas?|lockers?|birthday|parties|camps?|classes|strollers?|rentals?|tours?|encounters?|hotel|rooms?|spa|"
                   r"caf[eé]|restaurants?|concessions?|products?|items|purchases?)\b", re.I)
# A price for one, where the page is speaking of a sale: "Get a 2027 Silver Pass for $69. Ends 11/27." A price by the
# month is a payment plan.
_FOR_PRICE = re.compile(r"\b((?:\d{4}\s+)?(?:[A-Z][\w'’-]*\s+){0,3}(?:Pass(?:es)?|Tickets?|Memberships?))\s+(?:for|as\s+low\s+as|from|"
                        r"starting\s+at)\s+(?:just\s+|only\s+)?\$\s?(\d[\d,]*(?:\.\d\d)?)(?!\d|[.,]\d|\s*(?:/|per\b|a\s+mo|each\b|monthly))")
_SALE_CUE = re.compile(r"\b(?:sale|deals?|limited[- ]time|special offers?|offer ends|ends\s+\d|(?:now\s+)?through\s+(?:\w+\.?\s+)?\d)\b", re.I)
_PRICES = re.compile(r"\s*(?:\$\s?[\d,]+(?:\.\d\d)?\s*){1,2}$")              # a tile's was and now: "$145.99 $59.99"
_YEAR = re.compile(r"\b(20\d\d)\b")
_SAYS_WHEN = re.compile(r"\b(?:ends?|through|thru|until|expires?|valid)\b", re.I)     # the line under an offer, dating it
_STOP = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")                               # a sentence ends: not at "Nov. 30" or "$3.89"
# A link on a venue's page worth following: its sale's own page, named for a day or for what it is.
_SALE_PATH = re.compile(r"black-?friday|cyber-?(?:monday|week)|(?:memorial|labor|presidents|veterans|mothers|fathers)-?day|"
                        r"fourth-of-july|(?<![a-z])(?:deals?|offers?|sales?|specials?|promotions?)(?![a-z])", re.I)
_NOT_THAT_PATH = re.compile(r"group|military|student|teacher|birthday|dining|drinks?|food|corporate|hotel|meal|camp|feed\b|"
                            r"events?|packages?|spa\b|fitness|locals?\b", re.I)
FOLLOW = 3                 # how many sale pages of a venue are read beside the ones listed
LONG = 200                 # a line longer than this is a paragraph: its sentences are read one by one
_KINDS = (("membership", "Memberships"), ("pass", "Passes"), ("ticket", "Tickets"))


@dataclass
class PageOffer:
    """One saving a venue's page states."""
    pct: Optional[float] = None
    upto: bool = False
    price: Optional[float] = None
    thing: str = ""                      # the ticket's own name, when the page gives one: "2027 Silver Pass"
    kind: str = ""                       # what it is, when it has no name: "Memberships"
    said: str = ""                       # the page's words
    around: str = ""                     # those words with the heading over them: where the sale is named and dated


@lru_cache(maxsize=1)
def venue_pages() -> list[dict]:
    return json.loads((DATA / "venue_pages.json").read_text())["venues"]


def page_lines(page: str) -> list[str]:
    """The text a visitor sees, a line for each block of the page: a heading, a tile's label, a paragraph."""
    from .regulars import page_texts, tidy
    body = re.sub(r"<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", page, flags=re.S | re.I)
    body = re.sub(r"<[^>]+>", " ", _BLOCK.sub("\n", body))
    lines = [ln for ln in (tidy(htmllib.unescape(ln)) for ln in body.split("\n")) if ln]
    if sum(map(len, lines)) < 400:                       # a page its scripts build: its wording is in its data
        data = page_texts(page)[1]
        lines += [data] if data else []
    return lines


def _sentence(line: str, lo: int, hi: int) -> tuple[int, int]:
    """Where the sentence holding line[lo:hi] starts and ends. A short line is one statement whole."""
    if len(line) <= LONG:
        return 0, len(line)
    starts = [m.end() for m in _STOP.finditer(line, 0, lo)]
    end = _STOP.search(line, hi)
    return (starts[-1] if starts else 0), (end.start() if end else len(line))


def _kind(words: str) -> str:
    return next((plural for stem, plural in _KINDS if stem in words.lower()), "")


def _names_one(line: str) -> bool:
    return len(line) <= 70 and bool(_NAMED.search(line)) and "$" not in line and "%" not in line and \
        not (_NOT_OURS.search(line) or _PERK.search(line) or _ONE_GROUP.search(line))


def page_offers(lines: list[str], this_year: int) -> list[PageOffer]:
    """The savings on tickets, passes and memberships a venue's page states, each in the page's words. `lines` is the
    page as page_lines() gives it."""
    n = len(lines)
    short = lambda i: lines[i] if 0 <= i < n and len(lines[i]) <= 90 else ""        # noqa: E731  a heading or a label
    found: list[tuple[int, int, dict]] = []      # (first line, last line, what was read)
    perks: set[int] = set()                      # lines that state a saving on something else
    bare: dict[int, float] = {}                  # lines that state a percent and nothing more
    two_for: set[float] = set()                  # percents the page says are off the second of two tickets
    for i, line in enumerate(lines):
        for m in _SAVING.finditer(line):
            pct, upto = float(m.group(2) or m.group(4)), bool(m.group(1) or m.group(3))
            a, b = _sentence(line, m.start(), m.end())
            sent, rest = line[a:b], line[m.end():b]
            near = line if len(line) <= 600 else line[max(0, a - 200):b + 200]     # where a long line dates the offer
            on = _ON_IT.match(rest)
            if _TWO_FOR.search(sent) and _PASS.search(sent):
                two_for.add(pct)
            if on and (_PERK.search(on.group(1)) or _NOT_OURS.search(sent)):
                perks.add(i)
                continue
            if on:
                its = _ITS_NAME.search(on.group(1))
                found.append((i, i, dict(pct=pct, upto=upto, thing=its.group(1) if its else "", kind=_kind(on.group(1)),
                                         said=sent, near=near, own=True)))
                continue
            before = line[a:m.start()][-90:]
            lead = _ITS_NAME.findall(before)
            if not _BARE.match(rest):
                # It goes on to name something that is not a ticket. That is a perk, unless the line began by naming
                # the ticket's own sale: "Black Friday Annual Pass Sale: 25% off a Whole Year of Fun".
                if lead and (_SALE_CUE.search(before) or days.named(before)) and not (_PERK.search(rest) or _NOT_OURS.search(sent)):
                    found.append((i, i, dict(pct=pct, upto=upto, thing=lead[-1], kind=_kind(lead[-1]), said=sent, near=near, own=True)))
                else:
                    perks.add(i)
                continue
            if _NOT_OURS.search(sent):
                continue
            bare.setdefault(i, pct)
            if lead:                              # the ticket is named on the same line: "Any Day Ticket: Save 25%"
                found.append((i, i, dict(pct=pct, upto=upto, thing=lead[-1], kind=_kind(lead[-1]), said=sent, near=near)))
                continue
            # ... or on the line beside it: its tile's label, over it or under it, a price or the same badge between
            for step in (-1, 1):
                j, hops = i + step, 0
                while 0 <= j < n and hops < 2 and (_PRICES.match(lines[j]) or lines[j] == line):
                    j, hops = j + step, hops + 1
                if 0 <= j < n and _names_one(lines[j]):
                    lo, hi = min(i, j), max(i, j)
                    its = _ITS_NAME.search(lines[j])
                    found.append((lo, hi, dict(pct=pct, upto=upto, thing=its.group(1) if its else "", kind=_kind(lines[j]),
                                               said=" ".join(dict.fromkeys(lines[lo:hi + 1])))))
                    break
        for m in _FOR_PRICE.finditer(line):
            a, b = _sentence(line, m.start(), m.end())
            if _SALE_CUE.search(line) or days.named(line) or _SALE_CUE.search(short(i - 1)) or days.named(short(i - 1)):
                found.append((i, i, dict(price=float(m.group(2).replace(",", "")), thing=m.group(1).strip(),
                                         said=line if len(line) <= LONG else line[a:b], check=line[a:b], own=True,
                                         near=line if len(line) <= 600 else line[max(0, a - 200):b + 200])))
    out: list[PageOffer] = []
    for lo, hi, o in found:
        own = o.pop("own", False)
        check = o.pop("check", o["said"])
        if own and o.get("pct") is not None and (lo - 1 in perks or hi + 1 in perks):       # one of a list of perks
            continue
        if o.get("pct") is not None and (_COMES_WITH.search(short(lo - 1)) or _COMES_WITH.search(short(lo - 2))):
            continue                                                                        # under "Member Benefits"
        if not own and any(k in bare and bare[k] != o["pct"] for k in (lo - 1, hi + 1) if not lo <= k <= hi):
            continue                                                                        # a table of what each tier gets
        if _ONE_GROUP.search(check) or _ONE_GROUP.search(short(lo - 1)) or _ONE_GROUP.search(short(hi + 1)):
            continue
        if o.get("pct") in two_for and not o.get("thing"):                                  # the page's own name for a two-for
            continue
        under = short(hi + 1) if _SAYS_WHEN.search(short(hi + 1)) and not _SAVING.search(short(hi + 1)) else ""
        around = " ".join(x for x in (short(lo - 1), o.pop("near", "") or " ".join(lines[lo:hi + 1]), under) if x)
        years = [int(y) for y in _YEAR.findall(around)]
        if years and max(years) < this_year:                                                # "Black Friday 2024": an old page
            continue
        for name in days.named(o.get("thing", "")):           # "Black Friday Annual Pass" is an Annual Pass
            o["thing"] = clean(re.sub(re.escape(name), "", o["thing"], flags=re.I))
        out.append(PageOffer(said=clean(o.pop("said"))[:240], around=around, **o))
    return out


def sale_links(page_html: str, page_url: str) -> list[str]:
    """The venue's own sale pages a page links to: same site, same section of it, a path that names a sale."""
    here = urlsplit(page_url)
    section = here.path.strip("/").split("/")[0] if here.path.strip("/").count("/") else ""
    found: dict[str, int] = {}
    for href in re.findall(r'href="([^"#?]+)', page_html):
        u = urlsplit(urljoin(page_url, href))
        if u.hostname != here.hostname or u.path.rstrip("/") == here.path.rstrip("/"):
            continue
        if section and not u.path.strip("/").startswith(section + "/"):
            continue
        tail = u.path.strip("/")[len(section):]
        if _SALE_PATH.search(tail) and not _NOT_THAT_PATH.search(tail):
            found.setdefault(f"https://{u.hostname}{u.path}", 0 if days.SLUG.search(tail) else 1)
    return [u for u, _ in sorted(found.items(), key=lambda kv: (kv[1], len(kv[0]), kv[0]))][:FOLLOW]


def _dates(text: str, now: datetime) -> tuple[Optional[datetime], Optional[datetime], str]:
    """When the sale a page states starts and ends, read as a post's words are (sales.sale_dates), and an end that has
    already passed. A post never states one of those; a page left up does ("40% off ends September 10"), and to
    read it the words are dated as if written some months ago."""
    from .sales import sale_dates
    first = None
    for back in (0, 90, 180):
        starts, ends, how = sale_dates(Post(source="", id="", url="", title="", text=text, posted_at=now - timedelta(days=back)), now)
        first = first or (starts, ends, how)
        if ends:
            return (starts if not back else None), ends, how
    return first


def venue_sale(venue: dict, read: list[tuple[str, list[str]]], now: datetime) -> Optional[StoreSale]:
    """A venue's sale as its pages state it: the biggest saving, in the page's words, with the page it is on. `read`
    is [(page address, the page's lines)]. None when no page states a saving that is still on."""
    from .sales import CENTRAL, _end_of, code_of, event_phrase
    today = now.astimezone(CENTRAL).date()
    live: list[tuple[tuple, PageOffer, str, tuple]] = []
    for url, lines in read:
        for o in page_offers(lines, today.year):
            dates = _dates(o.around, now)
            day = days.day_of(o.around, today)
            if dates[1] and dates[1] < now:
                continue                                         # the page still says it, and says it is over
            if days.named(o.around) and not day and not dates[1]:
                continue                                         # named for a day that is not coming: a page left up
            live.append(((o.pct is not None, o.pct or 0.0, -(o.price or 0.0), dates[1] is not None, day is not None), o, url, dates))
    if not live:
        return None
    _, o, url, (starts, ends, ends_how) = max(live, key=lambda x: x[0])     # the first of equals: the top of the page
    pcts = {x[1].pct for x in live if x[1].pct is not None}
    day = days.day_of(o.around, today)
    event = event_phrase(o.around) or (f"{day[0]} sale" if day else "")
    if o.pct is not None:
        upto = o.upto or (not o.thing and len(pcts) > 1)         # several savings and none named: this one is the most
        words, badge = (f"Up to {o.pct:g}% off", f"Up to {o.pct:g}%") if upto else (f"{o.pct:g}% off", f"{o.pct:g}% off")
        pct, rank = None if upto else o.pct, o.pct / 2 if upto else o.pct
        name = event if event and o.thing.lower() in event.lower() else f"{event}: {o.thing}" if event else \
            o.thing or o.kind or "Tickets and passes"
    else:                                                        # the offer line names the pass: the name is the sale's
        upto, words, badge, pct, rank = False, f"{o.thing} for {_usd(o.price)}", _usd(o.price), None, None
        name = event or _kind(o.thing) or "Tickets and passes"
    site = venue.get("site") or (urlsplit(url).hostname or "").removeprefix("www.")
    return StoreSale(
        id="sale:venue:" + re.sub(r"[^a-z0-9]+", "-", venue["name"].lower()).strip("-"), store="", store_name=venue["name"],
        title=o.said, name=name, offer=words, badge=badge, badge_soft=upto, what=TICKETS, own_site=True,
        code=code_of(o.said, "", None, today, today)[0], pct=pct, upto=o.pct if upto else None,
        starts_at=starts, ends_at=ends, ends_how=ends_how.replace("the post says", "the page says"),
        event=day[0] if day else "", event_ends_at=_end_of(day[1]) if day and not ends else None,
        offer_how=f"{site} says “{o.said}”", posted_at=now, checked_at=now, source=site, source_url=url,
        industries=[ENTERTAINMENT], industry_rule="a venue's own page", discount_pct=rank, score=round(rank or 0.0, 2),
        city=venue.get("city", ""), raw={"store_how": "slomp/data/venue_pages.json", "text": o.around})


async def venue_sales(http, now: datetime) -> tuple[list[StoreSale], list[dict]]:
    """Every listed venue's sale, read from its own pages now, and what was read: (sales, sources). A page that can't
    be read (robots.txt, a bot check, an error) is reported and never worked around."""
    from .config import TTL
    from .http import FetchError

    async def one(venue: dict) -> tuple[Optional[StoreSale], dict]:
        read, error, todo, seen, followed = [], "", list(venue["pages"]), set(), 0
        while todo:
            url = todo.pop(0)
            if url in seen:
                continue
            seen.add(url)
            try:
                r = await http.get(url, ttl_s=TTL["page"], html=True)
            except FetchError as e:
                error = error or e.reason
                continue
            if r.status != 200:
                error = error or f"HTTP {r.status}"
                continue
            read.append((r.final_url or url, page_lines(r.text)))
            if url in venue["pages"]:
                more = [u for u in sale_links(r.text, r.final_url or url) if u not in seen and u not in todo][:FOLLOW - followed]
                todo, followed = todo + more, followed + len(more)
        sale = venue_sale(venue, read, now) if read else None
        # `own_site` sets it apart from the deal sites: a place that can't be read is one card missing, not a feed
        return sale, {"name": f"{venue['name']} (its own site)", "own_site": True, "ok": bool(read), "posts": int(sale is not None),
                      **({"error": error} if error and not read else {})}
    got = await asyncio.gather(*(one(v) for v in venue_pages()))
    return [s for s, _ in got if s is not None], [src for _, src in got]
