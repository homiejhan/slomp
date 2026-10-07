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

from zoneinfo import ZoneInfo

from . import industries as ind
from .config import TTL
from .http import FetchError, PoliteClient
from .models import OnlineStore, StoreSale
from .online import classify_post
from .promos import _DAY, _MONTH, _MONTHS, _RANGE_MD, _RANGE_NUM, _date
from .sources.feeds import SOURCE_NAMES, DealFeeds, FeedPlan, Post, plan, post_gone
from .stores_online import _straight, registry, store_named, stores_in
from .terms import bogo_of, clean

CENTRAL = ZoneInfo("America/Chicago")
POSTED_DAYS = 30           # a sale posted longer ago than this is not shown, whatever end it states (evergreen coupons)
UNDATED_DAYS = 7           # a sale with no end is shown this long after it was posted
AHEAD_DAYS = 7             # a sale that starts later than this is not shown yet
SOURCE_ORDER = ("dealnews", "Slickdeals", "Hip2Save", "9to5Toys", "The Inventory", "Ben's Bargains", "DealCatcher")
ONLINE_IDS = tuple(i for i in ind.IDS if ind.BY_ID[i].online)


_PLACE = re.compile(r"\b(?:at|on|from|via|@)\s+(?:the\s+)?(?:official\s+)?((?:[A-Z]|[a-z](?=[A-Z]))[\w&'.!-]*(?:\s+(?:[A-Z&]|[a-z](?=[A-Z]))[\w&'.!-]*){0,3})")
_SENT_TO = re.compile(r"\b(?i:head|hop|run|dash|scoot|hurry|go|swing|zip|pop|race)(?i:\s+on)?(?i:\s+over)?\s+(?i:to)\s+(?:the\s+)?"
                      r"(?:official\s+|online\s+)?((?:[A-Z]|[a-z](?=[A-Z]))[\w&'.!-]*(?:\s+(?:[A-Z&]|[a-z](?=[A-Z]))[\w&'.!-]*){0,3})")


def _shop_in(phrase: str) -> Optional[OnlineStore]:
    """The store a phrase names: "the official Crocs eBay Store" is eBay, where Crocs, a brand, has a shop."""
    named = stores_in(phrase)
    shops = [s for _, s, _ in named if not s.brand]
    return shops[0] if shops else store_named(phrase)


# Deal sites name themselves as the retailer of their own roundups ("The Best Amazon Prime Big Deal Days Deals").
_DEAL_SITES = re.compile(r"^(?:deal ?news|slickdeals|hip2save|9to5toys|the inventory|ben'?s bargains|dealcatcher|"
                         r"the krazy coupon lady|krazy coupon lady)$", re.I)


def find_store(p: Post) -> tuple[Optional[OnlineStore], str]:
    """The registry store a sale post is at, and how that was decided ("" when no registry store is)."""
    title, text = _straight(p.title), _straight(p.text[:900])
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
_OFF = re.compile(r"(\bup\s?to\s+|\$\s?\d[\d,]*\s?(?:to|-|–)\s?)?\$\s?(\d[\d,]*(?:\.\d\d)?)\s?off\b(?:\s+(?:your\s+|an?\s+|orders?\s+(?:of\s+)?|"
                  r"purchases?\s+(?:of\s+)?|when you spend\s+|every\s+)?\$\s?(\d[\d,]*)\+?)?", re.I)
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


def parse_offer(title: str) -> Offer:
    t = re.sub(r"\(([^()]*%[^()]*)\)", r" \1 ", offer_part(title))      # "(Up to 64% off)"
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
        parts.append(f"{_pct(o.pct)} off" + (f" when you buy {o.buy_n}" if o.buy_n else ""))
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
_CODE = re.compile(r"\b(?:promo|coupon|discount|offer|checkout|savings)?\s?codes?\s*(?:of\s+|:\s*|-\s*)?"
                   r"(?:\"\s*([A-Za-z0-9][A-Za-z0-9_-]{2,23})\s*\"|'([A-Za-z0-9][A-Za-z0-9_-]{2,23})'|\*([A-Za-z0-9][A-Za-z0-9_-]{2,23})\*|"
                   r"\b([A-Z0-9][A-Z0-9_-]{3,23})\b)")
_NOT_A_CODE = {"NEEDED", "REQUIRED", "REQUIRED.", "NONE", "AT", "THE", "AND", "FOR", "FREE", "SALE", "DEAL", "DEALS",
               "SHOP", "HERE", "BELOW", "ABOVE", "VALID", "ONLY", "APPLIED", "APPLY", "CHECKOUT", "ONLINE", "STORE",
               "PRIME", "EXTRA", "OFF", "WITH", "USE", "THIS", "THAT", "YOUR", "WILL", "INSTANT", "SAVINGS"}


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
        if re.search(r"\bno\s*$|\bwithout\s*$", before) or code.upper() in _NOT_A_CODE:
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
    (re.compile(r"\+\s*(?:free\s+)?(?:store\s+)?pickup\b(?!.*\b(?:shipping|s&h)\b)", re.I), "pickup only"),
    (re.compile(r"\bin-?stores? only\b|\bin-?store purchases? only\b|\bavailable in stores\b", re.I), "in stores only"),
    (re.compile(r"\bdigital (?:download|delivery|code|games?|movies?|titles?)\b|\bemail delivery\b|\be-?shop\b|"
                r"\bplaystation store\b|\bxbox store\b|\bsteam\b|\bgoogle play\b|\bapp store\b|\bstreaming\b|"
                r"\bmovies? (?:to own|deals)\b|\bapple tv\b|\bvudu\b|\bfandango at home\b|\bkindle\b|\baudible\b|"
                r"\bebooks?\b|\bsoftware\b|\bvpn\b|\bantivirus\b", re.I), "digital, not shipped"),
]
_SHIPS = re.compile(r"\bshipping\b|\bshipped\b|\bships\b|\bs&h\b|\bdelivery\b|\bdelivered\b", re.I)


def not_a_sale(p: Post, o: Offer) -> str:
    """Why a post is not a sale at an online store that ships, or "" when it is one."""
    t = _straight(p.title)
    main = _ASIDE.sub("", t)
    if p.deal_type == "product":
        return "one product, not a sale"
    if _ROUNDUP.search(t):
        return "a roundup of other deals"
    for rx, why in _NOT_SALE:
        if rx.search(t) and not (why == "a gift card" and o.reward):
            return why
    for rx, why in _NOT_SHIPPED:
        if rx.search(t):
            return why
    if not o.any:
        return "no discount stated"
    if p.deal_type != "sale" and not _SALE_WORDS.search(main) and o.upto is None and o.extra is None and \
            len(set(re.findall(r"\$\s?(\d[\d,]*(?:\.\d\d)?)", p.text[:600]))) <= 2 and \
            re.search(r"\b(?:just|only|for)\s+\$\s?\d", p.text[:600], re.I):
        return "one product, not a sale"         # "50% Off Cosequin Supplements": the post prices one bottle
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


def sale_name(title: str, store: Optional[OnlineStore], store_name: str) -> str:
    """The sale in a few words, without the store, the offer or shipping: "Deal Days Shoe Sale"."""
    head, _ = split_title(title)
    t = head or _straight(title)
    while _ASIDE.search(t):
        t = _ASIDE.sub("", t)
    t = _FOR_MEMBERS.sub("", _DECOR.sub("", t))
    t = _SHIP_TAIL.sub("", t)
    t = _OFFER_WORDS.sub(" ", t)
    names = sorted(set((store.names if store else ()) + ((store_name,) if store_name else ())), key=len, reverse=True)
    for n in names:
        n = re.escape(_straight(n))
        t = re.sub(r"\s+(?:at|on|from|via|@)\s+(?:the\s+)?" + n + r"(?:\.com)?(?:'s)?\b", " ", t, flags=re.I)
        t = re.sub(r"(?<![\w&'.-])" + n + r"(?:\.com)?(?:'s)?(?![\w&-])", " ", t, flags=re.I)
    t = _DECOR.sub("", t)
    t = re.sub(r"\s+(?:for|w/|with|on|at|in|from)\s*$", "", re.sub(r"[\s|=+:–—-]+$", "", re.sub(r"^[\s|=+:–—!*-]+", "", t)))
    t = re.sub(r"\s{2,}", " ", t).strip(" ,.;!*")
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
    r"prime|early|access|countdown|handpicked|popular|picks|rated|price|in|bag|drop|mystery|digital|new|season|end|"
    r"of|the|we|made|too|much|easy|up|extra|sitewide|storewide|site-wide|store-wide|everything|rewards?|vip|"
    r"warehouse|blowout|markdowns?|price-in-bag|limited|time|kickoff|kick|off|and|one-day|two-day|"
    r"shop|now|here|live|is|are|its|it's|score|save|grab|get|huge|rare|more|plus|wow|best|this|these|your|our|all|"
    r"on|at|for|with|w|via|instant|stackable|stacking|flash|weekly|sitewide|"
    r"january|february|march|april|may|june|july|august|september|october|november|december|"
    r"wootober|techtober|\d+(?:-day|-hour)?)\b", re.I)


def is_store_event(name: str) -> bool:
    rest = _EVENT_WORDS.sub(" ", re.sub(r"[^\w\s'-]", " ", _straight(name)))
    return not [w for w in rest.split() if len(w) > 1 and not w.isdigit()]


def main_line(store: OnlineStore) -> list[str]:
    """The departments a store-wide event that names no goods counts for: a department store's first two, another
    store's first (the registry lists what a store sells, main line first). The second run's judge put Kohl's and Gap
    Factory's unnamed events under Fashion and Home, not Baby & Kids."""
    return list(store.sells[:2] if len(store.sells) >= 4 else store.sells[:1])


def sale_industries(p: Post, store: Optional[OnlineStore], name: str, sitewide: bool) -> tuple[list[str], str]:
    """The industries a sale counts for. A store-wide sale or event counts for what its post names (its category and
    the kinds of goods its words mention), kept to what the store sells; for everything the store sells when the post
    names nothing, or says "sitewide" at a store with a line of its own. Any other sale counts for what the post is
    about, kept to what the store sells. The first live run filed an AliExpress Halloween sale under Pets this way."""
    main = _ASIDE.sub("", _straight(p.title))
    cls = classify_post(replace(p, title=main))
    if not cls.industries and p.category:           # a dealnews leaf the category table lacks ("Shaving & Grooming")
        by_words = ind.from_text(p.category)
        cls = ind.Classification(by_words.industries, f"category words: {p.category}", p.category)
    found = [i for i in cls.industries if i in ONLINE_IDS]
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
_END_MD = re.compile(r"\b" + _END_WORDS + r"\s+(?:on\s+)?(?:\w+day,?\s+)?" + _MONTH + r"\s+" + _DAY + r"\b", re.I)
_END_NUM = re.compile(r"\b" + _END_WORDS + r"\s+(?:on\s+)?(\d{1,2})/(\d{1,2})(?:/\d{2,4})?(?![\d/])", re.I)
_START_MD = re.compile(r"\b(?:starts?|starting|begins?|beginning|kicks? off|launch(?:es)?)\s+(?:on\s+)?(?:\w+day,?\s+)?" +
                       _MONTH + r"\s+" + _DAY + r"\b", re.I)
_ONLY_MD = re.compile(r"\b(?:today,?\s+)?(?:\w+day,?\s+)?" + _MONTH + r"\s+" + _DAY + r",?\s+only\b", re.I)
_TODAY_ONLY = re.compile(r"\btoday[- ]only\b|\bends today\b|\bends tonight\b|\bone[- ]day (?:only|sale)\b|\b1-day sale\b",
                         re.I)


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
    if end is None and _TODAY_ONLY.search(text):
        end, how = posted, "the post says “today only”"
    if start is None:
        m = _START_MD.search(text)
        if m:
            start = _date(_MONTHS[m.group(1)[:3].lower()], int(m.group(2)), posted)
    explicit = bool(_START_MD.search(text))
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


def live_reason(s: StoreSale, now: datetime) -> str:
    """Why a sale is not shown at this moment, or "" when it is (docs/DESIGN-online-stores.md 4.4)."""
    if s.ends_at and s.ends_at < now:
        return "sale: ended"
    if s.posted_at and now - s.posted_at > timedelta(days=POSTED_DAYS):
        return f"sale: posted over {POSTED_DAYS} days ago"
    if not s.ends_at and (not s.posted_at or now - s.posted_at > timedelta(days=UNDATED_DAYS)):
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
    def __init__(self, feeds: DealFeeds, http: PoliteClient):
        self.feeds, self.http = feeds, http

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
        candidates = []
        for p in posts.values():
            s = self.sale(p, now, res.excluded)
            if s is not None:
                candidates.append(s)
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
        why = not_a_sale(p, o)
        if why:
            excluded[f"not a store sale: {why}"] += 1
            return None
        store, how = find_store(p)
        name = store.name if store else (clean(p.seller) if p.source == "dealnews" and not
                                          _DEAL_SITES.match(p.seller.strip()) else "")
        if not name:
            excluded["sale: store not identified"] += 1
            return None
        if not store and not _SHIPS.search(f"{p.title} {p.text[:600]}"):
            excluded["sale: the post doesn't say the store ships"] += 1
            return None
        starts, ends, ends_how = sale_dates(p, now)
        if ends and ends < now:
            excluded["sale: ended"] += 1
            return None
        if p.posted_at and now - p.posted_at > timedelta(days=POSTED_DAYS):
            excluded[f"sale: posted over {POSTED_DAYS} days ago"] += 1
            return None
        if not ends and (not p.posted_at or now - p.posted_at > timedelta(days=UNDATED_DAYS)):
            excluded[f"sale: no end date and posted over {UNDATED_DAYS} days ago"] += 1
            return None
        title = clean(p.title)
        sname = sale_name(title, store, name)
        sitewide = bool(_SITEWIDE.search(title)) or (bool(_EVERYTHING.search(title)) and is_store_event(sname))
        inds, rule = sale_industries(p, store, sname, sitewide)
        if not inds:
            excluded["sale: no industry"] += 1
            return None
        text, badge, soft = offer_text(o)
        conditions = conditions_of(o, title, p.text)
        posted = (p.posted_at or now).astimezone(CENTRAL).date()
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
    return kept


