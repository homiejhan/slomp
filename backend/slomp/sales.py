"""Sales at online stores that ship: store-wide and category sales, promo codes and sale events.

feeds (the Online tab's, each store's dealnews feed, sale searches) -> sale posts -> store -> offer, code -> dates ->
industries -> duplicates -> post pages read again -> rank. docs/DESIGN-online-stores.md has the design.

The result is the same for every city. It is computed for the whole state and kept with every candidate that hasn't
ended; `select` then applies the industries and the moment of the search, here and in the published site's engine.js.
"""
from __future__ import annotations

import asyncio
import re
from collections import Counter
from dataclasses import dataclass, field, replace
from datetime import date, datetime, time, timedelta, timezone
from typing import Iterable, Optional
from urllib.parse import parse_qs, unquote, urlsplit

from zoneinfo import ZoneInfo

from . import days
from . import industries as ind
from .config import TTL
from .http import FetchError, PoliteClient
from .models import OnlineStore, StoreSale
from .online import classify_post, labelled_posts, note_left_out
from .promos import _DAY, _MONTH, _MONTHS, _RANGE_MD, _RANGE_NUM, _date
from .reference import norm
from .sources.feeds import SOURCE_NAMES, DealFeeds, FeedPlan, Post, plan, post_gone
from .stores_online import _straight, registry, store_named, stores_in
from .terms import bogo_of, clean

CENTRAL = ZoneInfo("America/Chicago")
POSTED_DAYS = 30           # a sale posted longer ago than this is not shown, whatever end it states (evergreen coupons)
UNDATED_DAYS = 7           # a sale with no end is shown this long after it was posted
AHEAD_DAYS = 7             # a sale that starts later than this is not shown yet
EVENT_OFFER, EVENT_BADGE = "Sale event, no discount stated", "Sale event"   # a store's event named for a day
SOURCE_ORDER = ("dealnews", "Slickdeals", "Hip2Save", "9to5Toys", "The Inventory", "Ben's Bargains", "DealCatcher")
ONLINE_IDS = tuple(i for i in ind.IDS if ind.BY_ID[i].online)


# A name as a post writes one: capitalized words ("Minky Couture", "eBay"), a number before them ("32 Degrees").
_NAMED = (r"((?:\d+(?:\.\d+)?\s+(?=[A-Z]))?(?:[A-Z]|[a-z](?=[A-Z]))[\w&'.!-]*"
          r"(?:\s+(?:[A-Z&]|[a-z](?=[A-Z]))[\w&'.!-]*){0,3})")
_PLACE = re.compile(r"\b(?:at|on|from|via|@)\s+(?:the\s+)?(?:official\s+)?" + _NAMED)


class _Either:
    """Several patterns read as one: their matches in the order they stand in the text, one for each name. Where two
    patterns read the same words, the earlier pattern's reading stands."""
    def __init__(self, *patterns: re.Pattern):
        self.patterns = patterns

    def finditer(self, text: str) -> list[re.Match]:
        kept: list[re.Match] = []
        for rx in self.patterns:
            for m in rx.finditer(text):
                if not any(k.start(1) < m.end(1) and m.start(1) < k.end(1) for k in kept):
                    kept.append(m)
        return sorted(kept, key=lambda m: m.start(1))


# The words a deal post sends its reader to a store with: "head over to Kohl's", "hop on over to Comfrt.com". Writers
# vary the verb without end ("make your way over to AliExpress.com where ...", "click over to BarefootDreams.com for
# ..."), so any "... over to" counts when what follows shows a store is meant: a website, or "where" and what is
# there. "Savings carry over to January" sends no one anywhere. And the "to" left out: "hurry over Corkcicle where you
# can save 30%".
_TLDS = ("com", "net", "org", "co", "shop", "store", "us", "io")
_TLD = "(?:" + "|".join(_TLDS) + ")"
_GO = r"(?i:head|hop|run|dash|scoot|hurry|go|swing|zip|pop|race)"
_TO_A = r"\s+(?:the\s+)?(?:official\s+|online\s+)?"
_WHERE = r"(?=,?\s+(?i:where)\b)"
_A_SITE = "(?:" + "|".join(rf"(?<=\.{t})" for t in _TLDS) + r")(?![\w-])"
_SENT_TO = _Either(
    re.compile(r"\b" + _GO + r"(?i:\s+on)?(?i:\s+over)?\s+(?i:to)" + _TO_A + _NAMED),
    re.compile(r"(?:\b[\w']+\s+){0,3}\b(?i:over\s+to)" + _TO_A + _NAMED + "(?:" + _A_SITE + "|" + _WHERE + ")"),
    re.compile(r"\b" + _GO + r"(?i:\s+on)?\s+(?i:over)\s+" + _NAMED + _WHERE))


def _shop_in(phrase: str) -> Optional[OnlineStore]:
    """The store a phrase names: "the official Crocs eBay Store" is eBay, where Crocs, a brand, has a shop."""
    named = stores_in(phrase)
    shops = [s for _, s, _ in named if not s.brand]
    return shops[0] if shops else store_named(phrase)


# Deal sites name themselves as the retailer of their own roundups ("The Best Amazon Prime Big Deal Days Deals").
_DEAL_SITES = re.compile(r"^(?:deal ?news|slickdeals|hip2save|9to5toys|the inventory|ben'?s bargains|dealcatcher|"
                         r"the krazy coupon lady|krazy coupon lady)$", re.I)
# A deal site named within other words ("... Gave Hip2Save Readers an EXCLUSIVE Code"): the words are about the post.
_DEAL_SITE_SAID = re.compile(r"\b(?:deal ?news|slickdeals|hip2save|9to5toys|ben'?s bargains|dealcatcher|"
                             r"krazy coupon lady)\b", re.I)


_PRIME_SHIPPING = re.compile(r"\b(?:free\s+)?(?:shipping|delivery)\s+(?:for|w/|with)\s+(?:amazon\s+)?prime(?:\s+members?)?\b",
                             re.I)


def find_store(p: Post) -> tuple[Optional[OnlineStore], str]:
    """The registry store a sale post is at, and how that was decided ("" when no registry store is)."""
    title, text = _straight(p.title), _straight(p.text[:900])
    # "+ Free Shipping for Amazon Prime Members" names a membership, not the store (Hip2Save's Woot posts)
    title = _PRIME_SHIPPING.sub(" ", title)
    if p.seller and _DEAL_SITES.match(p.seller.strip()):
        p = replace(p, seller="")                 # the deal site isn't the store: read on
    if p.seller:
        s = store_named(p.seller)
        if s:
            return s, "the source's store field" if p.source == "dealnews" else "the post's store"
        if p.source == "dealnews":                  # a retailer the registry doesn't know: the caller keeps its name
            return None, ""
    for rx in (_PLACE, _SENT_TO):
        for m in rx.finditer(title):
            s = _shop_in(m.group(1))
            if s:
                return s, f"the title: {m.group(0).strip()!r}"
    for m in _SENT_TO.finditer(text):
        s = _shop_in(m.group(1))
        if s:
            return s, f"the post: {m.group(0).strip()!r}"
    named = stores_in(title)
    if named and named[0][0] == 0 and not named[0][1].brand:
        return named[0][1], "the title starts with it"
    shops = [x for x in named if not x[1].brand]
    if len({x[1].key for x in shops}) == 1:
        return shops[0][1], "the title names it" + (" (its sale event)" if shops[0][2] else "")
    for m in _PLACE.finditer(text):           # the post's words before a brand the title names: it may sell elsewhere
        s = _shop_in(m.group(1))
        if s:
            return s, f"the post: {m.group(0).strip()!r}"
    if not shops and len({x[1].key for x in named}) == 1:
        return named[0][1], "the title names it"
    return None, ""


def store_of_sale(p: Post) -> tuple[Optional[OnlineStore], str, str]:
    """The registry store whose sale a post is about when its title names no store, or misspells the one it means
    ("lululelmon Black Friday Sale + Free Shipping"), how that was decided, and what the sale is called: the one
    store whose sale the post's first words name by the name the title gives the sale ("You don't want to miss the
    prices during the Lululemon Black Friday Sale!"). The sale has a name of its own: event words, and only those,
    stand between the store's name and the sale word ("the Amazon sale" names none). A second store's sale leaves
    it open."""
    title, text = _straight(p.title), _straight(p.text[:300])
    if stores_in(title):
        return None, "", ""
    found: dict[str, tuple[OnlineStore, str, str]] = {}
    for at, s, _ in stores_in(text):
        end = next((at + len(n) for n in sorted(map(_straight, s.names), key=len, reverse=True)
                    if text[at:at + len(n)].lower() == n.lower()), None)
        if end is None:
            continue
        tail = re.sub(r"^(?:'s|')", "", text[end:])
        raw = tail.split()[:6]
        for j, w in enumerate(raw):
            word = w.strip(":,.!|")
            if _SALE_NOUN.match(word):
                called = " ".join(raw[:j] + [word])
                if j and all(is_store_event(x) for x in raw[:j]) and \
                        re.search(r"\b" + re.escape(called) + r"\b", title, re.I):
                    found.setdefault(s.key, (s, f"{text[at:end]}{text[end:len(text) - len(tail)]} {called}", called))
                break
            if word != w or not word:             # punctuation ends the phrase before a sale word
                break
    if len(found) == 1:
        s, said, called = next(iter(found.values()))
        return s, f"the post names its sale: {said!r}", called
    return None, "", ""


# --- a store the registry doesn't list ----------------------------------------------------------------------------
# Deal sites post sales at more stores than any list keeps up with, and the post names the store: "PUMA's Stock Up
# sale ...", "Wilson Fall Sale: ...", "... at Dearfoams", and after the offer, "Up to 70% Off Comfrt Early Black
# Friday Sale", "Buy 1, Get 1 FREE Comfrt Hoodies & Sweatpants". A name is the first capitalized words, before a
# possessive, before event words and a sale word, or before the goods on sale; it names a store only when something
# is left of it once the words of events, departments and goods are taken out ("Fall Sale", "Kids' Sale" and "Costume
# Sale" name none). A name may start with a number, and then the word after it is the name's whatever else it means
# ("32 Degrees"). The post must also show the sale is at that store, online: a link to the name's own website, its
# own words sending the reader there ("Hop on over to Comfrt where ..."), or, for a sale named after the store, that
# it ships. A name before goods ("Comfrt Hoodies") could as well be a brand sold elsewhere, so shipping is not enough.
#
# Hip2Save's posts carry no links at all (run 161, Nov 22, 2026), so there the post's words are all there is: a
# website the title itself names ("... on FilterKing.com"), the site the post sends the reader to when its name holds
# the title's ("GiveHugz.co" for "Hugz"), and, when the title names no one, the store the post sends the reader to.
_NAME_TOKEN = re.compile(r"(?:[A-Z][\w&.!+-]*|[a-z]+[A-Z][\w&.!+-]*|&)(?:'s|')?$")
_SALE_NOUN = re.compile(r"^(?:sales?|events?|deals|clearance|savings|promo(?:tion)?s?|specials|markdowns?|blowout|"
                        r"outlet|offers?)\b", re.I)
_NOT_A_NAME = re.compile(r"^(?:massive|amazing|awesome|epic|insane|crazy|great|secret|surprise|select|selected|"
                         r"checkout|cart|register|participating|local|retailers?|stores?|official)$", re.I)
_HOST_WORDS = {"www", "www2", "shop", "store", "us", "en", "com", "net", "org", "co", "go", "click", "m"}
# The offer a title leads with, before where it is: "Up to 70% Off", "Extra 40% Off", "$10 Off", "BOGO Free", "Buy 1,
# Get 1 50% Off".
_LEAD_OFFER = re.compile(
    r"^\s*(?:(?:up\s?to|an?\s+extra|extra|additional|over|at\s+least|take|save|get|score)\s+)*"
    r"(?:\d{1,3}\s?%(?:\s?(?:-|–|to)\s?\d{1,3}\s?%)?\s+off|\$\s?\d[\d,.]*\s+off|"
    r"bogo(?:\s+(?:free|\d{1,3}\s?%\s+off|half\s+off))?|b\d+g\d+(?:\s+free)?|"
    r"buy\s+(?:\d+|one|two),?\s+get\s+(?:\d+|one|two)\s+(?:free|\d{1,3}\s?%\s+off|half\s+off))\s+"
    r"(?:(?:on|at|of|the|all|select|any|your)\s+)*", re.I)
_NUMBER = re.compile(r"\d+(?:\.\d+)?$")           # a name may start with one: "32 Degrees", "5.11 Tactical"


def _goods_or_event(word: str) -> bool:
    w = word.strip("'&.,!").lower()
    return not w or len(norm(w)) < 2 or is_store_event(w) or bool(ind.from_department(w)) or \
        bool(ind.text_industries(w)) or bool(ind.APPAREL_CUE.fullmatch(word)) or bool(_NOT_A_NAME.match(w))


def _a_name(name: str) -> bool:
    """Whether something is left of a name once the words of events, departments and goods are taken out. Words that
    are goods only together ("Stuffed Animals", "Christmas Tree") leave nothing."""
    words = name.split()
    together = len(words) > 1 and ind.text_industries(name) and not any(ind.text_industries(w) for w in words)
    return any(not _goods_or_event(w) for w in words) and not together and not _DEAL_SITES.match(name)


def _numbered(name: str) -> bool:
    """A name that starts with a number and goes on: "32 Degrees", "5.11 Tactical". The word after the number is part
    of the name whatever else it means ("degrees"); a count of days or of stores is not one ("12 Days", "5 Stores")."""
    words = name.split()
    return len(words) > 1 and bool(_NUMBER.match(words[0])) and not is_store_event(name) and \
        not any(_NOT_A_NAME.match(w) for w in words[1:])


def _named_sale(words: list[str]) -> tuple[str, bool, bool]:
    """The store these words start with, whether it was written as a possessive ("PUMA's ... sale"), and whether
    the sale is named for an event of its own ("Wilson Fall Sale", not "Soma Sale")."""
    for k in range(1, min(4, len(words) - 1) + 1):
        last = words[k - 1]
        if not _NAME_TOKEN.match(last) or (k > 1 and last != "&" and _goods_or_event(last)) or \
                ind.APPAREL_CUE.fullmatch(last):
            return "", False, False
        rest = [w.strip(":,.!|") for w in words[k:k + 6]]
        possessive = bool(re.search(r"'s?$", last)) and last != "&"
        name = re.sub(r"'s?$", "", " ".join(words[:k]))
        for j, w in enumerate(rest):
            if _SALE_NOUN.match(w):
                events = all(is_store_event(x) or not norm(x) for x in rest[:j])
                if (possessive or events) and _a_name(name):
                    return name, possessive, events and any(norm(x) for x in rest[:j])
                break
            if j >= 4:
                break
        if possessive:
            return "", False, False
    return "", False, False


def _name_before_sale(words: list[str]) -> tuple[str, bool]:
    """The store these words start with, and whether it was written as a possessive."""
    return _named_sale(words)[:2]


def _leading_name(title: str) -> tuple[str, bool]:
    """The store a title starts with, and whether it was written as a possessive."""
    return _name_before_sale(_DECOR.sub("", _straight(title)).split())


def _after_offer(title: str) -> list[str]:
    """The words after the offer a title leads with ([] when it leads with none)."""
    rest = _DECOR.sub("", _straight(title))
    m = _LEAD_OFFER.match(rest)
    return rest[m.end():].split() if m else []


def _first_words(words: list[str]) -> list[str]:
    """The capitalized words these start with, as far as a name could run: at most three, up to punctuation or a
    sale word. A number may lead ("32 Degrees")."""
    run: list[str] = []
    for i, word in enumerate(words[:4]):
        token = word.strip(":,.!|")
        numbered = not run and bool(_NUMBER.match(token)) and i + 1 < len(words) and \
            bool(_NAME_TOKEN.match(words[i + 1].strip(":,.!|")))
        if len(run) == 3 or _SALE_NOUN.match(token) or not (numbered or _NAME_TOKEN.match(token)):
            break
        run.append(re.sub(r"'s?$", "", token))
        if token != word:                         # punctuation ends a name
            break
    while run and run[-1] == "&":
        run.pop()
    return run


def _names_in(words: list[str], goods_too: bool) -> list[str]:
    """What a store could be called when its name is the first of these words, the longest first: "Charlotte Tilbury"
    and "Charlotte" of "Charlotte Tilbury Makeup Sale". With `goods_too`, words of goods count as well ("32 Degrees",
    "Mattress Firm"): for when the post links to a site of that very name."""
    run = _first_words(words)
    if not goods_too:
        first = 2 if run and _NUMBER.match(run[0]) else 0       # the word after a leading number is the name's
        stop = next((i for i, w in enumerate(run) if i >= first and w != "&" and _goods_or_event(w)), len(run))
        run = run[:stop]
    names = [" ".join(run[:k]) for k in range(len(run), 0, -1) if run[k - 1] != "&"]
    return [n for n in names if not _NUMBER.match(n) and not is_store_event(n) and not _DEAL_SITES.match(n) and
            (goods_too or _a_name(n) or _numbered(n))]


def _hosts(urls: Iterable[str]) -> set[str]:
    """The sites the links lead to, through affiliate redirects that carry the destination in their query."""
    out: set[str] = set()
    todo = [u for u in urls if u]
    while todo:
        u = todo.pop()
        parts = urlsplit(u)
        if parts.hostname:
            out.add(parts.hostname.lower())
        for values in parse_qs(parts.query).values():
            todo += [unquote(v) for v in values if re.match(r"https?(?::|%3A)", v, re.I)]
    return out


def _own_site(name: str, urls: Iterable[str]) -> str:
    key = norm(re.sub(r"^the\s+", "", name, flags=re.I))
    for host in sorted(_hosts(urls)):
        labels = [x for x in host.split(".") if x not in _HOST_WORDS]
        if key and len(key) >= 3 and key in labels:
            return host
    return ""


# A website a title names: "Extra 20% Off Any Size on FilterKing.com + Free Shipping!" (not an e-mail address).
_TITLE_SITE = re.compile(r"(?<![\w@.-])((?:[A-Za-z0-9][A-Za-z0-9-]*\.)*([A-Za-z0-9][A-Za-z0-9-]{2,})\." + _TLD + r")\b(?![\w@/-])")


def _sent_names(text: str) -> list[tuple[str, str]]:
    """Where a post's own words send the reader: (the name as written, without ".com"; the words that say so)."""
    out = []
    for rx in (_SENT_TO, _PLACE):
        for m in rx.finditer(text):
            if rx is _PLACE and not re.match(r"(?:at|@)\b", m.group(0), re.I):
                continue                          # "hoodies from Comfrt", "save on Electric Bikes": no store is named
            said = re.sub(r"\." + _TLD + r"\b.*$", "", m.group(1).strip(" .,!"), flags=re.I)
            said = re.sub(r"'s?$", "", re.sub(r"^the\s+", "", said, flags=re.I))
            if said:
                out.append((said, m.group(0).strip()))
    return out


def _sent_there(name: str, text: str) -> str:
    """The post's own words sending the reader to this store, or "": "Hop on over to Comfrt.com where ...", and where
    the site's name holds the store's, "Head over to GiveHugz.co" for Hugz, or the words go on after it, "... to
    Comfrt's Black Friday Sale", "... to Minky Couture" for Minky. Not when the words are goods only together: "... to
    the Stuffed Animals page" is no store called Stuffed."""
    key = norm(re.sub(r"^the\s+", "", name, flags=re.I))
    if len(key) < 3:
        return ""
    for said, words in _sent_names(text):
        said_key, parts = norm(said), said.split()
        whole = said_key == key
        k = len(name.split())                     # "Comfrt's Black Friday Sale" begins with Comfrt
        begins = len(parts) > k and norm(re.sub(r"'s?$", "", " ".join(parts[:k]))) == key and _a_name(said)
        inside = len(parts) == 1 and len(key) >= 4 and 2 * len(key) >= len(said_key) and \
            (said_key.startswith(key) or said_key.endswith(key))
        if whole or begins or inside:
            return words
    return ""


def _sent_store(text: str, title: str = "") -> tuple[str, str]:
    """The store a post sends the reader to when its title names none, and the words that say so: "Hop on over to
    Minky Couture where ...". Not a store of the registry (find_store reads those), a deal site, or words of events
    and goods ("... to the Black Friday Sale"). A website named for what it sells keeps its ".com" ("Blinds.com"),
    and a name the title also writes is spelled as the title spells it ("Barefoot Dreams" for BarefootDreams.com)."""
    for m in _SENT_TO.finditer(text):
        written = m.group(1).strip(" .,!")
        site = re.match(r"(\S+?\." + _TLD + r")\b", written, re.I)
        said = re.sub(r"\." + _TLD + r"\b.*$", "", written, flags=re.I)
        parts = re.sub(r"^the\s+", "", said, flags=re.I).split()
        least = 2 if parts and _NUMBER.match(parts[0]) else 1             # "32 Degrees" is not a store called 32
        while len(parts) > least and (_goods_or_event(parts[-1]) or _SALE_NOUN.match(parts[-1])):
            parts.pop()                           # "Comfrt Black Friday Sale" is Comfrt's
        name = re.sub(r"'s?$", "", " ".join(parts))
        if not name or store_named(site.group(1) if site else name) or _DEAL_SITES.match(name):
            continue
        if _a_name(name) or _numbered(name):
            return _as_titled(name, title), m.group(0).strip()
        if site:
            return site.group(1), m.group(0).strip()
    return "", ""


def _as_titled(name: str, title: str) -> str:
    """A name as the title spells it, where the title writes the same name in its own way."""
    key, words = norm(name), [w.strip(":,.!|()") for w in title.split()]
    for i in range(len(words)):
        for k in range(1, 5):
            if i + k <= len(words) and norm(re.sub(r"'s?$", "", " ".join(words[i:i + k]))) == key:
                return re.sub(r"'s?$", "", " ".join(words[i:i + k]))
    return name


def named_store(p: Post) -> tuple[str, str]:
    """A store the registry doesn't list, as the post names it, and how that was decided ("" when none is)."""
    urls = list(p.links) + [p.merchant_link]
    title, text = _straight(p.title), _straight(p.text[:900])
    ships = bool(_SHIPS.search(f"{p.title} {p.text[:600]}"))
    lead = _DECOR.sub("", title).split()
    after = _after_offer(p.title)

    name, possessive = _name_before_sale(lead)
    if name:
        site = _own_site(name, urls)
        if site or ships:
            return name, f"the title names it ({name}{'’s' if possessive else ''} sale)" + \
                (f" and the post links to {site}" if site else " and the post says it ships")
    # A website the title names is the store, spelled as the post spells it where it does ("Filter King"). One named
    # for what it sells keeps its ".com": "Blinds.com" is a store, "Blinds" is not.
    for m in _TITLE_SITE.finditer(title):
        host, label = m.group(1), m.group(2)
        if store_named(host) or _DEAL_SITES.match(label):
            continue
        spelled = next((said for said, _ in _sent_names(text) if norm(said) == norm(label)), label)
        return (spelled if _a_name(label) else host), f"the title names its website ({host})"
    # A name the post links to a site of, at the start of the title or after its offer; then one its words send the
    # reader to. That a post ships says nothing of where: "Stuffed Animals Sale + Free Shipping" names no store.
    for name in _names_in(after or lead, True):
        site = _own_site(name, urls)
        if site:
            return name, f"the title names it ({name}) and the post links to {site}"
    for name in _names_in(after or lead, False):
        sent = _sent_there(name, text)
        if sent:
            return name, f"the title names it ({name}) and the post says {sent!r}"
    # The title names no one the post confirms: the store the post sends the reader to, when it says it ships.
    name, sent = _sent_store(text, title)
    if name and ships:
        return name, f"the post says {sent!r} and that it ships"
    # A sale named for the store's own event after the offer ("Up to 75% Off Laura Geller Early Black Friday Sale"),
    # in a post that ships and sends the reader nowhere else. Goods are seldom given an event of their own.
    name, possessive, event = _named_sale(after) if after else ("", False, False)
    if name and (possessive or event) and ships:
        return name, f"the title names it after the offer ({name}{'’s' if possessive else ''} sale) and the post says it ships"
    for m in _PLACE.finditer(title):
        name = m.group(1).strip(" .,!")
        site = _own_site(name, urls) if _a_name(name) or _numbered(name) else ""
        if site:
            return name, f"the title: {m.group(0).strip()!r}, and the post links to {site}"
    return "", ""


def store_evidence(p: Post) -> str:
    """For a build's log, what a post left out as "store not identified" has to go on: the name its title could
    mean, the sites it links to, where its words send the reader, whether it says it ships, and how it begins."""
    words = _after_offer(p.title) or _DECOR.sub("", _straight(p.title)).split()
    names = [n for n in (_name_before_sale(words)[0], *_names_in(words, False)) if n]
    own = urlsplit(p.url).hostname or ""
    hosts = sorted(h for h in _hosts(list(p.links) + [p.merchant_link]) if h != own)
    text = _straight(clean(p.text))
    sent = next((m.group(1) for m in _SENT_TO.finditer(text[:900])), "")
    return (f"title name {names[0]!r}" if names else "no name in the title") + \
        (f", links to {', '.join(hosts[:4])}" if hosts else ", no links") + \
        (f", sends readers to {sent!r}" if sent else "") + \
        (", says it ships" if _SHIPS.search(f"{p.title} {p.text[:600]}") else "") + \
        (f", begins {text[:110]!r}" if text else "")


# --- what the sale offers ----------------------------------------------------------------------------------------
_SHIP_TAIL = re.compile(r"\s*(?:\+|&|and|plus)\s+(?:\*?rare\*?\s+|earn\s+)?(?:free\s+(?:prime\s+)?)?(?:shipping|s&h|s/h|"
                        r"same-day delivery|delivery|store pickup|pickup|digital download|email delivery)\b.*$|"
                        r"\s*(?:\+|&)\s+\$[\d.]+\s+shipping\b.*$|\s*\+\s*shipping varies\b.*$", re.I)
_DECOR = re.compile(r"^\s*(?:\*+\s*)?(?:(?:hot|wow|go|rare|new|last chance|today only|ends soon|huge|yay|sweet|"
                    r"last day to (?:score|grab|get|shop)|stock up on essentials|don'?t miss|score|snag|grab|shop|save on|"
                    r"get|over)\W+)+", re.I)
_FOR_MEMBERS = re.compile(r"\s+for (?:amazon |target )?(?:prime|circle|rewards?) members\b", re.I)
# Hip2Save puts an example price or a list after " | " or " = ": "40% Off Target Handbags = Styles from $9"
_ASIDE = re.compile(r"\s+[|=]\s+.*$|\s+\((?![^()]*%)[^()]*\)\s*$")
_BOGO_NEXT = re.compile(r"\bbuy\s+(\d+|one),?\s+get\s+(?:an?\s+)?(?:extra\s+)?(\d{1,3})\s?%\s?off\s+(?:the\s+)?"
                        r"(?:2nd|second|next|another)\b", re.I)
_BOGO_BARE = re.compile(r"\bbogo\b(?!\s*(?:free|\d{1,3}\s?%|half))", re.I)
_BUY_N_SAVE = re.compile(r"\bbuy\s+(\d+)\+?,?\s+(?:and\s+)?save\s+\$\s?(\d[\d,]*)", re.I)
_UPTO_PCT = re.compile(r"\bup\s?to\s+(?:an?\s+)?(?:extra\s+|additional\s+)?(\d{1,3})\s?%", re.I)
_RANGE_PCT = re.compile(r"\b(\d{1,3})\s?%\s?(?:to|-|–)\s?(\d{1,3})\s?%\s?off", re.I)
_EXTRA_PCT = re.compile(r"\b(?:extra|additional|add'?l\.?|another|take an extra)\s+(\d{1,3})\s?%", re.I)
_PCT = re.compile(r"(?<![\d.$%])(\d{1,3})\s?%\s?off\b", re.I)
_PCT_OF = re.compile(r"(?<![\d.$%])(\d{1,3})\s?%\s?off\s+(?:(?:your|an?|orders?|purchases?)\s+(?:of\s+)?)?\$\s?(\d[\d,]*)\+?",
                     re.I)                                   # "New Balance Sale: 25% off $125"
_OFF = re.compile(r"(\bup\s?to\s+|\$\s?\d[\d,]*\s?(?:to|-|–)\s?)?\$\s?(\d[\d,]*(?:\.\d\d)?)\s?off\b(?:\s+(?:your\s+|an?\s+|orders?\s+(?:of\s+)?|"
                  r"purchases?\s+(?:of\s+)?|when you spend\s+|every\s+)?\$\s?(\d[\d,]*)\+?)?", re.I)
# Dollars off said another way: "Up to $150 in instant credits", "$500 instant savings", "Save up to $200 on TVs".
_OFF_SAID = re.compile(r"(\bup\s?to\s+)?\$\s?(\d[\d,]*(?:\.\d\d)?)\s+(?:in\s+)?instant\s+(?:savings|credits?|rebates?|discounts?)\b|"
                       r"\bsave\s+(up\s?to\s+)?\$\s?(\d[\d,]*(?:\.\d\d)?)\b(?!\s?(?:off\b|\+|or more|when|with|w/|on orders?|"
                       r"on your|on purchases?))", re.I)
_SPEND = re.compile(r"\bspend\s+\$\s?(\d[\d,]*)\+?(?:\s+on\s+[^,$]{1,60})?,?\s+(?:and\s+)?(?:get|save|receive|take)\s+(?:an?\s+)?"
                    r"\$\s?(\d[\d,]*)(\s+off|\s+(?:[\w']+\s+){0,2}(?:gift ?cards?|gc|credit|cash|rewards?))?", re.I)
_BUY_N_PCT = re.compile(r"\bbuy\s+(\d+)\+?(?:\s+or\s+more)?,?\s+(?:and\s+)?(?:get|save)\s+(\d{1,3})\s?%\s?off", re.I)
_SITEWIDE = re.compile(r"\bsite-?wide\b|\bstore-?wide\b|\bentire (?:site|store)\b|\bwhole store\b", re.I)
# "Everything" is the whole store only when the sale names nothing narrower: "LEGO Deal Days Event: 40% off
# everything" is everything LEGO.
_EVERYTHING = re.compile(r"\beverything\b|\bmost items\b|\bany order\b|\ball orders\b|\bentire (?:order|purchase)\b", re.I)
_CATEGORY_NOUNS = re.compile(
    r"\b(?:costumes|handbags|bags|backpacks|purses|wallets|jackets|coats|sweaters|hoodies|sweatshirts|pajamas|pjs|"
    r"jeans|pants|leggings|shorts|shirts|tees|t-shirts|tops|dresses|skirts|clothing|clothes|apparel|activewear|"
    r"outerwear|swimwear|underwear|bras|socks|shoes|sneakers|boots|sandals|slippers|clogs|heels|jewelry|watches|"
    r"sunglasses|accessories|styles|toys|games|puzzles|dolls|books|decor|furniture|bedding|sheets|towels|rugs|"
    r"curtains|lighting|lamps|cookware|bakeware|appliances|kitchen items|kitchenware|tools|gear|equipment|supplies|"
    r"essentials|items|products|brands|collections?|favorites|finds|makeup|skincare|skin care|haircare|hair care|"
    r"fragrances|perfumes|candles|vitamins|supplements|snacks|groceries|electronics|laptops|tvs|headphones|earbuds|"
    r"speakers|cameras|phones|tablets|computers|monitors|plants|ornaments|decorations|outdoors?)\b", re.I)
_ROUNDUP = re.compile(r"\b(?:best|top|hottest|our top|my top|\d+)\s+(?:\w+\s+){0,3}(?:sales|deals|finds|picks)\b"
                      r"(?:\s+\w+){0,4}\s+(?:this week|today|right now|of the (?:week|day)|you can still|to grab)\b|"
                      r"\broundup\b|\bweekly ad\b|\bgift ideas\b|\bgift guide\b", re.I)
_SALE_WORDS = re.compile(r"\b(?:sales?|deals?|event|promo(?:tion)?s?|codes?|coupons?|clearance|savings|specials|outlet|"
                         r"sitewide|site-wide|storewide|everything|markdowns?|flash|doorbusters?|discounts?|days|week|"
                         r"friends\s?(?:&|and)\s?family)\b", re.I)
_ONE_PRICE = re.compile(r"(?:\bfor|:|\bjust|\bonly|=|\bnow|\bat)\s+\$\s?\d[\d,]*(?:\.\d\d)?\b(?!\s?(?:off|\+|or more))|"
                        r"\b\d{1,2} cents\b", re.I)
_AND_MORE = re.compile(r"(?:&|\band|\+)\s+(?:so much\s+)?more\b", re.I)
# The nouns that name a sale of many things: "Deal", one thing's, is not one.
_SALE_NOUNS = re.compile(r"\b(?:sales?|deals|events?|savings|specials|doorbusters?|clearance|markdowns?)\b", re.I)
_PRICE_NOTE = re.compile(r"\b(from|starting at|start(?:s|ing)? at|as low as|under|for less than)\s*(?:just\s+|only\s+)?"
                         r"\$\s?(\d[\d,]*(?:\.\d\d)?)", re.I)
_PRICE_HEDGE = re.compile(r"\b(?:from|starting at|as low as|under|for less than|prices? (?:start\s+)?(?:at|from)|"
                          r"deals? from|styles? from|start(?:ing)? at)\s*(?:just\s+|only\s+)?\$", re.I)


@dataclass
class Offer:
    pct: Optional[float] = None
    upto: Optional[float] = None
    extra: Optional[float] = None
    off: Optional[float] = None
    off_upto: bool = False
    min_spend: Optional[float] = None
    reward: str = ""                    # "gift card", "credit": a spend-and-get paid in store money
    bogo: str = ""
    bogo_pct: Optional[float] = None
    buy_n: int = 0                      # "buy 3, get 20% off", "buy 10, save $50"
    extra_upto: Optional[float] = None  # "+ 10% to 35% off": an extra percent that varies

    @property
    def any(self) -> bool:
        return any(v is not None for v in (self.pct, self.upto, self.extra, self.off, self.bogo_pct)) or bool(self.bogo)


# An offer begins the part after a colon: "Kohl's Deal Days Sale: Up to 60% off ...", not "Amazon fall Prime Day:
# Score Hanes deals from $7 (Up to 61% off)", a headline whose subject comes after the colon.
_OFFER_START = re.compile(r"^(?:up\s?to\b|extra\b|additional\b|over\b|\d{1,3}\s?%|\$\d|bogo\b|buy\b|b\d+g\d\b|spend\b|"
                          r"save\b|take\b|at least\b)", re.I)


def split_title(title: str) -> tuple[str, str]:
    """(what is on sale, the offer) for a title that puts the offer after a colon; ("", title) otherwise."""
    t = _straight(title)
    head, sep, tail = t.rpartition(": ")
    if sep and len(head) >= 3 and _OFFER_START.match(tail.strip()):
        return head, tail
    return "", t


def offer_part(title: str) -> str:
    """The words that state the offer, without shipping, which is not part of it, or an aside."""
    return _ASIDE.sub("", _SHIP_TAIL.sub("", split_title(title)[1])).strip()


def aside_of(title: str) -> str:
    """What a title says after " | " or " = ", without shipping: Hip2Save's example price or list, and sometimes the
    offer itself ("Nordstrom Black Friday Sale is LIVE | Up to 75% Off Baublebar, LEGO, UGG & More")."""
    m = re.search(r"\s+[|=]\s+(.*)$", _straight(title))
    return _SHIP_TAIL.sub("", m.group(1)).strip() if m else ""


def names_a_sale(text: str) -> bool:
    """Whether words name a sale or a day stores hold sales on ("Black Friday Ad Preview"), not one product."""
    return bool(_SALE_NOUNS.search(text)) or bool(days.named(text))


def _at_most(o: Offer, said: str) -> Offer:
    """An offer told beside a sale's name rather than as its offer: one of its highlights, so a plain percent is the
    most the sale gives, unless the words say it is on everything."""
    if o.pct is not None and not o.buy_n and not (_SITEWIDE.search(said) or _EVERYTHING.search(said)):
        o.upto, o.pct, o.min_spend = max(o.upto or 0, o.pct), None, None
    return o


def parse_offer(title: str) -> Offer:
    """The offer a title states. A title that names a sale and leaves its offer to an aside is read there ("Target's
    Black Friday Deals Start 11/22 (50% Off Thousands of Gifts!)", "... Sale is LIVE | Up to 75% Off ...")."""
    part = offer_part(title)
    head = re.sub(r"\([^()]*\)", " ", part)
    if head == part or not names_a_sale(head) or _parse(head).any:
        o = _parse(part)
    else:
        o = _at_most(_parse(part), part)          # the offer is in a parenthesis after the sale's name
    if not o.any and names_a_sale(_ASIDE.sub("", _straight(title))):
        aside = aside_of(title)
        o = _at_most(_parse(aside), aside)
    return o


def said_offer(p: Post) -> tuple[Offer, str]:
    """The offer in the sentence of a post that sends the reader to the store ("Through December 1st, head over to
    Nordstrom.com where you can save up to 75% off popular designer and name brands during their Black Friday
    Sale!"), and that sentence. For a title that names a sale and not its discount. What one sentence says of a sale
    is the most it gives, so a plain percent is read as a ceiling unless the sentence says it is on everything."""
    text = _straight(p.text[:900])
    for m in _SENT_TO.finditer(text):
        said = _sentence(text, m.start())
        o = _parse(_SHIP_TAIL.sub("", said[max(0, said.find(m.group(0))):]))
        if o.any:
            return _at_most(o, said), said
    return Offer(), ""


def price_note(title: str) -> str:
    """The price a sale's title gives in place of a discount: "From $15", "Under $50"."""
    m = _PRICE_NOTE.search(_SHIP_TAIL.sub("", _straight(title)))
    if not m:
        return ""
    return ("Under " if re.match(r"under|for less than", m.group(1), re.I) else "From ") + _usd(float(m.group(2).replace(",", "")))


def _parse(text: str) -> Offer:
    t = re.sub(r"\(([^()]*%[^()]*)\)", r" \1 ", text)      # "(Up to 64% off)"
    o = Offer()
    m = _BUY_N_PCT.search(t)
    if m:
        o.pct, o.buy_n = float(m.group(2)), int(m.group(1))
        t = t[:m.start()] + " " + t[m.end():]
    m = _BUY_N_SAVE.search(t)
    if m and not o.buy_n:
        o.off, o.buy_n = float(m.group(2).replace(",", "")), int(m.group(1))
        t = t[:m.start()] + " " + t[m.end():]
    m = _BOGO_NEXT.search(t)                    # "buy 1, get extra 75% off 2nd": the second one, not everything
    if m:
        buy, off = int(m.group(1)) if m.group(1).isdigit() else 1, float(m.group(2))
        o.bogo, o.bogo_pct = f"buy {buy} get 1 {off:g}% off", round(off / (buy + 1), 1)
        t = t[:m.start()] + " " + t[m.end():]
    elif not o.buy_n:
        if _BOGO_BARE.search(t) and not re.search(r"\bbuy\s+\w+,?\s+get\b", t, re.I):
            o.bogo = "buy one, get one deals"        # "BOGO & More": which kind isn't said
            t = _BOGO_BARE.sub(" ", t)
        else:
            o.bogo, o.bogo_pct = bogo_of(t)
            if o.bogo:                               # the BOGO's own percent is not a percent off everything
                t = re.sub(r"\b(?:buy|b)\s?(?:\d+|one|two)\s?(?:[.,;]\s*)?(?:get|g)\s?(?:the\s)?(?:\d+|one|two)?"
                           r"(?:st|nd|rd|th)?\s?(?:free|\d{1,3}\s?%\*?\s?off|half (?:off|price))?|\bbogo\b(?:\s+(?:free|"
                           r"\d{1,3}\s?%\s?off|half off))?", " ", t, flags=re.I)
    m = _RANGE_PCT.search(t)
    if m:
        lo, hi = sorted((float(m.group(1)), float(m.group(2))))
        if "+" in t[:m.start()]:                # after a plus it comes on top: "up to 89% off + 10% to 35% off"
            o.extra, o.extra_upto = lo, hi
        else:
            o.pct, o.upto = lo, hi
        t = t[:m.start()] + " " + t[m.end():]
    for m in _EXTRA_PCT.finditer(t):
        o.extra = max(o.extra or 0, float(m.group(1)))
        o.extra_upto = None
    t2 = _EXTRA_PCT.sub(" ", t)
    for m in _UPTO_PCT.finditer(t2):
        o.upto = max(o.upto or 0, float(m.group(1)))
    t3 = _UPTO_PCT.sub(" ", t2)
    if o.pct is None:
        firm = [float(x) for x in _PCT.findall(t3)]
        if firm:
            o.pct = max(firm)
            m = _PCT_OF.search(t3)
            if m and float(m.group(1)) == o.pct:
                o.min_spend = float(m.group(2).replace(",", ""))
            # A list of highlights ("$5 Throw Blankets, 50% Off Gift Sets & More", "FREE Poinsettias, BOGO Offers,
            # 70% Off Trees & More"): a percent that is not its first item is one item's, the most the sale gives.
            at = next(m for m in _PCT.finditer(t3) if float(m.group(1)) == o.pct)
            if _AND_MORE.search(t3) and "," in t3[:at.start()] and "%" not in t3[:at.start()] and not o.buy_n:
                o.upto, o.pct, o.min_spend = max(o.upto or 0, o.pct), None, None
    m = _SPEND.search(t)
    if m:
        o.min_spend, o.off = float(m.group(1).replace(",", "")), float(m.group(2).replace(",", ""))
        kind = (m.group(3) or "").lower()
        o.reward = "" if not kind or "off" in kind else "credit" if "credit" in kind else \
            "store cash" if "cash" in kind or "reward" in kind else "gift card"
    else:
        for m in _OFF.finditer(t):
            v = float(m.group(2).replace(",", ""))
            if o.off is None or v > o.off:
                o.off, o.off_upto = v, bool(m.group(1))
                o.min_spend = float(m.group(3).replace(",", "")) if m.group(3) else None
        if o.off is None:
            for m in _OFF_SAID.finditer(t):
                v = float((m.group(2) or m.group(4)).replace(",", ""))
                if o.off is None or v > o.off:
                    o.off, o.off_upto = v, bool(m.group(1) or m.group(3))
    for k in ("pct", "upto", "extra", "extra_upto"):
        v = getattr(o, k)
        if v is not None and not 0 < v < 100:
            setattr(o, k, None)
    if o.upto is not None and o.pct is not None and o.upto <= o.pct:
        o.upto = None
    return o


def _pct(v: float) -> str:
    return f"{v:g}%"


def _usd(v: float) -> str:
    return f"${v:,.2f}".replace(".00", "")


def offer_text(o: Offer) -> tuple[str, str, bool]:
    """(the offer in words, its badge, whether the badge is a ceiling or needs a purchase): written from the parsed
    parts, so the two always agree."""
    parts: list[str] = []
    badge, soft = "", False
    if o.bogo:
        parts.append(o.bogo[:1].upper() + o.bogo[1:])
        m = re.match(r"buy (\d+) get (\d+) (free|(\d+)% off)", o.bogo)
        badge = ("BOGO" if m and m.group(1) == m.group(2) == "1" else f"B{m.group(1)}G{m.group(2)}" if m else "BOGO") + \
            ("" if not m or m.group(3) == "free" else f" {m.group(4)}%")
    if o.pct is not None and o.upto is not None:
        parts.append(f"{o.pct:g}–{_pct(o.upto)} off")
        badge = badge or f"{o.pct:g}–{_pct(o.upto)} off"
    elif o.pct is not None:
        parts.append(f"{_pct(o.pct)} off" + (f" when you buy {o.buy_n}" if o.buy_n else "") +
                     (f" {_usd(o.min_spend)}+" if o.min_spend and o.off is None else ""))
        badge = badge or f"{_pct(o.pct)} off"
    elif o.upto is not None:
        parts.append(f"Up to {_pct(o.upto)} off")
        if not badge and o.extra is None:
            badge, soft = f"Up to {_pct(o.upto)}", True
    if o.extra is not None:
        amount = f"{o.extra:g}–{_pct(o.extra_upto)}" if o.extra_upto else _pct(o.extra)
        parts.append(f"extra {amount} off" if parts else f"Extra {amount} off")
        badge = badge or f"Extra {amount}"
    if o.off is not None:
        if o.reward:
            parts.append(f"Spend {_usd(o.min_spend)}, get {_usd(o.off)} in {o.reward}" if o.min_spend else
                         f"{_usd(o.off)} in {o.reward}")
        else:
            parts.append(("up to " if o.off_upto and parts else "Up to " if o.off_upto else "") + f"{_usd(o.off)} off" +
                         (f" {_usd(o.min_spend)}+" if o.min_spend else "") +
                         (f" when you buy {o.buy_n}" if o.buy_n and o.pct is None else ""))
        if not badge:
            badge, soft = (f"{_usd(o.off)} off" if not o.off_upto else f"Up to {_usd(o.off)}"), True
    text = " + ".join(parts)
    return (text[:1].upper() + text[1:]) if text else "", badge, soft


def rank_pct(o: Offer) -> Optional[float]:
    """What "best deal first" ranks by: what a shopper can count on. A firm percent counts in full and stacks with an
    extra one; an "up to" ceiling counts at half its distance above that; BOGO is its per-item saving; dollars off an
    order of a stated size count as half their share of it (it can be less, never more)."""
    firm = 0.0
    if o.pct is not None:
        firm = o.pct
    if o.bogo_pct is not None:
        firm = max(firm, o.bogo_pct)
    if o.extra is not None:
        firm = 100 * (1 - (1 - firm / 100) * (1 - o.extra / 100))
    best = firm
    if o.upto is not None or o.extra_upto is not None:
        top = o.extra_upto or o.extra
        ceiling = (o.upto or firm) if top is None else 100 * (1 - (1 - (o.upto or o.pct or 0) / 100) * (1 - top / 100))
        best = firm + 0.5 * max(0.0, ceiling - firm)
    if o.off is not None and o.min_spend and not o.off_upto:
        best = max(best, 50 * o.off / o.min_spend)
    return round(best, 1) if best > 0 else None


# --- the code, the conditions, shipping ---------------------------------------------------------------------------
# The cue is any case ("w/ Code SAVE50", "Promo Code FALL15" in Slickdeals' and Hip2Save's titles); an unquoted code
# is still capitals and digits, so the words after a cue ("code at checkout") are not taken for one.
_CODE = re.compile(r"\b(?i:(?:promo|coupon|discount|offer|checkout|savings)?\s?codes?|coupons?(?=\s*[\"']))\s*(?i:of\s+|:\s*|-\s*)?"
                   r"(?:\"\s*([A-Za-z0-9][A-Za-z0-9_-]{2,23})\s*\"|'([A-Za-z0-9][A-Za-z0-9_-]{2,23})'|\*([A-Za-z0-9][A-Za-z0-9_-]{2,23})\*|"
                   r"\b([A-Z0-9][A-Z0-9_-]{3,23})\b)")
_NOT_A_CODE = {"NEEDED", "REQUIRED", "REQUIRED.", "NONE", "AT", "THE", "AND", "FOR", "FREE", "SALE", "DEAL", "DEALS",
               "SHOP", "HERE", "BELOW", "ABOVE", "VALID", "ONLY", "APPLIED", "APPLY", "CHECKOUT", "ONLINE", "STORE",
               "PRIME", "EXTRA", "OFF", "WITH", "USE", "THIS", "THAT", "YOUR", "WILL", "INSTANT", "SAVINGS",
               # the capitals deal sites shout in titles ("w/ Promo Code TODAY ONLY", "*HOT*")
               "TODAY", "HOT", "RARE", "WOW", "NOW", "NEW", "BOGO", "ENDS", "LAST", "SCORE", "HURRY", "BONUS",
               "EXCLUSIVE", "STACK", "STACKS", "PLUS", "SHIPPED", "SHIPPING"}


_CARD = re.compile(r"\bcredit card\b|\bcard ?holders?\b|\bcard ?members?\b|\b(?:store|branded|rewards) (?:credit )?card\b",
                   re.I)
_CODE_NEW = re.compile(r"\bnew (?:\w+ )?(?:customers?|users?|members?|subscribers?)\b|\bfirst (?:order|purchase)\b", re.I)
_CODE_SHIP = re.compile(r"\bshipping\b|\bdelivery\b|\bships\b", re.I)
_CODE_DISCOUNT = re.compile(r"%|\$\s?\d[\d,.]*\s?off\b|\boff\b|\bsave\b|\bdiscount", re.I)


def _sentence(text: str, at: int) -> str:
    start = max(text.rfind(". ", 0, at), text.rfind("! ", 0, at), text.rfind("? ", 0, at))
    ends = [i for i in (text.find(". ", at), text.find("! ", at), text.find("? ", at)) if i >= 0]
    return text[start + 1 if start >= 0 else 0:min(ends) + 1 if ends else len(text)].strip()


def code_of(title: str, text: str, store: Optional[OnlineStore] = None, posted: Optional[date] = None,
            today: Optional[date] = None) -> tuple[str, str, list[str]]:
    """(a promo code the post states, exactly as written; what it is for, when that isn't the discount; conditions
    the code adds). Its own sentence decides: a code for cardholders, for another store, or whose stated day has
    passed is not this sale's code; one that only buys free shipping says so ("no promo code needed" is no code)."""
    full = _straight(f"{title}. {text}")
    for m in _CODE.finditer(full):
        code = next(g for g in m.groups() if g)
        before = full[max(0, m.start() - 12):m.start()].lower()
        # a word in capitals after a cue may be shouting ("Code TODAY ONLY"); a quoted one is the code
        # (dealnews: 'Code "EXTRA" takes an extra 20% off' at Old Navy, Oct 14, 2026)
        if re.search(r"\bno\s*$|\bwithout\s*$", before) or (m.group(4) and code.upper() in _NOT_A_CODE):
            continue
        if not m.group(4) and not re.search(r"[A-Z0-9]", code):    # quoted, but plain words: "code "here""
            continue
        if m.group(4) and not re.search(r"\d", code) and len(code) < 4:
            continue
        said = _sentence(full, m.start())
        if _CARD.search(said):
            continue
        others = [s for _, s, _ in stores_in(said) if not s.brand and (not store or s.key != store.key)]
        if store and others:
            continue
        if posted and today:
            probe = Post(source="", id="", url="", title="", text=said, posted_at=datetime.combine(posted, time(12), CENTRAL))
            _, ends, _ = sale_dates(probe, datetime.combine(posted, time(12), CENTRAL))
            if ends and ends.date() < today:
                continue
        note = ""
        if _CODE_SHIP.search(said) and not _CODE_DISCOUNT.search(said.replace(code, " ")):
            note = "for free delivery" if re.search(r"\bdelivery\b", said, re.I) else "for free shipping"
        return code, note, (["the code is for new customers"] if _CODE_NEW.search(said) else [])
    return "", "", []


_MEMBERS = [
    (re.compile(r"\bw/\s*prime\b|\bprime members?\b|\bfor (?:amazon )?prime\b|\bwith (?:amazon )?prime\b", re.I),
     "Prime members"),
    (re.compile(r"\btarget circle\b|\bcircle (?:members|360|deal)\b", re.I), "Target Circle members (free to join)"),
    (re.compile(r"\bmy best buy\b|\bbest buy members?\b|\bmember deals\b", re.I), "store members"),
    (re.compile(r"\brewards? members?\b|\bloyalty members?\b|\badiclub\b|\bbeauty insider\b|\bulta (?:beauty )?rewards\b", re.I),
     "rewards members (free to join)"),
    (re.compile(r"\bfor members\b|\bmembers only\b|\bmember(?:s)?[- ]exclusive\b|\bplus members\b|\bmember appreciation\b|"
                r"\b\w+ members:", re.I), "members only"),
]
_CONDITIONS = [
    (re.compile(r"\bselect (?:items|styles|products|brands|merchandise|categories)\b|\bon select\b|^select\b", re.I),
     "select items"),
    (re.compile(r"\bmost items\b", re.I), "most items"),
    (re.compile(r"\bw/ exclusions\b|\bexclusions apply\b", re.I), "exclusions apply"),
    (re.compile(r"\bnew (?:customers?|users?|members)\b|\bfirst (?:order|purchase)\b", re.I), "new customers"),
    (re.compile(r"\bin (?:the )?app\b|\bapp[- ]only\b|\bvia (?:the )?app\b|\bapp exclusive\b|\bapp:", re.I), "in the app"),
    (re.compile(r"\bonline[- ]only\b|\bonline exclusive\b", re.I), "online only"),
    (re.compile(r"\btoday[- ]only\b", re.I), "today only"),
    (re.compile(r"\bsubscribe (?:&|and) save\b|\bsub & save\b", re.I), "with Subscribe & Save"),
    (re.compile(r"\bwhile supplies last\b", re.I), "while supplies last"),
    (re.compile(r"\brefurb(?:ished)?\b|\bopen-box\b", re.I), "refurbished or open-box"),
]


def conditions_of(o: Offer, title: str, text: str) -> list[str]:
    """What the discount asks of the shopper, from the title. A post's body names perks that are not conditions of
    the discount ("adiClub members get free shipping"), so only "today only" is also read there."""
    head, offer = split_title(title)
    t = _straight(f"{head} {_SHIP_TAIL.sub('', offer)}")
    out = []
    for rx, label in _MEMBERS:
        if rx.search(t):
            out.append(label)
            break
    for rx, label in _CONDITIONS:
        if rx.search(t) or (label == "today only" and rx.search(_straight(text[:400]))):
            out.append(label)
    if o.min_spend and not o.reward:
        out.append(f"on orders of {_usd(o.min_spend)}+")
    if o.buy_n and o.pct is not None:
        out.append(f"when you buy {o.buy_n}")
    if o.reward:
        out.append(f"paid as a {o.reward}")
    return list(dict.fromkeys(out))


_FREE_SHIP_MIN = re.compile(r"free (?:shipping|s&h|s/h|delivery)\s*(?:on\s+|w/\s*|with\s+|over\s+|on orders? (?:of\s+|over\s+)?)?"
                            r"\$\s?(\d+(?:\.\d\d)?)\+?", re.I)
_FREE_SHIP_WITH = re.compile(r"free (?:shipping|s&h|s/h)\s*(?:w/|with)\s+(prime|[\w+]+ (?:membership|members?)|"
                             r"select purchase|exclusions)", re.I)
_FREE_SHIP = re.compile(r"\bfree (?:prime )?(?:shipping|s&h|s/h)\b|\bships? free\b|\beverything ships free\b", re.I)


def shipping_of(title: str) -> str:
    t = _straight(title)
    m = _FREE_SHIP_MIN.search(t)
    if m:
        return f"Free shipping on {_usd(float(m.group(1)))}+"
    m = _FREE_SHIP_WITH.search(t)
    if m:
        what = m.group(1).lower()
        return "Free shipping with Prime" if what == "prime" else \
            "Free shipping, with exclusions" if what == "exclusions" else \
            "Free shipping on some orders" if what == "select purchase" else f"Free shipping with {m.group(1)}"
    if _FREE_SHIP.search(t):
        return "Free shipping"
    if re.search(r"shipping varies", t, re.I):
        return "Shipping varies"
    m = re.search(r"\+\s*\$(\d+(?:\.\d\d)?)\s+shipping", t)
    return f"{_usd(float(m.group(1)))} shipping" if m else ""


# --- is it a sale at an online store? -----------------------------------------------------------------------------
_NOT_SALE = [
    (re.compile(r"\bgift ?cards?\b|\be-?gift\b", re.I), "a gift card"),
    (re.compile(r"\bmemberships?\b(?!\s+(?:deals|savings|prices?|exclusive|required))", re.I), "a membership"),
    (re.compile(r"\bsubscriptions?\b|\bper month\b|/mo\b|\bmonthly plan\b", re.I), "a subscription"),
    (re.compile(r"\bcredit cards?\b|\bcard ?members?\b|\bcardholders?\b", re.I), "a credit card offer"),
    (re.compile(r"\btrade-?ins?\b", re.I), "a trade-in"),
    (re.compile(r"\bsign-?ups?\b|\bemail sign\b|\bjoin (?:the|our)\b", re.I), "a sign-up offer"),
    (re.compile(r"\b(?:student|teacher|military|healthcare|nurse|first responder|veteran|senior|educator)s?'?\s+"
                r"(?:discount|day|savings|promo)|\bseniors? day\b", re.I), "a discount for a group of people"),
    (re.compile(r"\b(?:flights?|hotels?|cruises?|vacations?|car rentals?|airfare|travel packages?|resorts?)\b", re.I),
     "travel"),
    (re.compile(r"\bsweepstakes\b|\bgiveaways?\b|\binstant win\b", re.I), "a giveaway"),
    (re.compile(r"\bauctions?\b", re.I), "an auction"),
    (re.compile(r"\bhaircuts?\b|\bcar wash\b|\boil change\b|\bdine-?in\b|\brestaurants?\b|\bmovie tickets?\b", re.I),
     "a local service"),
]
_NOT_SHIPPED = [
    (re.compile(r"\+\s*(?:free\s+)?(?:same-day\s+|store\s+)?pickup\b(?!.*\b(?:shipping|s&h)\b)", re.I), "pickup only"),
    (re.compile(r"\bin-?stores? only\b|\bin-?store purchases? only\b|\bavailable in stores\b", re.I), "in stores only"),
    (re.compile(r"\bdigital (?:download|delivery|code|games?|movies?|titles?)\b|\bemail delivery\b|\be-?shop\b|"
                r"\bplaystation store\b|\bxbox store\b|\bsteam\b|\bgoogle play\b|\bapp store\b|\bstreaming\b|"
                r"\bmovies? (?:to own|deals)\b|\bapple tv\b|\bvudu\b|\bfandango at home\b|\bkindle\b|\baudible\b|"
                r"\bebooks?\b|\bsoftware\b|\b\w*vpn\b|\bantivirus\b", re.I), "digital, not shipped"),
]
_SHIPS = re.compile(r"\bshipping\b|\bshipped\b|\bships\b|\bs&h\b|\bdelivery\b|\bdelivered\b", re.I)


def not_a_sale(p: Post, o: Offer, event: bool = False) -> str:
    """Why a post is not a sale at an online store that ships, or "" when it is one. With `event`, a store's own
    event named for a day (StoreSales.sale decides that), which needs no stated discount."""
    t = _straight(p.title)
    main = _ASIDE.sub("", t)
    if p.deal_type == "product":
        return "one product, not a sale"
    if _ROUNDUP.search(t):
        return "a roundup of other deals"
    # what is on sale, not how it ships: "+ free shipping w/ Passport membership" sells no membership
    goods = _SHIP_TAIL.sub("", t)
    # ... and not what comes with it: once the offer is stated, what follows a plus is an extra ("Up to 36% off +
    # trade-in offers", "Up to 50% Off + FREE Gift Card Giveaway!")
    plus = goods.find(" + ")
    if plus > 0 and parse_offer(goods[:plus]).any:
        goods = goods[:plus]
    for rx, why in _NOT_SALE:
        if rx.search(goods) and not (why == "a gift card" and o.reward):
            return why
    for rx, why in _NOT_SHIPPED:
        if rx.search(t):
            return why
    if not o.any and not event:
        return "no discount stated"
    if p.deal_type != "sale" and not _SALE_WORDS.search(main) and o.upto is None and o.extra is None and \
            len(set(re.findall(r"\$\s?(\d[\d,]*(?:\.\d\d)?)", p.text[:600]))) <= 2 and \
            re.search(r"\b(?:just|only|for|now|is|are)\s+\$\s?\d", p.text[:600], re.I):
        # "50% Off Cosequin Supplements": the post prices one bottle ("for $18", "now $38.80 at Belk")
        return "one product, not a sale"
    many = (p.deal_type == "sale" or bool(_SALE_WORDS.search(main)) or o.upto is not None or o.extra is not None or
            bool(o.min_spend) or bool(_SITEWIDE.search(main) or _EVERYTHING.search(main)) or bool(o.buy_n) or
            bool(_CATEGORY_NOUNS.search(main)) or bool(o.bogo))
    one_price = bool(_ONE_PRICE.search(main)) and not _PRICE_HEDGE.search(main)
    if not many or (one_price and o.upto is None and o.extra is None and p.deal_type != "sale"):
        return "one product, not a sale"
    head = split_title(t)[0] or main
    if (o.off is not None and o.pct is None and o.upto is None and o.extra is None and not o.min_spend and not o.bogo
            and not o.off_upto and not _SALE_WORDS.search(head) and not _CATEGORY_NOUNS.search(head)
            and not (_SITEWIDE.search(head) or _EVERYTHING.search(head))):
        return "one product, not a sale"          # "Welax S3 Ergonomic Office Chair: $45 OFF": one chair
    return ""


# --- the sale's name -----------------------------------------------------------------------------------------------
_OFFER_WORDS = re.compile(
    r"\(?\bup\s?to\s+(?:an?\s+)?(?:extra\s+)?\d{1,3}\s?%\s?(?:off)?\)?|\b\d{1,3}\s?%\s?(?:to|-|–)\s?\d{1,3}\s?%\s?off|"
    r"\b(?:extra|additional|another)\s+\d{1,3}\s?%\s?(?:off)?|\b\d{1,3}\s?%\s?off\b|\(?\bup\s?to\s+\$[\d,]+\s?off\)?|"
    r"\$[\d,]+(?:\.\d\d)?\s?off(?:\s+\$[\d,]+\+?)?|\b(?:over|more than|at least)\s+\d{1,3}\s?%\s?off\b|\bbogo\b(?:\s+(?:free|\d{1,3}%\s?off))?|"
    r"\bbuy\s+(?:\d+|one|two),?\s+get\s+(?:\d+|one|two)(?:st|nd|rd|th)?\s+(?:free|\d{1,3}%\s?off|half off)?|"
    r"[=|]\s*(?:styles?|prices?|deals?)\s+(?:from|start\w*\s+at)\s+(?:just\s+)?\$[\d.,]+\w*.*$|"
    r"\b(?:prices?|styles?|deals?|items?)\s+(?:from|starting at)\s+(?:just\s+)?\$[\d.,]+(?:\s+shipped)?", re.I)


# How a headline says where a sale stands, which is no part of its name: "is LIVE", "Starts at 12am CT!", "Start
# 11/22", "End TONIGHT", "NOW", "New deals added". The sale is named before it.
_WHEN = (r"(?:now|today|tonight|tomorrow|soon|(?:on\s+)?\d{1,2}/\d{1,2}|at\s+(?:midnight|\d{1,2}(?::\d\d)?\s?[ap]\.?m\.?)"
         r"(?:\s+[pcme][sd]?t)?|(?:on\s+|this\s+)?(?:mon|tues|wednes|thurs|fri|satur|sun)day)")
_STATUS = re.compile(r"\b(?:is|are)\s+(?:now\s+)?(?:live|here|on|back)\b(?:\s+now\b)?|\blive\s+now\b|\bnow\s+live\b|"
                     r"\blive\s*(?=[|=!(]|$)|"
                     r"\b(?:starts?|begins?|kicks?\s+off|ends?)\s+" + _WHEN + r"\b|\bnew deals added\b|"
                     r"\bnow\b(?=\s*$|\s+(?:to|and|for)\s|\s*[|(!&+–-])|"
                     r"\b(?:going on|happening)\s+now\b", re.I)
_LAST_DAY = re.compile(r"^\s*last\s+(?:day|chance)\s+(?:of|for|to shop)\s+(?:the\s+)?", re.I)


def _named_part(t: str) -> str:
    """A title up to where it says how the sale stands, when a sale is named before that."""
    m = _STATUS.search(t)
    if m and _SALE_NOUNS.search(t[:m.start()]):
        return t[:m.start()]
    return _STATUS.sub(" ", t) if m else t


def event_phrase(title: str) -> str:
    """The sale a title names for a day, in its own words: "Black Friday Deals" of "Want a Peek at Walmart's Black
    Friday Deals? Get Ready to Shop on 11/23!", "Early Black Friday Sale". "" when it names none."""
    t = _straight(title)
    for _, rx, _ in days.DAYS:
        for m in rx.finditer(t):
            before, after = t[:m.start()].split(), re.findall(r"[\w'-]+|[^\w\s]", t[m.end():])
            lead = []
            while before and re.fullmatch(r"early|pre-?|annual|big|official|countdown|to", before[-1], re.I):
                lead.insert(0, before.pop())
            lead = lead[next((i for i, w in enumerate(lead) if not re.fullmatch(r"to", w, re.I)), len(lead)):]
            tail = []
            if _SALE_NOUNS.search(m.group(0)):          # a holiday is matched with its sale: "Halloween Clearance"
                return " ".join(lead + [m.group(0)])
            for w in after[:5]:
                if not re.fullmatch(r"[\w'-]+", w) or not is_store_event(w):
                    break
                tail.append(w)
                if _SALE_NOUNS.fullmatch(w):
                    return " ".join(lead + [m.group(0)] + tail)
    return ""


def sale_name(title: str, store: Optional[OnlineStore], store_name: str) -> str:
    """The sale in a few words, without the store, the offer or shipping: "Deal Days Shoe Sale"."""
    head, _ = split_title(title)
    if head and not _DECOR.sub("", head + ":").strip():      # "Today ONLY: Up to 80% Off ..." names nothing before the offer
        head = ""
    t = head or _straight(title)
    while _ASIDE.search(t):
        t = _ASIDE.sub("", t)
    t = _named_part(_LAST_DAY.sub("", t))
    while _ASIDE.search(t):
        t = _ASIDE.sub("", t)
    t = _FOR_MEMBERS.sub("", _DECOR.sub("", t))
    t = _SHIP_TAIL.sub("", t)
    # dealnews writes the offer after "for": "... Deals for From $15", "... Deals for Up to 40% off + extra 15% off"
    t = re.sub(r"\s+for\s+(?:(?:deals|prices|styles)\s+)?(?:up\s?to\b|an?\s+extra\b|extra\b|from\b|under\b|starting at\b|"
               r"as low as\b|\d{1,3}\s?%|\$\s?\d).*$", "", t, flags=re.I)
    t = re.sub(r"\s+" + _PRICE_NOTE.pattern + r".*$", "", t, flags=re.I)                  # "... Sale Clothing from $10.48"
    t = _OFFER_WORDS.sub(" ", t)
    names = sorted(set((store.names if store else ()) + ((store_name,) if store_name else ())), key=len, reverse=True)
    for n in names:
        n = re.escape(_straight(n))
        t = re.sub(r"\s+(?:at|on|from|via|@)\s+(?:the\s+)?" + n + r"(?:\.com)?(?:'s)?\b", " ", t, flags=re.I)
        t = re.sub(r"(?<![\w&'.-])" + n + r"(?:\.com)?(?:'s)?(?![\w&-])", " ", t, flags=re.I)
    t = _DECOR.sub("", t)
    t = re.sub(r"\s+(?:for|w/|with|on|at|in|from)\s*$", "", re.sub(r"[\s|=+:–—-]+$", "", re.sub(r"^[\s|=+:–—!*-]+", "", t)))
    t = re.sub(r"\s{2,}", " ", t).strip(" ,.;!*?()")
    if _DEAL_SITE_SAID.search(t):               # a headline about the post, not a sale's name
        t = ""
    return t if len(t) >= 3 else ("Sitewide sale" if _SITEWIDE.search(title) else "Sale")


# --- industries ----------------------------------------------------------------------------------------------------
# Words that name a sale event rather than what it sells. A name made only of these ("Deal Days Sale", "Star Deals
# Week", "Friends & Family Sale") is the whole store's sale; a brand or a product left over ("Harry's Prime Big
# Deals", "Cole Haan Star Deals") makes it that brand's or product's sale, placed by the post's own category.
_EVENT_WORDS = re.compile(
    r"\b(?:sales?|deals?|days?|weeks?|weekend|events?|promo(?:tion)?s?|codes?|coupons?|clearance|flash|outlet|specials?|"
    r"savings|offers?|doorbusters?|friends|family|fall|spring|summer|winter|autumn|holidays?|halloween|thanksgiving|"
    r"christmas|black|friday|cyber|monday|labor|memorial|presidents|back|to|school|anniversary|big|top|stars?|daily|"
    r"today|only|members?|appreciation|annual|semi-annual|mega|super|hot|last|chance|hours?|online|exclusive|circle|"
    r"biggest|bigger|mania|"
    r"prime|early|access|countdown|handpicked|popular|picks|rated|price|in|bag|drop|mystery|digital|new|season|end|"
    r"of|the|we|made|too|much|easy|up|extra|sitewide|storewide|site-wide|store-wide|everything|rewards?|vip|"
    r"warehouse|blowout|markdowns?|price-in-bag|limited|time|kickoff|kick|off|and|one-day|two-day|"
    r"shop|now|here|live|is|are|its|it's|score|save|grab|get|huge|rare|more|plus|wow|best|this|these|your|our|all|"
    r"on|at|for|with|w|via|instant|stackable|stacking|flash|weekly|sitewide|"
    r"january|february|march|april|may|june|july|august|september|october|november|december|"
    # the holidays stores name sales after ("Macy's Columbus Day Sale" is the whole store's)
    r"columbus|indigenous|peoples'?|veterans'?|independence|juneteenth|valentine'?s?|easter|mother'?s|father'?s|"
    r"president'?s|patrick'?s|st|year'?s|cinco|mayo|earth|singles'?|boxing|"
    r"wootober|techtober|\d+(?:-day|-hour)?)\b", re.I)


def is_store_event(name: str) -> bool:
    rest = _EVENT_WORDS.sub(" ", re.sub(r"[^\w\s'-]", " ", _straight(name)))
    return not [w for w in rest.split() if len(w) > 1 and not w.isdigit()]


def main_line(store: OnlineStore) -> list[str]:
    """The departments a store-wide event that names no goods counts for: a department store's first two, another
    store's first (the registry lists what a store sells, main line first). The second run's judge put Kohl's and Gap
    Factory's unnamed events under Fashion and Home, not Baby & Kids."""
    return list(store.sells[:2] if len(store.sells) >= 4 else store.sells[:1])


def sale_industries(p: Post, store: Optional[OnlineStore], name: str, sitewide: bool,
                    store_name: str = "") -> tuple[list[str], str]:
    """The industries a sale counts for. A store-wide sale or event counts for what its post names (its category and
    the kinds of goods its words mention), kept to what the store sells; for everything the store sells when the post
    names nothing, or says "sitewide" at a store with a line of its own. Any other sale counts for what the post is
    about, kept to what the store sells. The first live run filed an AliExpress Halloween sale under Pets this way.

    A store the registry doesn't list has no line to keep its sale to, and its own name is not what it sells
    ("Barefoot Dreams Throws" is no wine, "32 Degrees Clothes" no deodorant): the title is read without the name
    first, and with it only when nothing else places the sale ("Up to 60% Off at Mattress Firm")."""
    if store is None and store_name:
        bare = re.sub(r"(?<![\w&'.-])" + re.escape(_straight(store_name)) + r"(?:\.com)?(?:'s)?(?![\w&-])", " ",
                      _straight(p.title), flags=re.I)
        if bare != _straight(p.title):
            inds, rule = sale_industries(replace(p, title=bare), None, name, sitewide)
            if inds:
                return inds, rule
    main = _ASIDE.sub("", _straight(p.title))
    cls = classify_post(replace(p, title=main), learn=False)
    if not cls.industries and p.category:           # a dealnews leaf the category table lacks ("Shaving & Grooming")
        by_words = ind.from_text(p.category)
        cls = ind.Classification(by_words.industries, f"category words: {p.category}", p.category)
    if not cls.industries and not is_store_event(name):     # a department's sale ("Sports Overstock Clearance")
        cls = ind.from_department(name)
    if not cls.industries and p.category:           # the department the source files the post under ("Home Deals & Tips")
        by_dept = ind.from_department(p.category)
        cls = ind.Classification(by_dept.industries, f"category {by_dept.rule}", p.category)
    if not cls.industries:                          # a brand no rule names, by what its labelled goods were; an
        # event's words are no goods' ("Family Size" teaches "family" grocery, but a Friends & Family Sale sells clothes)
        cls = ind.learned(_EVENT_WORDS.sub(" ", main), allowed=store.sells if store else None)
    found = [i for i in cls.industries if i in ONLINE_IDS]
    if cls.rule.startswith("keywords"):
        # a sale on many products counts for every kind of goods its title names ("Up to 85% Off Apparel, Toys")
        found += [i for i in ind.text_industries(main) if i in ONLINE_IDS and i not in found]
    order = lambda xs: [i for i in ONLINE_IDS if i in xs]                                    # noqa: E731
    if store and (sitewide or is_store_event(name)):
        named = [i for i in ind.text_industries(main, p.text[:700]) if i in ONLINE_IDS]
        if cls.rule.startswith(("dealnews:", "category words")):   # the source's own category; feed hints are too broad
            named += found
        evidence = order(set(named))
        if store.sells:
            kept = [] if sitewide else [i for i in evidence if i in store.sells]
            if kept:
                return kept, "a store-wide event: the goods its post names"
            if sitewide:
                return list(store.sells), "sitewide: what the store sells"
            return main_line(store), "a store-wide event: the store's main line"
        return (evidence, "a store-wide event: the goods its post names") if evidence else \
            (list(ONLINE_IDS), "a store-wide event at a store that sells everything")
    if found:
        kept = [i for i in found if not store or not store.sells or i in store.sells]
        if not kept and store and len(store.sells) <= 3:        # "Taco Kit" at Lowe's is still Lowe's home goods
            return list(store.sells[:1]), "the store's own line"
        return order(kept or found), cls.rule
    if store and 0 < len(store.sells) <= 3:
        return list(store.sells[:1]), "the store's own line"
    return [], ""


# --- when -------------------------------------------------------------------------------------------------------
_END_WORDS = (r"(?:ends?|ending|expires?|expiring|through|thru|until|till|valid\s+(?:through|thru|until)|"
              r"good\s+(?:through|thru|until)|runs?\s+(?:through|thru|until)|lasts?\s+(?:through|until))")
# Between the words and the date: "on", a weekday ("through Sunday, 10/19"), a time ("ends at 11:59pm PT on 10/19").
_END_LEAD = (r"\s+(?:at\s+\d{1,2}(?::\d\d)?\s*(?:[ap]\.?m\.?)?\s*(?:[pcme][sd]?t\s+)?on\s+)?(?:on\s+)?"
             r"(?:\w+day,?\s+)?")
_END_MD = re.compile(r"\b" + _END_WORDS + _END_LEAD + _MONTH + r"\s+" + _DAY + r"\b", re.I)
_END_NUM = re.compile(r"\b" + _END_WORDS + _END_LEAD + r"(\d{1,2})/(\d{1,2})(?:/\d{2,4})?(?![\d/])", re.I)
_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
# A weekday and no date ("Sale runs through Sunday", "Hurry, ends Monday!"): that day, this week.
_END_DAY = re.compile(r"\b" + _END_WORDS + r"\s+(?:this\s+)?(" + "|".join(_WEEKDAYS) + r")\b(?![,\s]*(?:\d|" +
                      _MONTH + r"))", re.I)
_START_MD = re.compile(r"\b(?:starts?|starting|begins?|beginning|kicks? off|launch(?:es)?)\s+(?:on\s+)?(?:\w+day,?\s+)?" +
                       _MONTH + r"\s+" + _DAY + r"\b", re.I)
_ONLY_MD = re.compile(r"\b(?:today,?\s+)?(?:\w+day,?\s+)?" + _MONTH + r"\s+" + _DAY + r",?\s+only\b", re.I)
_TODAY_ONLY = re.compile(r"\btoday[- ]only\b|\bends? today\b|\bends? tonight\b|\bone[- ]day (?:only|sale)\b|"
                         r"\b1-day sale\b", re.I)
_LAST_DAY_SAID = re.compile(r"\blast day\b", re.I)          # in a headline; a body's "last day to order" is another day
# A start a headline gives in figures or by the clock: "Deals Start 11/22", "Get Ready to Shop on 11/23", "Starts
# Monday", "Starts at 12am CT". Read in the title only: a body's other dates are about other things.
_START_NUM = re.compile(r"\b(?:starts?|starting|begins?|beginning|kicks? off|launch(?:es)?|shop)\s+(?:on\s+)?(?:\w+day,?\s+)?"
                        r"(\d{1,2})/(\d{1,2})(?:/\d{2,4})?(?![\d/])", re.I)
_START_DAY = re.compile(r"\b(?:starts?|begins?|kicks? off)\s+(?:on\s+|this\s+)?(" + "|".join(_WEEKDAYS) + r")\b", re.I)
_START_NEXT = re.compile(r"\b(?:starts?|begins?|kicks? off)\s+(?:tomorrow\b|tonight\b|at\s+(?:midnight|12\s?a\.?m\.?))", re.I)


def _end_of(d: date) -> datetime:
    return datetime.combine(d, time(23, 59, 59), CENTRAL)


def sale_dates(p: Post, now: datetime) -> tuple[Optional[datetime], Optional[datetime], str]:
    """(starts, ends, where the end comes from). The source's own end comes first: dealnews' expiry when an editor
    set it (sources/feeds.dealnews_stated). Then the post's words: a date range, "ends/through/until <date>",
    "today only". Dates in words end at 11:59 PM Central on that day; a year is the one nearest the post."""
    posted = (p.posted_at or now).astimezone(CENTRAL).date()
    title, body = _straight(p.title), _straight(p.text[:900])
    text = f"{title}. {body}"
    start = end = None
    how = ""

    def ranged(where: str) -> Optional[tuple[date, date, str]]:
        m = _RANGE_MD.search(where)
        if m:
            m1 = _MONTHS[m.group(1)[:3].lower()]
            m2 = _MONTHS[m.group(3)[:3].lower()] if m.group(3) else m1
            a, b = _date(m1, int(m.group(2)), posted), _date(m2, int(m.group(4)), posted)
        else:
            m = _RANGE_NUM.search(where)
            a, b = (_date(int(m.group(1)), int(m.group(2)), posted), _date(int(m.group(3)), int(m.group(4)), posted)) \
                if m else (None, None)
        return (a, b, f"the post says “{m.group(0).strip()}”") if a and b and a <= b <= a + timedelta(days=62) else None

    def ending(where: str) -> Optional[tuple[date, str]]:
        m = _END_MD.search(where)
        if m:
            return _date(_MONTHS[m.group(1)[:3].lower()], int(m.group(2)), posted), f"the post says “{m.group(0).strip()}”"
        m = _END_NUM.search(where)
        if m and 1 <= int(m.group(1)) <= 12 and 1 <= int(m.group(2)) <= 31:
            return _date(int(m.group(1)), int(m.group(2)), posted), f"the post says “{m.group(0).strip()}”"
        # "Monday through Friday" is a span of weekdays, not an end
        m = next((m for m in _END_DAY.finditer(where) if not re.search(r"day\s*$", where[:m.start()], re.I)), None)
        if m:
            ahead = (_WEEKDAYS.index(m.group(1).lower()) - posted.weekday()) % 7
            return posted + timedelta(days=ahead), f"the post says “{m.group(0).strip()}”"
        return None

    # The title first, then an end the body states in words, then a range in the body: a body can carry other dates
    # ("earn Kohl's Cash, redeemable October 9–19") after the sale's own ("Through October 8th, ...").
    r = ranged(title)
    if r:
        start, end, how = r
    else:
        e = ending(title) or ending(body)
        if e:
            end, how = e
        else:
            r = ranged(body)
            if r:
                start, end, how = r
    if end is None:
        m = _ONLY_MD.search(text)
        if m:
            end, how = _date(_MONTHS[m.group(1)[:3].lower()], int(m.group(2)), posted), f"the post says “{m.group(0).strip()}”"
    if end is None and (_TODAY_ONLY.search(text) or _LAST_DAY_SAID.search(title)):
        end, how = posted, "the post says “today only”"
    explicit = False
    if start is None:
        m = _START_MD.search(text)
        if m:
            start, explicit = _date(_MONTHS[m.group(1)[:3].lower()], int(m.group(2)), posted), True
    if start is None:
        m = _START_NUM.search(title)
        if m and 1 <= int(m.group(1)) <= 12 and 1 <= int(m.group(2)) <= 31:
            start, explicit = _date(int(m.group(1)), int(m.group(2)), posted), True
    if start is None:
        m = _START_DAY.search(title)
        if m:                                      # the next such day after the post
            start, explicit = posted + timedelta(days=(_WEEKDAYS.index(m.group(1).lower()) - posted.weekday()) % 7 or 7), True
        elif _START_NEXT.search(title):            # the midnight after the post
            late = (p.posted_at or now).astimezone(CENTRAL).hour >= 2
            start, explicit = posted + timedelta(days=1 if late else 0), True
    if p.expires_stated and p.expires_at:
        # The source's own end wins; a range in the words may be about something else ("Kohl's Cash, redeemable
        # October 9–19"), so only a stated start before that end is kept.
        stated = p.expires_at.astimezone(CENTRAL).date()
        keep = start and explicit and posted < start <= stated
        return (datetime.combine(start, time(0, 0), CENTRAL) if keep else None, p.expires_at,
                f"{SOURCE_NAMES.get(p.source, p.source)} gives this end date")
    starts = datetime.combine(start, time(0, 0), CENTRAL) if start and start > posted and (not end or start <= end) else None
    if end and end < posted - timedelta(days=1):       # a date before the post is not this sale's end
        end, how = None, ""
    return starts, (_end_of(end) if end else None), how


# --- the pipeline --------------------------------------------------------------------------------------------------
def sale_plans() -> list[FeedPlan]:
    """The feeds read for sales: every online industry's (shared with the Online tab), each registry store's own
    dealnews feed, dealnews' latest and popular posts, and Slickdeals' sitewide sales."""
    out = plan(list(ONLINE_IDS))
    for s in registry():
        if s.dealnews:
            out.append(FeedPlan("dealnews", f"dealnews store {s.dealnews.split('/')[1]}",
                                f"https://www.dealnews.com/s{s.dealnews}/?rss=1", []))
    out += [FeedPlan("dealnews", "dealnews latest", "https://www.dealnews.com/?rss=1&sort=time", []),
            FeedPlan("dealnews", "dealnews popular", "https://www.dealnews.com/?rss=1&sort=hotness", [])]
    # Hip2Save's own front page: the posts it files under no category Slomp reads, a store's event among them
    # ("Target's Black Friday Deals Start 11/22"). Read on past its first page like every feed (DealFeeds.read).
    out.append(FeedPlan("hip2save", "hip2save latest", "https://hip2save.com/feed/", []))
    for q in ("sitewide", "storewide"):
        out.append(FeedPlan("slickdeals", f"slickdeals q={q}",
                            f"https://slickdeals.net/newsearch.php?mode=frontpage&searcharea=deals&searchin=first&rss=1&q={q}",
                            []))
    return out


@dataclass
class SalesResult:
    sales: list[StoreSale] = field(default_factory=list)       # every sale not yet ended when it was computed
    excluded: Counter = field(default_factory=Counter)
    sources: list[dict] = field(default_factory=list)
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    stores: dict = field(default_factory=dict)          # stores_payload() when computed: the page's store list
    left_out: dict[str, dict[str, str]] = field(default_factory=dict)   # reason -> the posts left out for it


def live_reason(s: StoreSale, now: datetime) -> str:
    """Why a sale is not shown at this moment, or "" when it is (docs/DESIGN-online-stores.md 4.4)."""
    if s.ends_at and s.ends_at < now:
        return "sale: ended"
    if s.posted_at and now - s.posted_at > timedelta(days=POSTED_DAYS):
        return f"sale: posted over {POSTED_DAYS} days ago"
    if not s.ends_at and (not s.posted_at or now - s.posted_at > timedelta(days=UNDATED_DAYS)) and \
            not (s.event_ends_at and now <= s.event_ends_at):       # a sale named for a day lasts through it
        return f"sale: no end date and posted over {UNDATED_DAYS} days ago"
    if s.starts_at and s.starts_at > now + timedelta(days=AHEAD_DAYS):
        return f"sale: starts after the next {AHEAD_DAYS} days"
    return ""


def select(res: SalesResult, industries: Iterable[str], now: Optional[datetime] = None) -> tuple[list[StoreSale], Counter]:
    """The sales a search shows: live at `now`, in the chosen industries, best first."""
    now = now or datetime.now(timezone.utc)
    wanted = set(industries)
    excluded = Counter(dict(res.excluded.most_common()))       # in the order the published site's file keeps
    out = []
    for s in res.sales:
        why = live_reason(s, now)
        if why:
            excluded[why] += 1
        elif not wanted & set(s.industries):
            excluded["sale: other industry"] += 1
        else:
            out.append(s)
    out.sort(key=lambda s: (-s.score, s.ends_at or datetime.max.replace(tzinfo=timezone.utc), s.store_name.lower(), s.id))
    return out, excluded


def stores_payload() -> dict[str, dict]:
    """Every registry store as the page needs it: name, site, the names deal sites use, what it sells, its logo."""
    from .regulars import _logos                              # logos.json, shared with regular deals
    logos = _logos()
    out = {}
    for s in registry():
        icon, mark = logos.get(f"o:{s.key}"), logos.get(f"ow:{s.key}")
        pick = lambda *xs: next(({"url": x["url"], "fit": x.get("fit", "contain")} for x in xs if x and x.get("url")), None)
        # `logo` for a store's tile (its wordmark, else its icon); `icon` (square) and `mark` (wide) for the corner of
        # a sale's picture
        out[s.key] = {"name": s.name, "site": s.site, "names": list(s.names), "sells": list(s.sells),
                      "logo": pick(mark, icon), "icon": pick(icon), "mark": pick(mark)}
    return out


def to_payload(res: SalesResult, industries: list[str], now: Optional[datetime] = None) -> dict:
    """The API's /api/v1/sales answer (and the `sales` part of /api/v1/search)."""
    now = now or datetime.now(timezone.utc)
    shown, excluded = select(res, industries, now)
    return {"industries": industries, "generated_at": res.generated_at.isoformat(),
            "sales": [s.to_dict() for s in shown],
            "counts": {"sales": len(shown), "stores": len({s.store or s.store_name for s in shown})},
            "stores": res.stores or stores_payload(), "excluded": dict(excluded.most_common()), "sources": res.sources}


class StoreSales:
    def __init__(self, feeds: DealFeeds, http: PoliteClient, db=None):
        self.feeds, self.http, self.db = feeds, http, db

    async def run(self, now: Optional[datetime] = None, check: bool = True) -> SalesResult:
        now = now or datetime.now(timezone.utc)
        res = SalesResult(generated_at=now)
        plans = sale_plans()
        got = await asyncio.gather(*(self.feeds.read(p) for p in plans))
        posts: dict[str, Post] = {}
        for p, (items, err) in zip(plans, got):
            if err == "HTTP 404" and p.name.startswith("dealnews store"):
                err = ""                                   # a store dealnews no longer lists: nothing to read, not a fault
            res.sources.append({"name": p.name, "ok": not err, "posts": len(items), **({"error": err} if err else {})})
            for post in items:
                have = posts.get(post.id)
                if have:                                   # the same post in two feeds: one post, both feeds' hints
                    have.feeds += [f for f in post.feeds if f not in have.feeds]
                    have.feed_industries += [i for i in post.feed_industries if i not in have.feed_industries]
                else:
                    posts[post.id] = post
        if self.db:
            self.db.label(labelled_posts(posts.values()))
        candidates = []
        for p in posts.values():
            before = res.excluded.copy()
            s = self.sale(p, now, res.excluded)
            if s is not None:
                candidates.append(s)
            else:
                why = res.excluded - before
                note_left_out(res.left_out, why, p, store_evidence(p) if "sale: store not identified" in why else "")
        candidates = dedupe(candidates, res.excluded)
        if check:
            await self._check(candidates, res.excluded)
            candidates = [s for s in candidates if not s.raw.get("gone")]
        res.sales = sorted(candidates, key=lambda s: (-s.score, s.store_name.lower(), s.id))
        res.stores = stores_payload()
        return res

    # -- one post -----------------------------------------------------------------------------------------------
    def sale(self, p: Post, now: datetime, excluded: Counter) -> Optional[StoreSale]:
        o = parse_offer(p.title)
        main = _ASIDE.sub("", _straight(p.title))
        offer_how = ""
        if not o.any and names_a_sale(main) and (not _ONE_PRICE.search(main) or _PRICE_HEDGE.search(main)):
            o, said = said_offer(p)          # the title names a sale and not its discount: the post's own sentence
            offer_how = f"the post says “{said[:200]}”" if o.any else ""
        why = not_a_sale(p, o)
        # A sale named for a day, with no discount stated anywhere: whether it is the store's own event is decided
        # below, once the store and the sale's name are known.
        headline = why == "no discount stated" and bool(days.named(main)) and bool(_SALE_NOUNS.search(main))
        if headline:
            why = not_a_sale(p, o, event=True)
        if why:
            excluded[f"not a store sale: {why}"] += 1
            return None
        store, how = find_store(p)
        name, called = store.name if store else "", ""
        if not store and p.source == "dealnews" and p.seller and not _DEAL_SITES.match(p.seller.strip()):
            name, how = clean(p.seller), "dealnews' retailer field"
            if not _SHIPS.search(f"{p.title} {p.text[:600]}"):
                excluded["sale: the post doesn't say the store ships"] += 1
                return None
        elif not store:
            name, how = named_store(p)
            if not name:
                store, how, called = store_of_sale(p)
                name = store.name if store else ""
        if not name:
            excluded["sale: store not identified"] += 1
            return None
        title = clean(p.title)
        sname = called or sale_name(title, store, name)       # as the post's own words call the store's sale
        note = ""
        if headline:
            # The store's own event ("Kohl's Black Friday Sale Starts at 12am CT!", "Want a Peek at Walmart's Black
            # Friday Deals?") or a sale that gives a price in place of a discount ("... Deals for From $15"). A day's
            # name on anything else ("Black Friday Buckets") states no discount and names no sale of the store's.
            note, phrase = price_note(title), event_phrase(main)
            own = phrase and re.search(r"(?:^|[\s(])" + re.escape(_straight(name)) + r"(?:\.com)?(?:'s|')?\s+(?:\w+\s+)?$",
                                       main[:main.find(phrase)] + " ", re.I)
            if not is_store_event(sname) and own:
                sname = phrase
            if not (is_store_event(sname) or note):
                excluded["not a store sale: no discount stated"] += 1
                return None
            aside = aside_of(p.title)                 # the one price an event's title gives beside its name:
            if not note and len(re.findall(r"\$\s?\d", aside)) == 1:    # "... = Popular Styles from $29 Shipped"
                note = price_note(aside)
        starts, ends, ends_how = sale_dates(p, now)
        posted = (p.posted_at or now).astimezone(CENTRAL).date()
        # The day the sale is named for. With no end stated it lasts through that day, unless it is named as the wave
        # before it ("Early Black Friday Sale"), which ends some day before.
        day = days.day_of(main, posted)
        through = _end_of(day[1]) if day and not ends and not days.BEFORE.search(main) else None
        if ends and ends < now:
            excluded["sale: ended"] += 1
            return None
        if p.posted_at and now - p.posted_at > timedelta(days=POSTED_DAYS):
            excluded[f"sale: posted over {POSTED_DAYS} days ago"] += 1
            return None
        if not ends and (not p.posted_at or now - p.posted_at > timedelta(days=UNDATED_DAYS)) and \
                not (through and now <= through):
            excluded[f"sale: no end date and posted over {UNDATED_DAYS} days ago"] += 1
            return None
        sitewide = bool(_SITEWIDE.search(title)) or (bool(_EVERYTHING.search(title)) and is_store_event(sname))
        inds, rule = sale_industries(p, store, sname, sitewide, name)
        if not inds:
            excluded["sale: no industry"] += 1
            return None
        text, badge, soft = offer_text(o)
        if not text:                    # an event with no discount stated: the price it gives instead, or that it is on
            text, badge, soft = (note, note, True) if note else (EVENT_OFFER, EVENT_BADGE, True)
        conditions = conditions_of(o, title, p.text)
        code, code_note, code_conditions = code_of(p.title, p.text, store, posted, now.astimezone(CENTRAL).date())
        conditions += [c for c in code_conditions if c not in conditions]
        if sitewide and "most items" not in conditions:
            conditions.insert(0, "sitewide")
        r = rank_pct(o)
        weight = 1.0 - 0.1 * any(c.endswith("members") or c == "members only" for c in conditions) \
            - 0.1 * ("select items" in conditions)
        source = SOURCE_NAMES.get(p.source, p.source)
        return StoreSale(
            id=f"sale:{p.id}", store=store.key if store else "", store_name=name, title=title, name=sname, offer=text,
            badge=badge, badge_soft=soft, pct=o.pct, upto=o.upto, extra=o.extra, off=o.off, off_upto=o.off_upto, min_spend=o.min_spend,
            extra_upto=o.extra_upto, bogo=o.bogo, bogo_pct=o.bogo_pct, code=code, code_note=code_note,
            conditions=conditions,
            shipping=shipping_of(title), sitewide=sitewide, starts_at=starts, ends_at=ends, ends_how=ends_how,
            event=day[0] if day else "", event_ends_at=through, offer_how=offer_how,
            posted_at=p.posted_at, source=source, source_url=p.url, image_url=p.image,
            industries=inds, industry_rule=rule, discount_pct=r,
            score=round((r or 0.0) * weight, 2), raw={"feeds": p.feeds, "store_how": how, "text": p.text[:1500]})

    async def _check(self, sales: list[StoreSale], excluded: Counter) -> None:
        """Read each sale's post page again and drop the ones taken down, sent elsewhere or marked expired."""
        async def one(s: StoreSale) -> None:
            if s.source == "DealCatcher":               # behind a bot wall
                return
            try:
                page = await self.http.get(s.source_url, ttl_s=TTL["page"], html=True)
            except FetchError:
                return
            why = "the post was removed (404)" if page.status == 404 else \
                post_gone(s.source_url, page.final_url, page.text, s.title) if page.status == 200 else ""
            if why:
                s.raw["gone"] = why
                excluded["sale: post removed or marked expired"] += 1
            elif page.status == 200:
                s.checked_at = datetime.fromtimestamp(page.fetched_at, timezone.utc)
        await asyncio.gather(*(one(s) for s in sales))


# --- duplicates ----------------------------------------------------------------------------------------------------
_STOP = {"the", "and", "on", "at", "for", "of", "in", "with", "sale", "deals", "deal", "off", "up", "to", "extra", "+",
         "&", "free", "shipping", "a", "an", "from", "your", "all"}


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in _STOP and not w.isdigit()}


def dedupe(sales: list[StoreSale], excluded: Counter) -> list[StoreSale]:
    """The same sale posted twice (dealnews and Hip2Save both cover Kohl's Deal Days): same store, same offer, same
    end, and names that share most of their words. The best-sourced post leads; the others are listed with it."""
    rank = {s: k for k, s in enumerate(SOURCE_ORDER)}
    ordered = sorted(sales, key=lambda s: (rank.get(s.source, 99), not s.code, s.posted_at or datetime.max.replace(tzinfo=timezone.utc)))
    kept: list[StoreSale] = []
    for s in ordered:
        same = None
        for k in kept:
            if (k.store or k.store_name) != (s.store or s.store_name) or k.badge != s.badge:
                continue
            if (k.ends_at.date() if k.ends_at else None) != (s.ends_at.date() if s.ends_at else None):
                continue
            if bool(days.BEFORE.search(k.name)) != bool(days.BEFORE.search(s.name)):
                continue                          # the wave before a day and the day's own sale are two sales
            a, b = _words(k.name), _words(s.name)
            if a == b or (a and b and len(a & b) / min(len(a), len(b)) >= 0.6):
                same = k
                break
        if same:
            same.also_posted.append({"source": s.source, "url": s.source_url, "title": s.title})
            if not same.code and s.code:
                same.code = s.code
            excluded["sale: same sale posted elsewhere"] += 1
        else:
            kept.append(s)
    # An event's headline with no discount stated ("Amazon's Black Friday Sale Is Live") adds nothing to a sale of
    # the same store, named for the same day, that states one.
    stated = lambda s: any(v is not None for v in (s.pct, s.upto, s.extra, s.off)) or bool(s.bogo)   # noqa: E731
    out: list[StoreSale] = []
    for s in kept:
        better = None if stated(s) or not s.event else next(
            (k for k in kept if k is not s and stated(k) and k.event == s.event
             and (k.store or k.store_name) == (s.store or s.store_name)), None)
        if better:
            better.also_posted.append({"source": s.source, "url": s.source_url, "title": s.title})
            excluded["sale: same sale posted elsewhere"] += 1
        else:
            out.append(s)
    return out


