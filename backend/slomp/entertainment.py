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
"""
from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Optional

from .models import StoreSale
from .reference import DATA, norm
from .sources.feeds import SOURCE_NAMES, FeedPlan, Post, dealnews_url
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
