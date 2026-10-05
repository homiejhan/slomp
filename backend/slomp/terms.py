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
    (re.compile(r"\bwhen you buy \d+\b|\bmust buy \d+\b|\bbuy \d+ or more\b|\bmix (?:&|and) match\b", re.I), "buy multiple"),
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
# "Buy 1 get 1 50% off", "BUY ONE. GET ONE 50% OFF", "Buy 1 get 1 50%* off", "B1G1 Free", "Buy 2 get 3rd FREE"
_BOGO = re.compile(r"\b(?:buy|b)\s?(\d+|one|two)\s?(?:[.,;]\s*)?(?:get|g)\s?(?:the\s)?(\d+|one|two)(st|nd|rd|th)?\s?"
                   r"(?:(?:for|at)\s)?(free|(\d{1,3})\s?%\*?\s?off|half (?:off|price))?", re.I)
_BOGO_PRICED = re.compile(r"\s?(?:(?:for|at)\s?)?\$")   # "buy 1 get 1 for $1": the second one is not free
# The count and the percent run together, or the count is left out: "Buy 1 get 150% OFF", "Buy 1, get 50% off"
_BOGO_GLUED = re.compile(r"\b(?:buy|b)\s?(\d+|one|two)\s?(?:[.,;]\s*)?(?:get|g)\s?(\d{2,3})\s?%\*?\s?off", re.I)
_BOGO_WORD = re.compile(r"\bBOGO\b(?:\s+(free|(\d{1,3})\s?%\*?\s?off|half off))?", re.I)
_WORDNUM = {"one": 1, "two": 2}


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
    if m and not m.group(4) and _BOGO_PRICED.match(text, m.end()):
        return "", None
    if m:
        buy = int(_WORDNUM.get(m.group(1).lower(), m.group(1)))
        get = 1 if m.group(3) else int(_WORDNUM.get(m.group(2).lower(), m.group(2)))     # "get 3rd free": one item
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


_MULTI_PRE = re.compile(r"^\s*(\d{1,2})\s*(?:/|for\b)", re.I)
_MULTI_TEXT = re.compile(r"\b(\d{1,2})\s*(?:/|for)\s*" + _MONEY, re.I)
_UNIT = re.compile(r"(?:/|\bper\s|\b)(lb|lbs|oz|ea|each|ct|pk|kg)\b\.?", re.I)
_PCT_OFF = re.compile(r"(\d{1,3})\s?%\*?\s?off", re.I)
_DOLLARS_OFF = re.compile(r"\$\s?(\d+(?:\.\d\d)?)\s?off\b|\bsave \$\s?(\d+(?:\.\d\d)?)", re.I)
_REG = re.compile(r"\b(?:reg(?:ular(?:ly)?)?\.?|was|orig(?:inal(?:ly)?)?\.?|normally|retail)\s*(?:price)?\s*:?\s*"
                  + _MONEY, re.I)
_LIST = re.compile(r"\b(?:compare at|comp\.? value|compare value|value|msrp|list(?: price)?|depart(?:ment)?\.? store value)"
                   r"\s*:?\s*" + _MONEY, re.I)
_FIRM_WORDS = re.compile(r"\b(?:reg(?:ular)?|was|orig(?:inal)?|price drop|new lower price|everyday low|"
                         r"now only|sale price)\b", re.I)
_LIST_WORDS = re.compile(r"\b(?:compare at|comp\.? value|value|msrp|list price|store value)\b", re.I)


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
    t.conditions = conditions_of(text_all, desc[:300])
    if raw.get("in_store_only") and "in store only" not in t.conditions:
        t.conditions.append("in store only")
    if merchant_membership:
        t.conditions.append(merchant_membership)
    t.unit = _unit(post, pre)

    # "$50 OFF" printed where the price goes: a saving with no price.
    if price is not None and re.search(r"\boff\b", f"{pre} {post}", re.I) and not original:
        if "%" in f"{pre} {post}":
            t.pct, t.promo, t.price = float(price), True, None
        else:
            t.savings, t.promo, t.price = price, True, None
        price = None

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
    text_list = _LIST.search(text_all)
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
    elif text_list and price and money(text_list.group(1)) and money(text_list.group(1)) > price:
        regular, basis = money(text_list.group(1)), "list"
    if text_list and basis == "claimed_savings":
        basis = "list"

    # Promotions with no single price: "40% off all jeans", "$10 off $50".
    if price is None and not t.promo:
        mp = _PCT_OFF.search(f"{story} {name} {pre} {post}")
        md = _DOLLARS_OFF.search(f"{story} {name} {pre} {post}")
        if mp:
            t.pct, t.promo = float(mp.group(1)), True
        elif md:
            t.savings, t.promo = money(md.group(1) or md.group(2)), True
        elif pct_off:
            t.pct, t.promo = pct_off, True
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
        parts.append(f"${t.savings:,.2f} off")
    if t.regular is not None and not t.bogo:
        word = {"store_regular": "reg.", "list": "list", "claimed_savings": "ad says saves"}.get(t.basis, "ref.")
        if t.basis == "claimed_savings" and t.savings:
            parts.append(f"ad says you save ${t.savings:,.2f} (no regular price given)")
        else:
            parts.append(f"{word} ${t.regular:,.2f}")
    if t.pct and not t.promo:
        parts.append(f"{t.pct:g}% off")
    if t.hedge and t.hedge != "up to":
        parts.append(t.hedge)
    return ", ".join(parts)


# --- online deal posts -------------------------------------------------------------------------------------------
_PRICE_IN_TITLE = re.compile(r"(?<![\w$])" + _MONEY + r"(?!\s?(?:off|credit|gift|reward|bonus|cash back)\b)", re.I)
_STOREWIDE = re.compile(r"\bup to \d{1,3}%|\b\d{1,3}% off (?:sitewide|storewide|everything|all|select|orders?)\b|"
                        r"\bsale\b.*\bup to\b|\bdeals? (?:at|on|from)\b|\bextra \d{1,3}% off\b|\bsitewide\b|"
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
_DN_FROM_TO = re.compile(r"(?:drops?|cuts?|lowers?|reduces?|marked down|discounted) (?:it |this |the price )?"
                         r"(?:from |by )?" + _MONEY + r" to " + _MONEY, re.I)
_DN_HISTORY = re.compile(r"best price (?:\w+ ){0,3}(?:has charged|we've seen|ever)|lowest price (?:we've seen|ever)|"
                         r"all-time low|best-ever price", re.I)
# Slickdeals descriptions: "Amazon has X for $12.99 - 10% when you clip the coupon ... = $11.05"
_SD_CHAIN = re.compile(r"\bfor \*?" + _MONEY + r"\*?(?:[^.$=]{0,160}?)=\s*\*?" + _MONEY, re.I)
_SD_CODE = re.compile(r"\bfor \*?" + _MONEY + r"\*?[^.$]{0,120}?(?:promo code|coupon code|code|coupon)[^.$]{0,80}?"
                      r"(?:bringing it to|to get it for|making it|for|=)\s*\*?" + _MONEY, re.I)


def title_price(title: str) -> tuple[Optional[float], str]:
    """The deal price in a post title, and a hedge if the title gives several prices or '& more'."""
    prices = [money(m.group(1)) for m in _PRICE_IN_TITLE.finditer(title)]
    prices = [p for p in prices if p]
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
    m = _DN_LOW.search(text)
    if m and money(m.group(1)):
        return round(price + money(m.group(1)), 2), "history", sentence(m)
    m = _DN_SAVINGS.search(text) or _DN_OFF.search(text)
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
