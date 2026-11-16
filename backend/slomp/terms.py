"""What a deal actually promises, read from its text.

Weekly-ad items (`ad_terms`) and online deal posts (`post_terms`) both become `Terms`: a per-unit price, the
reference it is measured against and what kind of reference that is (`basis`), multi-buys, BOGOs, hedges and
conditions. Rules that came from real ads Slomp v0.2 got wrong:

  * "You save $76" with no regular price can be a compare-at claim, so it is `claimed_savings`, not a firm saving,
    unless the item comes from the retailer's own feed or the ad says "reg"/"was".
  * BOGO "50% off" is a 25% saving when you buy two; "2 for $8" keeps its quantity ($4.00 each).
  * "Up to", "starting at", "from", "& more", "select" are hedges: a ceiling, not a promise.
  * A dollars-off amount printed where the price goes ("$50 OFF") is a saving with no price.
  * A "regular price" equal to a whole case at the per-pound price is not a discount.
  * A saving in words beside a price ("Save $250", "You save 25.00", "$3 OFF coupon") is read where no price field
    states one. The printed price is the price with the saving: "$1.25 with $3 OFF coupon" is never $-1.75.
  * A saving for an order of some size, for several items, or on something else is not this item's saving.
"""
from __future__ import annotations

import re
from typing import Any, Optional

from .models import Terms

_MONEY = r"\$\s?(\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)"


def money(raw: Any) -> Optional[float]:
    """'$1,299.99' / '1299.99' / 12 -> float, or None. Zero and negatives are not prices."""
    if raw is None or raw == "":
        return None
    if isinstance(raw, (int, float)):
        v = float(raw)
    else:
        m = re.search(r"(\d{1,3}(?:,\d{3})+|\d+)(\.\d{1,2})?", str(raw))
        if not m:
            return None
        v = float(m.group(1).replace(",", "") + (m.group(2) or ""))
    return round(v, 2) if v > 0 else None


def clean(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def pct(price: Optional[float], ref: Optional[float]) -> Optional[float]:
    if price is None or ref is None or ref <= 0 or price >= ref:
        return None
    return round((1 - price / ref) * 100, 1)


# --- hedges and conditions ---------------------------------------------------------------------------------------
_HEDGES = (
    (re.compile(r"\bup to\b", re.I), "up to"),
    (re.compile(r"\b(?:starting|starts) at\b|\bas low as\b", re.I), "starting at"),
    (re.compile(r"(?:^|\s)from \$|\bprices? from\b|\bdeals from\b", re.I), "from"),
    (re.compile(r"&\s*more\b|\band more\b", re.I), "& more (price varies by option)"),
    (re.compile(r"\bselect(?:ed)? (?:styles|items|varieties|models|colors|sizes|products|stores)\b", re.I),
     "select items"),
)

_CONDITIONS = (
    (re.compile(r"\bwith (?:your |a )?(?:\w+ ){0,2}(?:card|rewards|loyalty)\b|\bmembers? price\b", re.I), "loyalty card / rewards price"),
    (re.compile(r"\bdigital coupon\b|\bclip(?:ped)? (?:the )?coupon\b|\b'clip' the coupon\b|\bwith coupon\b|\bcoupon\b", re.I), "coupon required"),
    (re.compile(r"\b(?:promo|coupon|discount) code\b|\bw/ code\b|\bwith code\b|\bcode \"?[A-Z0-9]{4,}", re.I), "promo code"),
    (re.compile(r"\bmail-?in rebate\b|\bafter rebate\b|\b\$\d+(?:\.\d\d)? AR\b|\bw/ rebate\b", re.I), "mail-in rebate"),
    (re.compile(r"\bsubscribe ?(?:&|and) ?save\b|\bw/ S&S\b|\bvia S&S\b|\bSub\. ?& Save\b", re.I), "Subscribe & Save"),
    (re.compile(r"\bprime members?\b|\[prime\]|\bw/ prime\b|\bfor prime\b", re.I), "Prime members"),
    (re.compile(r"\bin[- ]store only\b|\bin stores? only\b", re.I), "in store only"),
    (re.compile(r"\bonline only\b|\bonline exclusive\b", re.I), "online only"),
    (re.compile(r"\bYMMV\b|\bselect stores\b|\bat participating\b|\bparticipating locations\b", re.I), "may vary by store"),
    (re.compile(r"\bwhen you buy (?:any )?(?:\d+|two|three|four|five|six)\b|\bmust buy \d+\b|"
                r"\bbuy (?:\d+|two|three|four|five|six) or more\b|\bmix (?:&|and) match\b", re.I), "buy multiple"),
    (re.compile(r"\bin the app\b|\bapp (?:only|exclusive|offer|users)\b|\bvia the app\b|\bwith the app\b", re.I), "in the app"),
    (re.compile(r"\bstudents?\b.*\bdiscount\b|\bstudent price\b", re.I), "students"),
    (re.compile(r"\b(?:in|at) (?:the )?(?:cart|checkout)\b|\bwhen you add (?:it |them )?to (?:your )?cart\b|"
                r"\bautomatically applied\b|\bapplied at checkout\b|\bextra \d{1,2}% off (?:in|at)\b", re.I),
     "discount applied in cart"),
)
_LIMIT = re.compile(r"\blimit (\d+)\b", re.I)
_CASE_ONLY = re.compile(r"\b(?:cs|case) only\b|\bfull case\b", re.I)


def hedge_of(*texts: str) -> str:
    text = " ".join(t for t in texts if t)
    for rx, label in _HEDGES:
        if rx.search(text):
            return label
    return ""


def conditions_of(*texts: str) -> list[str]:
    text = " ".join(t for t in texts if t)
    out = [label for rx, label in _CONDITIONS if rx.search(text)]
    m = _LIMIT.search(text)
    if m:
        out.append(f"limit {m.group(1)}")
    if _CASE_ONLY.search(text):
        out.append("full case only")
    return out


# --- BOGO and multi-buy ------------------------------------------------------------------------------------------
# "Buy 1 get 1 50% off", "BUY ONE. GET ONE 50% OFF", "Buy 1 get 1 50%* off", "B1G1 Free", "Buy 2 get 3rd FREE",
# and with a word between or the count after the offer: "BUY ONE AND GET ONE FREE", "BUY 1 GET FREE 1".
_BOGO = re.compile(r"\b(?:buy|b)\s?(\d+|one|two|three)\s?(?:[.,;]\s*)?(?:(?:and|&)\s+)?(?:get|g)\s?(?:the\s)?"
                   r"(?:(\d+|one|two|three)(st|nd|rd|th)?\s?)?"
                   r"(?:(?:for|at)\s)?(free|(\d{1,3})\s?%\*?\s?off|half (?:off|price))?", re.I)
_BOGO_PRICED = re.compile(r"\s?(?:(?:for|at)\s?)?\$")   # "buy 1 get 1 for $1": the second one is not free
_BOGO_COUNT_AFTER = re.compile(r"\s?(\d)\b(?!\s?(?:%|\.\d|/|for\b|oz\b|lbs?\b|ct\b|pk\b))")
# The count and the percent run together, or the count is left out: "Buy 1 get 150% OFF", "Buy 1, get 50% off"
_BOGO_GLUED = re.compile(r"\b(?:buy|b)\s?(\d+|one|two)\s?(?:[.,;]\s*)?(?:get|g)\s?(\d{2,3})\s?%\*?\s?off", re.I)
_BOGO_WORD = re.compile(r"\bBOGO\b(?:\s+(free|(\d{1,3})\s?%\*?\s?off|half off))?", re.I)
_WORDNUM = {"one": 1, "two": 2, "three": 3}


def bogo_of(*texts: str) -> tuple[str, Optional[float]]:
    """('buy 1 get 1 50% off', 25.0): the label and the effective percent saved when buying the whole set."""
    text = " ".join(t for t in texts if t)
    m = _BOGO_GLUED.search(text)
    if m:
        buy, digits = int(_WORDNUM.get(m.group(1).lower(), m.group(1))), m.group(2)
        get, off = (int(digits[0]), float(digits[1:])) if len(digits) == 3 else (1, float(digits))
        if buy > 0 and get > 0 and 0 < off <= 100:
            return f"buy {buy} get {get} {off:g}% off", round(get * off / (buy + get), 1)
    m = _BOGO.search(text)
    if m and m.group(2) and not m.group(4) and _BOGO_PRICED.match(text, m.end()):
        return "", None
    count = m.group(2) if m else None
    if m and not count:
        # The count after the offer ("BUY 1 GET FREE 1"). With none at all ("BUY 2 GET FREE", "buy 2 get $6 off",
        # "buy 1 get free shipping") how many come free is not said, and is not guessed.
        after = _BOGO_COUNT_AFTER.match(text, m.end()) if (m.group(4) or "").lower() == "free" else None
        count = after.group(1) if after else None
        m = m if count else None
    if m:
        buy = int(_WORDNUM.get(m.group(1).lower(), m.group(1)))
        get = 1 if m.group(3) else int(_WORDNUM.get(count.lower(), count))     # "get 3rd free": one item
        kind = (m.group(4) or "free").lower()
        off = 100.0 if kind == "free" else 50.0 if kind.startswith("half") else float(m.group(5))
        if buy <= 0 or get <= 0 or off <= 0 or off > 100:
            return "", None
        eff = round(get * off / (buy + get), 1)
        what = "free" if off == 100 else f"{off:g}% off"
        return f"buy {buy} get {get} {what}", eff
    m = _BOGO_WORD.search(text)
    if m:
        kind = (m.group(1) or "free").lower()
        off = 100.0 if kind == "free" else 50.0 if kind == "half off" else float(m.group(2))
        what = "free" if off == 100 else f"{off:g}% off"
        return f"buy 1 get 1 {what}", round(off / 2, 1)
    return "", None


# "2/", "3 for", and with a word in front as many ads print it: "Sale! 2/", "SALE 2 for", "BUY 2 FOR", "— ONLY — 2/".
_MULTI_PRE = re.compile(r"^\s*(?:(?:sale(?:\s+price)?|buy|—?\s*only\s*—?)\W*)?(\d{1,2})\s*(?:/|for\b)", re.I)
_MULTI_TEXT = re.compile(r"\b(\d{1,2})\s*(?:/|for)\s*" + _MONEY, re.I)
_UNIT = re.compile(r"(?:/|\bper\s|\b)(lb|lbs|oz|ea|each|ct|pk|kg)\b\.?", re.I)
_PCT_OFF = re.compile(r"(\d{1,3})\s?%\*?\s?off", re.I)
_SAVE_PCT = re.compile(r"\bsave\s+(?:up\s+to\s+)?(\d{1,2})\s?%", re.I)          # "SAVE 10% WHEN YOU BUY SIX OR MORE"
_DOLLARS_OFF = re.compile(r"\$\s?(\d+(?:\.\d\d)?)\s?off\b|\bsave \$\s?(\d+(?:\.\d\d)?)", re.I)
# --- a saving in the ad's own words ------------------------------------------------------------------------------
# An amount as ads print one: "$5", "$5.00", "$1,250", "5.00" with no sign (a drugstore's "You save 5.00", a farm
# store's "250.00 OFF REG. PRICE"), "75¢". Three groups.
_AMOUNT = (r"(?:\$\s?(\d{1,3}(?:,\d{3})+(?:\.\d\d)?|\d+(?:\.\d\d)?)|"
           r"(?<![\d.$,])(\d+\.\d\d)(?!\d)(?!\s?(?:oz|lbs?|ct|pk|ml|qt|gal|in|ft)\b)|(?<![\d.$])(\d{1,2})\s?¢)")
_COUNT = r"(\d{1,2}|two|three|four|five|six)"
_COUNTS = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6}
# "Save $250", "You save 25.00", "SAVE up to $2 per lb."; "$1 off", "250.00 OFF REG. PRICE", "200 OFF REG. PRICE",
# "Up to $4 off".
_SAVE_TEXT = re.compile(r"\b(?:you\s+)?sav(?:e|es|ings?)(?:\s+of)?\s+(up\s+to\s+)?" + _AMOUNT + r"(?!\s?%)", re.I)
_OFF_TEXT = re.compile(r"(?:\b(up\s+to)\s+)?(?:" + _AMOUNT + r"\s?off\b|(?<![\d.$,])(\d{1,4})\s?off(?=\s+reg))", re.I)
# What makes an amount something other than this item's saving. Anywhere in the text, an order size: "SPEND $199 SAVE
# $50", "save $10 when you spend $40", "with your $50 grocery purchase".
_ORDER_SIZE = re.compile(r"\bspend(?:ing)?\s+\$?\d|\$\s?\d+(?:\.\d\d)?\+?\s+(?:or\s+more\s+)?(?:\w+\s+)?(?:purchase|order)\b|"
                         r"\b(?:purchase|order)s?\s+of\s+\$\s?\d", re.I)
# Right after it: another amount ("$10 off $50"), the next order, a gallon of fuel, a reward.
_NOT_THIS = re.compile(r"^\s*(?:(?:on|with|w/|of)\s+)?(?:(?:your|a|an|any)\s+)?\$\s?\d|"
                       r"^\s*(?:(?:on|off|of)\s+)?your\s+(?:next|order|purchase|total|entire)\b|"
                       r"^\s*(?:per|a)\s+gal|^\s*(?:in\s+)?(?:rewards?|points|extrabucks|gift\s*cards?|cash\s*back|back)\b",
                       re.I)
# For several of the item: "$6 off 3", "Save $1 on 2", "SAVE $60 When You Buy 6 or more", "$1 WHEN YOU BUY 2".
_FOR_SEVERAL = re.compile(r"^\s*(?:(?:on|off)\s+(?:any\s+)?|when\s+you\s+buy\s+(?:any\s+)?|wyb\s+)?" + _COUNT +
                          r"\b(?!\s?(?:%|\.\d|¢|oz\b|lbs?\b|ct\b|pk\b))", re.I)
_BUY_GET = re.compile(r"\bbuy\s+" + _COUNT + r"\s*,?\s*(?:and\s+)?get\s+$", re.I)     # "Buy 2 Get $12.00 Off"
# The words that may follow this item's own saving: none, a new clause, "reg. price", "per lb.", "with card".
_THIS_ITEM = re.compile(r"^\s*(?:$|[^\w\s$]|reg\b|regular\b|each\b|ea\b|(?:per\s+|/\s?)?(?:lb|pound|oz|item|bottle|pkg|"
                        r"pack)\b|with\b|w/|when\b|instantly\b|sale\b|now\b|today\b)", re.I)
# A coupon's amount: "with $3 OFF Smart Coupon", "$1 off online coupon", "$4 DG DIGITAL COUPON", "$2.50 Digital mfr
# coupon", "75¢ OFF with Smart Coupon", "- 90¢ / EA DIGITAL COUPON", "Digital Coupon - $1.00", "$4.99-1.00 Digital
# Coupon"; for several items, "$6 off 3 online coupon", "$5.00 on 3 Digital mfr coupon", "$1 WHEN YOU BUY 2 ... COUPON".
_COUPON_WORDS = r"(?:[A-Za-z®™'/-]+\s+){0,4}?coupons?\b"
_COUPON_AMOUNT = re.compile(_AMOUNT + r"\s?(?:off\s+)?(?:(?:(?:on|off)\s+(?:any\s+)?|when\s+you\s+buy\s+(?:any\s+)?)?" + _COUNT +
                            r"\s+)?" + _COUPON_WORDS + r"|\bcoupons?\s*[-–:]\s*" + _AMOUNT, re.I)
_COUPON_NEXT = re.compile(r"^\s*" + _COUPON_WORDS, re.I)
# The dollar figure sits where the price goes, after "SAVE": "INSTANTLY SAVE [$1] WHEN YOU BUY 2", "SAVE [$2] DG DIGITAL
# COUPON". The words after it carry on the sentence; a lone "SAVE" over a price is a burst beside a price.
_SAVE_BEFORE = re.compile(r"\b(?:instantly\s+)?save(\s+up\s+to)?\s*$", re.I)
_SAVE_AFTER = re.compile(r"^\W*(?:when\b|with\b|w/|on\b|off\b|instantly\b|per\b|each\b)|\bcoupons?\b", re.I)
# The price runs up to another one ("$6.00 to $13.00"): a floor, not the price of each.
_PRICE_RANGE = re.compile(r"^(?:to|-|–)\s?\$\s?\d", re.I)
_REG = re.compile(r"\b(?:reg(?:ular(?:ly)?)?\.?|was|orig(?:inal(?:ly)?)?\.?|normally|retail)\s*(?:price)?\s*:?\s*"
                  + _MONEY, re.I)
# A price the ad compares with, not the store's own: "compare at $20", "MSRP $49.99", "THEIRS $8.99"; and with no
# sign after words that only ever lead to a price ("Depart. store value 65.00").
_LIST = re.compile(r"\b(?:compare at|comp\.? value|compare value|value|msrp|list(?: price)?|depart(?:ment)?\.? store value|"
                   r"theirs)\s*:?\s*" + _MONEY, re.I)
_LIST_BARE = re.compile(r"\b(?:compare at|comp\.? value|compare value|(?:depart(?:ment)?\.? |retail )?store value|"
                        r"retail value|theirs)\s*:?\s*(\d+\.\d\d)(?!\d)", re.I)
# A firm percent beside a price: "10% OFF When You Buy 6 or More", "SAVE 10% WHEN YOU BUY SIX", "-10% OFF". Not a
# ceiling over many items ("Up to 50% Off Kitchen Appliances", "SAVE UP TO 40% OFF APPAREL"), an extra on a price
# not stated ("+ Extra 10% Off with coupon"), or a percent off something else ("50% off 2nd", "20% off your next").
_PCT_TEXT = re.compile(r"(?<![\d.])(\d{1,2})\s?%\*?\s?off\b|\bsave\s+(\d{1,2})\s?%", re.I)
_PCT_SOFT = re.compile(r"\b(?:up\s+to|extra|additional|add'?l|another)\b[^.%]{0,12}$", re.I)
_PCT_ELSE = re.compile(r"^\s*(?:off\s+)?(?:on\s+)?(?:the\s+|your\s+|a\s+)?(?:2nd|second|3rd|third|next|entire|total|first)\b", re.I)
_FIRM_WORDS = re.compile(r"\b(?:reg(?:ular)?|was|orig(?:inal)?|price drop|new lower price|everyday low|"
                         r"now only|sale price)\b", re.I)
_LIST_WORDS = re.compile(r"\b(?:compare at|comp\.? value|value|msrp|list price|store value|theirs)\b", re.I)


def _amount(m: re.Match, first: int) -> Optional[float]:
    """The dollars an _AMOUNT matched (its three groups start at `first`)."""
    dollars, bare, cents = m.group(first), m.group(first + 1), m.group(first + 2)
    if dollars:
        return money(dollars)
    return float(bare) if bare else (int(cents) / 100 if cents else None)


def _count(word: Optional[str]) -> int:
    return int(_COUNTS.get(word.lower(), word)) if word else 1


def stated_saving(text: str) -> Optional[tuple[float, int, bool]]:
    """A saving on this item in the ad's own words: (dollars, for how many of the item, whether it is a ceiling).
    "Save $250" -> (250, 1, False); "SAVE up to $2 per lb." -> (2, 1, True); "250.00 OFF REG. PRICE" -> (250, 1, False);
    "SAVE $60 When You Buy 6" and "Buy 2 Get $12.00 Off" -> for 6 and for 2. None when the amount is for an order of
    some size ("$10 off $50", "save $10 when you spend $40"), for something else ("$1 off tortillas", "50¢ off per
    gallon"), or a coupon's (coupon_saving reads those)."""
    if _ORDER_SIZE.search(text):
        return None
    for rx in (_SAVE_TEXT, _OFF_TEXT):
        for m in rx.finditer(text):
            rest = text[m.end():]
            amount = _amount(m, 2) or (float(m.group(5)) if rx is _OFF_TEXT and m.group(5) else None)
            if not amount or _NOT_THIS.match(rest) or _COUPON_NEXT.match(rest):
                continue
            several = _FOR_SEVERAL.match(rest) or _BUY_GET.search(text[:m.start()])
            if several:
                return amount, _count(several.group(1)), bool(m.group(1))
            if _THIS_ITEM.match(rest):
                return amount, 1, bool(m.group(1))
    return None


def coupon_saving(text: str) -> Optional[tuple[float, int]]:
    """What a coupon named beside the price takes off: (dollars, for how many of the item). None when no amount is
    given ("FINAL PRICE WITH COUPON", "/EA With Digital Coupon")."""
    for m in _COUPON_AMOUNT.finditer(text):
        amount = _amount(m, 1) or _amount(m, 5)
        if amount:
            return amount, _count(m.group(4))
    return None


def stated_percent(text: str) -> Optional[float]:
    """A firm percent off stated beside a price, or None."""
    for m in _PCT_TEXT.finditer(text):
        if _PCT_SOFT.search(text[:m.start()]) or _PCT_ELSE.match(text[m.end():]):
            continue
        v = float(m.group(1) or m.group(2))
        if 0 < v < 100:
            return v
    return None


def _unit(*texts: str) -> str:
    for t in texts:
        m = _UNIT.search(t or "")
        if m:
            u = m.group(1).lower()
            return {"lbs": "lb", "each": "ea"}.get(u, u)
    return ""


def ad_terms(raw: dict, *, feed: bool, merchant_membership: str = "") -> Terms:
    """Terms of one weekly-ad item from every price field Flipp has for it (listing, search hit or full record).

    `feed` is True when the item came from the retailer's own product feed (it links to a product page), where
    savings are measured from the retailer's regular price. Ads transcribed from print can quote compare-at values.
    """
    name = clean(raw.get("name"))
    pre = clean(raw.get("pre_price_text"))
    post = clean(raw.get("price_text") or raw.get("post_price_text"))
    story = clean(raw.get("sale_story"))
    desc = clean(raw.get("description"))
    disclaimer = clean(raw.get("disclaimer_text"))
    text_all = " ".join(x for x in (name, pre, post, story, disclaimer) if x)
    said = " ".join(x for x in (pre, post, story) if x)          # the words around the price: where a saving is stated
    price_raw = raw.get("current_price", raw.get("price"))
    price = money(price_raw)
    original = money(raw.get("original_price"))
    dollars_off = money(raw.get("dollars_off"))
    pct_off = raw.get("percent_off") if raw.get("percent_off") is not None else raw.get("discount")
    try:
        pct_off = float(pct_off) if pct_off not in (None, "") and float(pct_off) > 0 else None
    except (TypeError, ValueError):
        pct_off = None

    t = Terms()
    t.hedge = hedge_of(pre, post, story, name)
    if price is not None and _PRICE_RANGE.match(post or story):
        t.hedge = t.hedge or "starting at"
    t.conditions = conditions_of(text_all, desc[:300])
    if raw.get("in_store_only") and "in store only" not in t.conditions:
        t.conditions.append("in store only")
    if merchant_membership:
        t.conditions.append(merchant_membership)
    t.unit = _unit(post, pre)

    # "40% OFF" or "$50 OFF" printed where the price goes: the number Flipp gives as the price is the saving, and the
    # text right after it says so. A price followed by other words is a price: "$149.99 + Extra 10% Off* with coupon",
    # "$5.25 with $1 OFF Smart Coupon", "BOGO 25% Off" above $12.99.
    if price is not None and not original and re.match(r"(?:%\s*)?off\b", post, re.I):
        if not post.startswith("%"):
            t.savings, t.promo, t.price = price, True, None
        elif price <= 100:
            t.pct, t.promo, t.price = float(price), True, None
        if t.promo:
            price = None
    # The same with the words in front: "INSTANTLY SAVE [$1] WHEN YOU BUY 2", "SAVE [$2] with digital coupon".
    elif price is not None and not original and _SAVE_BEFORE.search(pre) and _SAVE_AFTER.search(f"{post} {story}".strip()):
        t.savings, t.promo, t.price, price = price, True, None, None

    # Multi-buy: "2/" or "2 for" before the price -> per-unit price.
    m = _MULTI_PRE.match(pre) if pre else None
    if price is not None and m and int(m.group(1)) > 1:
        t.qty, t.bundle_price = int(m.group(1)), price
        price = round(price / t.qty, 2)
    elif price is None:
        mt = _MULTI_TEXT.search(f"{story} {name}")
        if mt and int(mt.group(1)) > 1:
            t.qty, t.bundle_price = int(mt.group(1)), money(mt.group(2))
            price = round(t.bundle_price / t.qty, 2) if t.bundle_price else None
    t.price = price if t.price is None and not t.promo else t.price

    label, eff = bogo_of(story, name, pre, post)
    if label:
        t.bogo, t.promo = label, True
        t.pct = eff
        t.basis = "store_regular"          # the store's own offer against its own price, with or without a price shown
        if price is not None and eff:
            t.regular = price
            t.savings = round(price * eff / 100, 2)
        t.summary = summarize(t)
        return t

    # The reference price, strongest evidence first.
    text_reg = _REG.search(text_all)
    text_list = _LIST.search(text_all) or _LIST_BARE.search(text_all)
    list_value = money(text_list.group(1)) if text_list else None
    regular: Optional[float] = None
    basis = "none"
    if text_reg and money(text_reg.group(1)) and t.qty == 1:
        regular, basis = money(text_reg.group(1)), "store_regular"
    elif original and price and original > price:
        regular = original
        basis = "store_regular" if (feed or _FIRM_WORDS.search(text_all)) else "claimed_savings"
        if _LIST_WORDS.search(text_all) and not _FIRM_WORDS.search(text_all):
            basis = "list"
    elif dollars_off and price:
        regular = round(price + dollars_off, 2)
        basis = "store_regular" if feed else "claimed_savings"
    elif pct_off and price and pct_off < 100:
        # Only a headline percent (rounded): show the percent, never a regular price computed from it.
        t.pct = float(pct_off)
        t.basis = "store_regular" if feed else "claimed_savings"
        t.summary = summarize(t)
        return t
    elif list_value and price and list_value > price:
        regular, basis = list_value, "list"
    elif price is not None:
        # The saving in the ad's words beside the price: "Save $250", "You save 25.00", "SAVE up to $2 per lb.", and a
        # coupon's amount. The printed price is the price with the saving ("$1.25 with $3 OFF coupon", "$4.99-1.00
        # Digital Coupon" over $3.99), so what the item costs without it is the price plus the saving. One coupon or
        # one "save $1" over "2 for $5" is taken as for the two.
        own, coupon = stated_saving(said), None
        if not own:
            coupon = coupon_saving(said)
        amount, n, ceiling = own if own else (*coupon, False) if coupon else (None, 1, False)
        if amount:
            each = round(amount / max(n, t.qty), 2)
            if n > 1 and "buy multiple" not in t.conditions:
                t.conditions.append("buy multiple")
            if ceiling or t.hedge:
                # "Save up to $2", or a price that is a floor: the ad's claim, and no regular price made from it. The
                # percent of a ceiling is a ceiling; a saving off "from $6" has none.
                t.savings, t.basis = each, "claimed_savings"
                if t.hedge in ("", "up to"):
                    t.hedge, t.pct = "up to", pct(price, round(price + each, 2))
                t.summary = summarize(t)
                return t
            regular = round(price + each, 2)
            basis = "store_regular" if feed and own else "claimed_savings"
        else:
            firm = stated_percent(said)
            if firm and not t.hedge:
                t.pct = firm                     # "10% OFF When You Buy 6 or More": the percent, as with a headline one
                t.basis = "store_regular" if feed else "claimed_savings"
                t.summary = summarize(t)
                return t
    if text_list and basis == "claimed_savings":
        basis = "list"

    # Promotions with no single price: "40% off all jeans", "$10 off $50", "250.00 OFF REG. PRICE", "Save up to $30",
    # "75¢ OFF with coupon", "SAVE 10% WHEN YOU BUY SIX OR MORE".
    if price is None and not t.promo:
        mp = _PCT_OFF.search(f"{story} {name} {pre} {post}") or _SAVE_PCT.search(said)
        md = _DOLLARS_OFF.search(f"{story} {name} {pre} {post}")
        own = None if mp or md or pct_off else stated_saving(said) or coupon_saving(said)
        if mp:
            t.pct, t.promo = float(mp.group(1)), True
        elif md:
            t.savings, t.promo = money(md.group(1) or md.group(2)), True
        elif pct_off:
            t.pct, t.promo = pct_off, True
        elif own:
            t.savings, t.promo = own[0], True
            if own[1] > 1 and "buy multiple" not in t.conditions:
                t.conditions.append("buy multiple")
            if len(own) > 2 and own[2]:
                t.hedge = t.hedge or "up to"
        t.basis = "store_regular" if t.promo and (feed or _FIRM_WORDS.search(text_all)) else (
            "claimed_savings" if t.promo else "none")
        t.summary = summarize(t)
        return t

    if regular is not None and price is not None and regular > price:
        # A "regular" that is a whole case at the per-pound price isn't a discount.
        if t.unit in ("lb", "oz", "kg") and regular / price > 8:
            regular, basis = None, "none"
    if regular is not None and price is not None and regular > price:
        t.regular, t.basis = regular, basis
        t.savings = round(regular - price, 2)
        t.pct = pct(price, regular)
        if t.pct and t.pct >= 90 and basis != "store_regular":
            t.rejected = f"{t.pct:g}% off a ${regular:,.2f} price: likely an ad error"
            t.regular, t.savings, t.pct, t.basis = None, None, None, "none"
    else:
        t.basis = "none"
    t.summary = summarize(t)
    return t


def summarize(t: Terms) -> str:
    parts: list[str] = []
    if t.qty > 1 and t.bundle_price:
        parts.append(f"{t.qty} for ${t.bundle_price:,.2f} (${t.bundle_price / t.qty:,.2f} ea)")
    elif t.price is not None:
        parts.append(f"${t.price:,.2f}{'/' + t.unit if t.unit and t.unit != 'ea' else ''}")
    if t.bogo:
        parts.append(t.bogo)
    elif t.promo and t.pct:
        parts.append(f"{t.hedge + ' ' if t.hedge == 'up to' else ''}{t.pct:g}% off")
    elif t.promo and t.savings:
        parts.append(f"{'up to ' if t.hedge == 'up to' else ''}${t.savings:,.2f} off")
    each = " each" if t.qty > 1 else ""
    if t.regular is not None and not t.bogo:
        word = {"store_regular": "reg.", "list": "list", "claimed_savings": "ad says saves"}.get(t.basis, "ref.")
        if t.basis == "claimed_savings" and t.savings:
            parts.append(f"ad says you save ${t.savings:,.2f}{each} (no regular price given)")
        else:
            parts.append(f"{word} ${t.regular:,.2f}")
    elif t.savings and t.price is not None and not t.promo and not t.bogo:       # a ceiling, or off a price that varies
        parts.append(f"ad says you save {'up to ' if t.hedge == 'up to' else ''}${t.savings:,.2f}{each}")
    if t.pct and not t.promo:
        parts.append(f"{'up to ' if t.hedge == 'up to' and t.regular is None else ''}{t.pct:g}% off")
    if t.hedge and t.hedge != "up to":
        parts.append(t.hedge)
    return ", ".join(parts)


# --- online deal posts -------------------------------------------------------------------------------------------
# A price, not the price it was cut from ("Originally $2,000 Samsung ... gaming monitor is down to $900", 9to5Toys),
# nor a saving or an order size: "$199 off" is no price at all (and never "$19"), nor "$50 discount",
# "$1,100 under the Pro model", "save $30", "free shipping w/ $35", "$10 off $30", "spend $9" or "on $49+".
# 9to5Toys titles put the saving first: "... live again at $199 off".
_PRICE_IN_TITLE = re.compile(r"(?<![\w$])(?<!\bsave )(?<!\bsaves )(?<!\bsaving )(?<!w/ )(?<!w/)(?<!\boff )(?<!\bspend )"
                             r"(?<!\boriginally )(?<!\bregularly )(?<!\bwas )(?<!\breg\. )(?<!\blist )"
                             + _MONEY +
                             r"(?![\d,.]*\d)(?!\+)(?!\s?(?:off|credit|gift|reward|bonus|cash back|discount|savings?|less|"
                             r"under|below|cheaper|lower|or more)\b)", re.I)
_CENTS_IN_TITLE = re.compile(r"(?<![\w$.])(\d{1,2})\s?(?:¢|cents?\b)(?!\s?(?:off|per|a gallon)\b)", re.I)  # "Only 49¢"
# "Deals at Woot" is many products; "Clearance deal on Apple Watch Ultra 3" (9to5Toys) is one.
_STOREWIDE = re.compile(r"\bup to \d{1,3}%|\b\d{1,3}% off (?:sitewide|storewide|everything|all|select|orders?)\b|"
                        r"\bsale\b.*\bup to\b|\bdeals (?:at|on|from)\b|\bextra \d{1,3}% off\b|\bsitewide\b|"
                        r"\bstorewide\b|\bextra \d{1,3}%|\b\d{1,3}% to \d{1,3}% off\b|\b(?:clearance|outlet) (?:sale|event|deals)\b|\bsale for from\b|\bgiveaway\b|\bsale event\b|\b\d+% off \$|"
                        r"\$\d+ off \$\d+|\bspend \$\d+|\bbuy \$\d+,? (?:get|save)\b|\bgift cards?\b|"
                        r"\bmembership\b|\bsubscriptions?\b|\bcredit card\b|\bbonus\b", re.I)
# dealnews descriptions: what the deal is measured against.
_DN_ELSEWHERE = re.compile(r"you'?d pay (?:at least |around |about )?" + _MONEY + r" (?:elsewhere|at|more)", re.I)
_DN_MORE_AT = re.compile(r"you'?d pay " + _MONEY + r" more (?:elsewhere|at ([A-Z][\w&' .-]+?))(?:[.,]|$)", re.I)
_DN_MOST = re.compile(r"most (?:merchants|stores|retailers) charge (?:around |about |at least |over )?" + _MONEY, re.I)
_DN_BEST_BY = re.compile(r"best (?:price|deal) we (?:could )?find(?: for [^.]*?)? by " + _MONEY, re.I)
_DN_LOW = re.compile(r"(?:that'?s )?an? " + _MONEY + r" (?:low|drop)\b", re.I)
_DN_LIST = re.compile(_MONEY + r" (?:\(about \d+%\) )?off (?:the |its |a )?" + _MONEY + r" list", re.I)
_DN_LIST2 = re.compile(r"(?:list price|list) (?:of |is )?" + _MONEY, re.I)
_DN_SAVINGS = re.compile(r"that'?s (?:a |an )?" + _MONEY + r" (?:savings|saving)\b", re.I)
_DN_OFF = re.compile(r"that'?s " + _MONEY + r" off\b", re.I)
# "It's $12 under list price."
_DN_UNDER = re.compile(_MONEY + r" (?:under|below) (?:the )?list(?: price)?\b", re.I)
_DN_FROM_TO = re.compile(r"(?:drops?|cuts?|lowers?|reduces?|marked down|discounted) (?:it |this |the price )?"
                         r"(?:from |by )?" + _MONEY + r" to " + _MONEY, re.I)
# 9to5Toys' words for the store's usual price: "This one normally fetches $37", "down from the usual $70 price tag",
# "Regularly fetching $399".
_USUAL = re.compile(r"\b(?:normally|usually|typically|regularly)\s+(?:fetch(?:es|ing)|sells?\s+for|selling\s+for|goes\s+for|"
                    r"going\s+for|priced\s+at|costs?|runs?|lists?\s+(?:for|at))\s+(?:around\s+|about\s+|closer\s+to\s+)?"
                    + _MONEY + r"|\bdown\s+from\s+(?:the\s+|its\s+|a\s+)?(?:usual|regular|normal|typical|going)?\s*"
                    r"(?:price\s+(?:of\s+|tag\s+of\s+)?|rate\s+of\s+)?" + _MONEY, re.I)
# The amount before the words, as The Inventory writes it: "a $30 discount from the $159.99 regular price".
_REG_AFTER = re.compile(_MONEY + r"\s+(?:regular|everyday|usual|normal)\s+price\b", re.I)
_DN_HISTORY = re.compile(r"best price (?:\w+ ){0,3}(?:has charged|we've seen|ever)|lowest price (?:we've seen|ever)|"
                         r"all-time low|best-ever price", re.I)
# Slickdeals descriptions: "Amazon has X for $12.99 - 10% when you clip the coupon ... = $11.05"
_SD_CHAIN = re.compile(r"\bfor \*?" + _MONEY + r"\*?(?:[^.$=]{0,160}?)=\s*\*?" + _MONEY, re.I)
_SD_CODE = re.compile(r"\bfor \*?" + _MONEY + r"\*?[^.$]{0,120}?(?:promo code|coupon code|code|coupon)[^.$]{0,80}?"
                      r"(?:bringing it to|to get it for|making it|for|=)\s*\*?" + _MONEY, re.I)


def title_price(title: str) -> tuple[Optional[float], str]:
    """The deal price in a post title, and a hedge if the title gives several prices or '& more'."""
    found = [(m.start(), money(m.group(1))) for m in _PRICE_IN_TITLE.finditer(title)] + \
        [(m.start(), round(int(m.group(1)) / 100, 2)) for m in _CENTS_IN_TITLE.finditer(title)]
    prices = [p for _, p in sorted(found) if p]
    if not prices:
        return None, ""
    hedge = hedge_of(title)
    # "$1299 & More", "From $499": the first price is a starting price.
    return prices[0], hedge


def post_reference(desc: str, price: Optional[float]) -> tuple[Optional[float], str, str]:
    """(reference price, basis, the sentence it came from) from a deal post's description."""
    if price is None:
        return None, "none", ""
    text = clean(desc)

    bounds = [0] + [b.end() for b in re.finditer(r"(?<=[.!?])\s+(?=[A-Z*\"'(])", text)] + [len(text)]

    def sentence(m: re.Match) -> str:
        """The whole sentence a match sits in (sentences end at '. ' before a capital, not at '$3.89' or 'amazon.com')."""
        start = max(b for b in bounds if b <= m.start())
        end = min((b for b in bounds if b >= m.end()), default=len(text))
        return text[start:end].strip()[:220]

    m = _DN_FROM_TO.search(text)
    if m and money(m.group(1)) and money(m.group(2)) and abs(money(m.group(2)) - price) <= max(1.0, price * 0.02):
        return money(m.group(1)), "store_regular", sentence(m)
    m = _DN_MORE_AT.search(text)
    if m and money(m.group(1)):
        return round(price + money(m.group(1)), 2), "editor_compare", sentence(m)
    m = _DN_ELSEWHERE.search(text) or _DN_MOST.search(text)
    if m and money(m.group(1)) and money(m.group(1)) > price:
        return money(m.group(1)), "editor_compare", sentence(m)
    m = _DN_BEST_BY.search(text)
    if m and money(m.group(1)):
        return round(price + money(m.group(1)), 2), "editor_compare", sentence(m)
    m = _DN_LIST.search(text)
    if m and money(m.group(2)) and money(m.group(2)) > price:
        return money(m.group(2)), "list", sentence(m)
    m = _SD_CHAIN.search(text) or _SD_CODE.search(text)
    if m and money(m.group(1)) and money(m.group(2)) and abs(money(m.group(2)) - price) <= max(1.0, price * 0.02) \
            and money(m.group(1)) > price:
        return money(m.group(1)), "store_regular", sentence(m)
    m = _REG.search(text)
    if m and money(m.group(1)) and money(m.group(1)) > price:
        return money(m.group(1)), "store_regular", sentence(m)
    m = _USUAL.search(text)
    usual = money(m.group(1) or m.group(2)) if m else None
    if usual and usual > price:
        return usual, "store_regular", sentence(m)
    m = _REG_AFTER.search(text)
    if m and money(m.group(1)) and money(m.group(1)) > price:
        return money(m.group(1)), "store_regular", sentence(m)
    m = _DN_LOW.search(text)
    if m and money(m.group(1)):
        return round(price + money(m.group(1)), 2), "history", sentence(m)
    m = _DN_SAVINGS.search(text) or _DN_OFF.search(text) or _DN_UNDER.search(text)
    if m and money(m.group(1)):
        return round(price + money(m.group(1)), 2), "list", sentence(m)
    m = _DN_LIST2.search(text)
    if m and money(m.group(1)) and money(m.group(1)) > price:
        return money(m.group(1)), "list", sentence(m)
    m = _DN_HISTORY.search(text)
    if m:
        return None, "history", sentence(m)
    return None, "none", ""


def is_storewide(title: str) -> bool:
    """A sale on many products ("Up to 70% off", "Deals at Woot", "$10 off $50"), not one product at one price."""
    return bool(_STOREWIDE.search(title))
