"""Reads deal terms out of weekly-ad text: multi-buys, BOGOs, per-pound prices, hedged savings, fine print.

Ads describe a deal across a few loose fields: the price, text printed before and after it, and a "sale story".
Misreading them is how deal lists mislead: "$8" for "2 for $8", "50% off" for "buy 1 get 1 50% off" (a 25% saving),
or an "up to" discount presented as the price. Every rule here errs toward the smaller claim.
"""
from __future__ import annotations

import re
from typing import Any, Iterable, Optional

from .models import DealTerms

MAX_PLAUSIBLE_PCT = 90.0      # deeper "discounts" in an ad are almost always a parsing or data error

_ZERO_WIDTH = re.compile(r"[\u200b-\u200f\u2060\ufeff]")
_FOOTNOTE = re.compile(r"[*†‡]+")
_NUM_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}
_N = r"(\d{1,2}|one|two|three|four|five)"

_QTY = re.compile(r"(?:^|\b)(\d{1,2})\s*(?:/|for\b|x\s*\$?|por\b)", re.I)                  # "2/", "2 FOR", "2X$"
_QTY_PRICE = re.compile(r"\b(\d{1,2})\s*(?:/|for)\s*\$\s*(\d+(?:\.\d{1,2})?)", re.I)       # "2/$5" inside text
_UNITS = ((re.compile(r"^(?:/|per\s+)?\s*lbs?\b", re.I), "lb"),
          (re.compile(r"^(?:/|per\s+)?\s*(?:ea|each|c/u)\b", re.I), "each"),
          (re.compile(r"^(?:/|per\s+)?\s*(?:cs|case)\b(?!\s+only)", re.I), "case"))   # "cs only" is a rule, not a unit
_UP_TO = re.compile(r"\bup\s+to\b|\bhasta\b", re.I)
_FROM = re.compile(r"\bstart(?:ing|s)\s+at\b|\bfrom\s+\$|\bas\s+low\s+as\b|\bdesde\b", re.I)
# A saving measured against someone else's price ("Dept. store value $103"), not the store's own regular price.
_COMPARE_AT = re.compile(r"\bstore\s+value\b|\bdep(?:ar)?t\.?\s+store\b|\bcompare\s+(?:at|to)\b|\bcomp\.?\s+(?:at|value)\b|"
                         r"\bretail\s+value\b|\bmsrp\b|\blist\s+price\b", re.I)
_OFF_AMOUNT = re.compile(r"\$?\s*(\d+(?:\.\d{1,2})?)\s*off\b", re.I)
_REG_CUE = re.compile(r"\b(?:was|reg(?:ular)?|price\s+drops?|originally|sale)\b", re.I)    # the store's own old price
_SAVE_CUE = re.compile(r"\b(?:save|savings|ahorr\w*|off)\b|%", re.I)
_PACK = re.compile(r"(?:(\d+)\s*/\s*)?(\d+(?:\.\d+)?)\s*(?:lb|lbs)\b", re.I)          # "40 lb", "6/2 lb" (= 12 lb)
_BOGO = re.compile(rf"\bbuy\s+{_N}\s*,?\s*get\s+{_N}\s+(free|(\d{{1,3}})\s*%\s*off)", re.I)
_BXGY = re.compile(r"\bb(\d)g(\d)\b(?:\s*(free|(\d{1,3})\s*%))?", re.I)
_BOGO_WORD = re.compile(r"\bbogo\b(?:\s*(\d{1,3})\s*%)?", re.I)
_PCT = re.compile(r"(\d{1,3}(?:\.\d+)?)\s*%\s*(?:off|de\s+descuento)", re.I)
_SAVE = re.compile(r"(?:\bsave|\bahorros?|\bahorra)\s+(?:up\s+to\s+)?"                   # "Save $30", "You save 76.00"
                   r"(?:\$\s*(\d[\d,]*(?:\.\d{1,2})?)|(\d[\d,]*\.\d{2})(?!\s*%))", re.I)
_DOLLAR_OFF = re.compile(r"\$\s*(\d[\d,]*(?:\.\d{1,2})?)\s+off\b", re.I)
_WAS = re.compile(r"(?:\bwas|\breg(?:ular)?\.?(?:\s+price)?|\bcompare\s+at|\bprecio\s+regular)\s*:?\s*"
                  r"\$\s*(\d[\d,]*(?:\.\d{1,2})?)", re.I)
_MIN_QTY = re.compile(r"(?:when\s+you\s+)?buy\s+(\d{1,3})\s*(?:\+|or\s+more)", re.I)
_LIMIT = re.compile(r"\blimit\s+(\d{1,3})\b\s*(lbs?\b)?", re.I)                        # "Limit 4", "Limit 10 lbs."
_SINGLE_PRICE = re.compile(r"\bor\s+(?:\$\s*\d|reg)", re.I)      # "2/$10 or $5.99 each": the price needs a multi-buy
_QTY_ONLY = re.compile(r"^(?:sale!?\s*)?\d{1,2}\s*(?:/|for|x\s*\$?)\s*$", re.I)   # "2/" says nothing on its own
_BARE_PRICE = re.compile(r"^\$\s*(\d[\d,]*(?:\.\d{1,2})?)\s*(?:ea\.?|each)?$", re.I)   # "$3499.99 ea." but not "$2 off"
_MEANINGFUL = re.compile(r"\d|\b(?:free|bogo|b\dg\d|clearance|rollback|price\s*drops?|half\s+(?:off|price)|bundle|"
                         r"gratis)\b", re.I)
_CONDITIONS = (
    (re.compile(r"\bbundle\b", re.I), "bundle"),       # the price covers a set whose size the ad data doesn't give
    (re.compile(r"\b(?:cs|case)\s+only\b", re.I), "full case only"),
    (re.compile(r"\bwith\s+(?:store\s+)?card\b|\bextracare\b", re.I), "loyalty card"),
    (re.compile(r"mywalgreens", re.I), "myWalgreens account"),
    (re.compile(r"\btarget\s+circle\b|\bwith\s+circle\b", re.I), "Target Circle"),
    (re.compile(r"(?:digital|smart|yellow|clip)\s+coupons?|\bwith\s+(?:a\s+)?coupon", re.I), "coupon"),
    (re.compile(r"\bonline\s+(?:price|only|savings|exclusive|deal)", re.I), "online price"),
    (re.compile(r"\bmembers?\s+only\b|\brewards\s+members\b|\bmember\s+price\b", re.I), "members only"),
    (re.compile(r"\brebate\b", re.I), "after rebate"),
)
# Warehouse clubs don't sell to the public; everything in their ads needs a membership.
MERCHANT_CONDITIONS = {"costco": "membership", "sam's club": "membership", "bj's wholesale club": "membership",
                       "restaurant depot": "business membership"}


def clean(text: Any) -> str:
    """Ad text as displayable plain text: no zero-width junk, no footnote markers, single spaces."""
    s = _FOOTNOTE.sub("", _ZERO_WIDTH.sub("", str(text or ""))).replace("\u2019", "'")
    return " ".join(s.split())


def money(raw: Any) -> Optional[float]:
    """'$1,299.99' / '3.99' / 3.99 -> 3.99. Blanks, zero, junk and absurd values -> None."""
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        v = float(raw)
    else:
        m = re.search(r"\d[\d,]*(?:\.\d+)?|\.\d+", str(raw))
        if not m:
            return None
        v = float(m.group(0).replace(",", ""))
    return v if 0 < v < 1_000_000 else None


def _pct(raw: Any) -> Optional[float]:
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return None
    return v if 0 < v < 100 else None


def _num(word: str) -> int:
    return _NUM_WORDS.get(word.lower()) or int(word)


def _first(patterns: Iterable[re.Pattern[str]], *texts: str) -> Optional[re.Match[str]]:
    for pat in patterns:
        for t in texts:
            m = pat.search(t) if t else None
            if m:
                return m
    return None


def bogo(text: str) -> Optional[tuple[int, int, float]]:
    """'Buy 2 get 1 free' -> (2, 1, 100); 'B1G1 50%' -> (1, 1, 50); 'BOGO' -> (1, 1, 100)."""
    m = _BOGO.search(text)
    if m:
        return _num(m.group(1)), _num(m.group(2)), float(m.group(4) or 100)
    m = _BXGY.search(text)
    if m:
        return int(m.group(1)), int(m.group(2)), float(m.group(4) or 100)
    m = _BOGO_WORD.search(text)
    if m:
        return 1, 1, float(m.group(1) or 100)
    return None


def unit_of(post: str) -> str:
    for pat, unit in _UNITS:
        if pat.search(post):
            return unit
    return ""


def price_is_discount(p: Optional[float], pre: str, post: str, story: str) -> bool:
    """The ad's big number is a dollars-off amount ("$5 OFF"), which feeds sometimes record as the price."""
    if p is None:
        return False
    if re.match(r"\s*off\b", post, re.I):
        return True
    for m in (m for t in (story, pre) for m in _OFF_AMOUNT.finditer(t)):
        v = float(m.group(1))
        if abs(v - p) < 0.005 or ("." not in m.group(1) and abs(v / 100 - p) < 0.005):   # "200 OFF" = $2.00 off
            return True
    return False


def pack_lb(description: str) -> Optional[float]:
    """Pack weight from a description like '40 lb' or '6/2 lb' (six 2-lb bags)."""
    m = _PACK.search(description)
    return (int(m.group(1)) if m.group(1) else 1) * float(m.group(2)) if m else None


def conditions_in(text: str) -> list[str]:
    out = [label for pat, label in _CONDITIONS if pat.search(text)]
    m = _MIN_QTY.search(text)
    if m:
        out.append(f"buy {m.group(1)}+")
    m = _LIMIT.search(text)
    if m:
        out.append(f"limit {m.group(1)}{' lb' if m.group(2) else ''}")
    return out


def parse_terms(*, price: Any = None, original: Any = None, pre: Any = None, post: Any = None, story: Any = None,
                pct: Any = None, dollars: Any = None, in_store_only: bool = False, name: Any = "",
                description: Any = "", disclaimer: Any = "", merchant: str = "", feed: bool = True) -> DealTerms:
    """Normalise one ad's price fields. Field values (pct, dollars, original) win over numbers parsed from text.

    `feed` says the numbers come from the retailer's product feed. Otherwise they were transcribed from the printed
    ad, where checking against the ad images showed savings that drop their reference ("You save $76" printed next
    to a department-store value) or are garbled outright ($28.20 read as "2.8"). Such savings count as firm only
    when the data states the store's own regular price."""
    pre, post, story = clean(pre), clean(post), clean(story)
    blob = " | ".join(t for t in (pre, story, post) if t)
    p = money(price)
    m = None if p is not None else _BARE_PRICE.match(story)
    if m:                                              # some ads carry the price only in the story: "$3499.99 ea."
        p = money(m.group(1))
    off_only = price_is_discount(p, pre, post, story)
    if off_only:                                       # "$5 OFF" recorded as a $5 price: keep the $5 as the saving
        p, dollars, pct, original = None, p, None, None

    qty = 1
    m = _QTY.search(pre)
    if m:
        qty = int(m.group(1))
    else:
        m = _first([_QTY_PRICE], story, post)
        if m:
            qty, p = int(m.group(1)), p if p is not None else money(m.group(2))
    if not 2 <= qty <= 50:
        qty = 1

    hedge = ("starting at" if _FROM.search(blob) else "up to" if _UP_TO.search(blob)
             else "compare at" if _COMPARE_AT.search(blob) else "")
    unit = unit_of(post) or unit_of(pre)
    conds = conditions_in(" | ".join(t for t in (blob, clean(disclaimer)) if t))   # fine print: "Limit 10 lbs. Each"
    if in_store_only:
        conds.append("in store only")
    club = MERCHANT_CONDITIONS.get(clean(merchant).lower())
    if club:
        conds.append(club)

    offer = next((t for t in (story, pre) if t and _MEANINGFUL.search(t) and not _QTY_ONLY.match(t)), "")
    was = money(original)
    was = was if (was is not None and p is not None and was > p) else None
    deal = bogo(blob) or bogo(clean(name))
    if deal:
        x, y, z = deal
        pct_off: Optional[float] = round(y * z / (x + y), 1)    # what you save across the x + y items
        dollars_off, was = None, None
        offer = offer or f"Buy {x} get {y} " + ("free" if z == 100 else f"{z:g}% off")
        conds.append(f"buy {x + y}")
    else:
        dollars_off = money(dollars)
        m = None if re.search(r"\bspend\b", blob, re.I) else _first([_SAVE, _DOLLAR_OFF], story, pre, post)
        printed = money(next(g for g in m.groups() if g)) if m else None     # "spend $2,500 save $200" is a reward
        if printed is not None and (dollars_off is None or abs(printed - dollars_off) <= 0.05):
            dollars_off = printed                     # the ad's own figure ($76.00) over a computed one ($76.01)
        if was is None:
            m = _WAS.search(blob)
            w = money(m.group(1)) if m else None
            was = w if (w is not None and p is not None and w > p) else None
        if was is None and p is not None and dollars_off and hedge not in ("up to", "starting at"):
            was = round(p + dollars_off, 2)
        if dollars_off is None and was is not None and p is not None:
            dollars_off = round(was - p, 2)
        pct_off = None if off_only else _pct(pct)
        if pct_off is None and not off_only:
            m = _PCT.search(blob)
            pct_off = _pct(m.group(1)) if m else None
        weight = pack_lb(clean(description)) if unit == "lb" else None
        if was is not None and p is not None and weight and abs(was - p * weight) <= 0.03 * was:
            was = dollars_off = pct_off = None     # the "regular price" is the whole pack at the same per-lb rate
        if not feed and p is not None and (was is not None or pct_off or dollars_off):
            stated = _WAS.search(blob) is not None or (money(original) is not None and _REG_CUE.search(blob) is not None)
            if not stated and _SAVE_CUE.search(blob):
                hedge, was = hedge or "no reference", None      # a saving, but against a price the ad doesn't give
            elif not stated:
                was = dollars_off = pct_off = None              # numbers no ad text backs up
        if was is not None and p is not None:
            exact = (was - p) / was * 100
            # Exact dollar figures beat a rounded percentage; if the two disagree, keep the smaller claim.
            pct_off = round(exact if pct_off is None or abs(exact - pct_off) <= 2 else min(exact, pct_off), 1)
    if qty > 1 and _SINGLE_PRICE.search(post):
        conds.append(f"buy {qty}")
        if not offer and p is not None:
            offer = f"{qty} for ${p:.2f}, {post}"
    return DealTerms(price=p, quantity=qty, unit=unit, was=was, pct_off=pct_off, dollars_off=dollars_off,
                     hedge=hedge, offer=offer, conditions=tuple(dict.fromkeys(conds)))
