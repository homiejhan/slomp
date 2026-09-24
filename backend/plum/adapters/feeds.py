"""Online deal feeds. Each states its discount differently, and what a saving is measured against matters as much as
the number:

  * Slickdeals (community-vetted; the thumb score is the vetting): "on sale for $199.99 - 35% with promo code X
    = $129.99" is a discount on the store's own price. A bare "on sale for $9.99" states no reference.
  * dealnews (editor-checked): "You'd pay $5 more at Macy's" and "the best price we found by $16" are other stores'
    prices; "a $9 low" and "best-ever price" are price history; "a $39 savings" names no reference.
  * camelcamelcamel: "down 13.26% ($3.88) to $25.37 from $29.25" is Amazon's own tracked price.
"""
from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Optional

from ..models import DealTerms, OnlineDeal, PricePoint
from ..net import HttpClient
from ..terms import clean, money

TTL_S = 1800                       # deal feeds turn over within hours
FEEDS = {
    "Slickdeals": ("https://slickdeals.net/newsearch.php?mode=frontpage&searcharea=deals&searchin=first&rss=1",
                   "https://slickdeals.net/newsearch.php?mode=popdeals&searcharea=deals&searchin=first&rss=1"),
    "dealnews": ("https://www.dealnews.com/?rss=1",),
    "camelcamelcamel": ("https://camelcamelcamel.com/top_drops/feed",),
}
M = r"\$\s*(\d[\d,]*(?:\.\d{1,2})?)"                       # a dollar amount
_NUMWORD = {"a buck": 1.0, "a dollar": 1.0, "a couple bucks": 2.0, "a few bucks": 3.0}


# --- shared ------------------------------------------------------------------------------------------------------


def _items(xml_text: str) -> list[ET.Element]:
    try:
        return ET.fromstring(xml_text.encode("utf-8")).findall(".//item")
    except ET.ParseError:
        return []


def _field(item: ET.Element, name: str) -> str:
    """Child text by local name, whatever its namespace (dealnews keeps price and retailer in its own)."""
    return next(((c.text or "").strip() for c in item if c.tag.rsplit("}", 1)[-1] == name), "")


def _plain(fragment: str) -> str:
    return clean(html.unescape(re.sub(r"<[^>]+>", " ", html.unescape(fragment or ""))))


def _img(fragment: str) -> str:
    m = re.search(r"""<img[^>]+src=["']([^"']+)["']""", html.unescape(fragment or ""))
    return m.group(1) if m else ""


def _when(raw: str) -> Optional[datetime]:
    if not raw:
        return None
    try:
        return parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        pass
    try:
        d = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return d if d.tzinfo else None
    except ValueError:
        return None


def _amount(text: str) -> Optional[float]:
    """'$12' / '12.50' / 'a buck' -> a number."""
    t = text.strip().lower()
    if t in _NUMWORD:
        return _NUMWORD[t]
    return money(t)


def _pct(price: Optional[float], ref: Optional[float]) -> Optional[float]:
    return round((ref - price) / ref * 100, 1) if price and ref and ref > price else None


# --- Slickdeals ---------------------------------------------------------------------------------------------------

_SD_THUMBS = re.compile(r"Thumb Score:\s*([+-]?\d+)")
# Posts open with "<seller> via <store> [domain] has ..." or "<store> [domain] has ...".
_SD_STORE = re.compile(r"^\s*(?:(?P<seller>[^\[\]]{1,60}?)\s+via\s+)?(?P<store>[^\s\[][^\[]{0,40}?)\s*"
                       r"(?P<domain>\[\s*[\w.-]+\s*\])?\s+has\b")
_SD_ANCHOR = re.compile(rf"\bon sale\s+(?:for|from)\s+(?:(\d+)\s+for\s+)?{M}|\b(\d+)\s+for\s+{M}|\bfor\s+{M}", re.I)
_SD_RANGE = re.compile(rf"^\s*[–—]\s*{M}")                   # "$9.99–$14.99": a spread of prices, not a discount
_SD_FINAL = re.compile(rf"=\s*{M}")
_SD_PCT = re.compile(r"\s-\s*(\d{1,2})\s*%")
_SD_OFF = re.compile(rf"\s-\s*{M}")
_SD_CODE = re.compile(r"\b(?:promo|coupon)\s+code\s+([A-Z0-9]{4,20})\b|\bcode\s+([A-Z0-9]{4,20})\b")
_SD_LIST = re.compile(rf"Sale Price:\s*{M}.{{0,40}}?List Price:\s*{M}", re.I)
_SD_PREFIX = re.compile(r"^([A-Z][\w'&+ ]{1,30}?):\s+")      # "Prime Members: ...", "Select Accounts: ..."
_SD_STORE_PREFIX = re.compile(r"^(?:Amazon|Walmart|Target|eBay|Woot!?|Best Buy)\s+[–—-]\s+")
_SD_CONDITIONS = ((re.compile(r"\bclip", re.I), "clip coupon"),
                  (re.compile(r"subscribe\s*&\s*save|\bS&S\b", re.I), "Subscribe & Save"),
                  (re.compile(r"\brefurb", re.I), "refurbished"),
                  (re.compile(r"\bopen[- ]box\b", re.I), "open box"))
_SD_STORES = {"amazon": "Amazon", "walmart": "Walmart", "ebay": "eBay", "costco-wholesale": "Costco",
              "the-home-depot": "The Home Depot", "lowes": "Lowe's", "best-buy": "Best Buy", "target": "Target",
              "woot": "Woot", "newegg": "Newegg", "adidas": "adidas", "nike": "Nike", "macys": "Macy's",
              "kohls": "Kohl's", "sweetwater": "Sweetwater", "b-h-photo-video": "B&H", "dell": "Dell"}


def _title_prices(title: str) -> list[float]:
    return [v for v in (money(m) for m in re.findall(M, title)) if v]


def _sd_product(title: str, body_html: str) -> tuple[str, list[str]]:
    """The product name and any audience limits from the title ("Prime Members: ..." -> "Prime members")."""
    conds: list[str] = []
    m = re.search(r"\bhas\s+(?:for\s+[^*]{0,40}?:\s*)?\*([^*]{5,200})\*", html.unescape(body_html))
    name = clean(m.group(1)) if m else ""
    if len(name.split()) < 3:                           # "*27-Gallon* HDX Tough Tote": only part of the name is starred
        name = ""
    t = re.sub(r"^\$[\d,.]+\s*\|\s*", "", _SD_STORE_PREFIX.sub("", clean(title)))
    p = _SD_PREFIX.match(t)
    if p and re.search(r"member|account|prime|student|new customer|select", p.group(1), re.I):
        who = p.group(1).lower()
        conds.append("Prime members only" if who == "prime" else who.replace("members", "members only").strip())
        t = t[p.end():]
    if not name:
        name = re.sub(r"\s+(?:\d+\s+for\s+)?\$[\d,.].*$", "", t).strip(" -–—+") or t
    return name, conds


def _sd_store(text: str, raw: str) -> str:
    """The store from the post's opening line, trusted only with a "via" or a [domain]; else the link's store tag."""
    slug = re.search(r'data-store-slug="([^"]+)"', raw)
    tagged = _SD_STORES.get(slug.group(1), slug.group(1).replace("-", " ").title()) if slug else ""
    m = _SD_STORE.match(text[:220])
    if m and (m.group("seller") or m.group("domain")):
        return m.group("store").strip()
    return tagged


def parse_slickdeals(xml_text: str) -> list[OnlineDeal]:
    out: list[OnlineDeal] = []
    for it in _items(xml_text):
        link = _field(it, "link")
        tid = re.search(r"/f/(\d+)", link)
        desc = _field(it, "description")
        raw = _field(it, "encoded") or desc
        text = _plain(raw)
        title = clean(_field(it, "title"))
        if not (tid and title):
            continue
        name, conds = _sd_product(title, desc)          # the plain summary wraps the full product name in *...*
        thumbs = _SD_THUMBS.search(text)
        body = _SD_THUMBS.sub("", text).strip()
        store = _sd_store(body, raw)

        price = was = None
        qty, hedge = 1, ""
        a = _SD_ANCHOR.search(body)
        if a:
            q = a.group(1) or a.group(3)
            listed = money(a.group(2) or a.group(4) or a.group(5))
            qty = int(q) if q and 1 < int(q) <= 50 else 1
            rest = body[a.end():]
            end = re.search(r"\.\s+(?=[A-Z])", rest)
            seg = rest[:end.start()] if end else rest[:220]
            if _SD_RANGE.match(rest):
                price, hedge = listed, "starting at"
            else:
                if re.match(r"on sale\s+from\b", a.group(0), re.I) or re.search(r"&\s*more\b", title, re.I):
                    hedge = "starting at"        # "on sale from $17.99", "$9 & More": the cheapest of several options
                final, pct, off = _SD_FINAL.search(seg), _SD_PCT.search(seg), _SD_OFF.search(seg)
                if final:
                    price = money(final.group(1))
                elif pct:
                    price = round(listed * (1 - int(pct.group(1)) / 100), 2) if listed else None
                elif off:
                    price = round(listed - (money(off.group(1)) or 0), 2) if listed else None
                else:
                    price = listed
                was = listed if price is not None and listed and listed > price else None
        lp = _SD_LIST.search(body)
        if lp and was is None:
            price, was, hedge = money(lp.group(1)), money(lp.group(2)), "compare at"
        seen = _title_prices(title)
        if price is not None and seen and not any(abs(price - s) <= max(1.0, 0.03 * s) for s in seen):
            price, was, hedge = min(seen), None, ""     # the body's math doesn't match the headline: trust neither
        if price is None and seen:
            price = min(seen)
        code_m = _SD_CODE.search(body)
        code = next((g for g in code_m.groups() if g), "") if code_m else ""
        conds += [label for pat, label in _SD_CONDITIONS if pat.search(title + " " + body)]
        pct = _pct(price, was)
        if price is not None and was is None and not hedge:
            hedge = "no reference"
        out.append(OnlineDeal(
            id=f"slickdeals:{tid.group(1)}", source="Slickdeals", title=name, store=store,
            terms=DealTerms(price=price, quantity=qty, was=was, pct_off=pct,
                            dollars_off=round(was - price, 2) if was and price else None, hedge=hedge,
                            conditions=tuple(dict.fromkeys(([f"code {code}"] if code else []) + conds))),
            url=link.split("?")[0], image_url=_img(raw), posted=_when(_field(it, "pubDate")),
            votes=int(thumbs.group(1)) if thumbs else None, code=code, category=_field(it, "category"), headline=title))
    return out


# --- dealnews -----------------------------------------------------------------------------------------------------

_DN_EXACT = re.compile(rf"\bfor\s+{M}")
_DN_MORE_AT = re.compile(r"You'd pay\s+(?:about\s+|around\s+)?(\$[\d,.]+|a buck|a couple bucks|a few bucks)\s+more\s+"
                         r"(?:at\s+([A-Z][\w&'. -]{1,30}?)(?=[.,;]|\s*$)|elsewhere|locally)", re.I)
_DN_PAY_ELSEWHERE = re.compile(rf"You'd pay\s+(over|at least|about|around|roughly)?\s*{M}\s+(elsewhere|locally)", re.I)
_DN_DOUBLE = re.compile(r"(?:You'd pay\s+(?:around|about|roughly)?\s*double|around half what you'd pay)\s+elsewhere", re.I)
_DN_BEST_BY = re.compile(r"best price we (?:could\s+)?f(?:ou|i)nd by\s+(at least\s+)?(\$[\d,.]+|a buck)", re.I)
_DN_UNDER_LOCAL = re.compile(rf"{M}\s+under local prices", re.I)
_DN_UNDER_DIRECT = re.compile(rf"{M}\s+under what\s+([A-Z][\w&'. -]{{1,30}}?)\s+charges", re.I)
_DN_LOW = re.compile(rf"\ba\s+{M}\s+low\b|\ba low by (a buck|\$[\d,.]+)", re.I)
_DN_DROP = re.compile(rf"\ba\s+{M}\s+drop from\s+(\w+)", re.I)
_DN_BEST_EVER = re.compile(r"best[- ]ever price|lowest price we've seen|(second|third)-lowest price we've seen", re.I)
_DN_LOWEST_FOUND = re.compile(r"lowest price we (?:could\s+)?f(?:ou|i)nd", re.I)
_DN_SAVE = re.compile(rf"(?:\ban?\s+{M}\s+savings\b|savings of\s+{M}|(?<!\w){M}\s+off\b(?!\s+(?:list|MSRP)))", re.I)
_DN_OFF_LIST = re.compile(rf"{M}\s+off\s+(?:list|MSRP)|{M}\s+below the original price|list (?:price )?of\s+{M}", re.I)
_DN_REGULAR = re.compile(rf"(?:normally|regularly)\s+(?:costs?\s+|sells for\s+)?{M}|regular price of\s+{M}", re.I)
_DN_CEILING = re.compile(r"\b(?:as high as|up to)\s+\$\d", re.I)


def _dn_compare(text: str, price: float, store: str) -> tuple[list[PricePoint], str]:
    """Other stores' prices and price-history notes from a dealnews write-up."""
    pts: list[PricePoint] = []
    src = "dealnews editors"
    m = _DN_MORE_AT.search(text)
    if m:
        more = _amount(m.group(1)) or 0
        where = m.group(2) or ("stores near you" if "locally" in m.group(0).lower() else "other stores")
        pts.append(PricePoint(where, round(price + more, 2), src, approx="around" in m.group(0).lower()))
    m = _DN_PAY_ELSEWHERE.search(text)
    if m:
        q = (m.group(1) or "").lower()
        pts.append(PricePoint("stores near you" if m.group(3).lower() == "locally" else "other stores", money(m.group(2)),
                              src, at_least=q in ("over", "at least"), approx=q in ("about", "around", "roughly")))
    if _DN_DOUBLE.search(text):
        pts.append(PricePoint("other stores", round(price * 2, 2), src, approx=True))
    m = _DN_BEST_BY.search(text)
    if m:
        pts.append(PricePoint("next-cheapest store", round(price + (_amount(m.group(2)) or 0), 2), src,
                              at_least=bool(m.group(1))))
    m = _DN_UNDER_LOCAL.search(text)
    if m:
        pts.append(PricePoint("stores near you", round(price + (money(m.group(1)) or 0), 2), src))
    m = _DN_UNDER_DIRECT.search(text)
    if m:
        pts.append(PricePoint(f"{m.group(2)} (direct)", round(price + (money(m.group(1)) or 0), 2), src))
    notes = []
    m = _DN_LOW.search(text)
    if m:
        amt = _amount(m.group(1) or m.group(2))
        notes.append(f"${amt:g} below its previous low" if amt else "a new low")
    m = _DN_DROP.search(text)
    if m:
        notes.append(f"${money(m.group(1)):g} less than in {m.group(2)}")
    m = _DN_BEST_EVER.search(text)
    if m:
        notes.append((m.group(1) + "-lowest price seen") if m.group(1) else "best price ever seen")
    if _DN_LOWEST_FOUND.search(text) and not pts:
        notes.append("lowest price dealnews found")
    return [p for p in pts if p.price and p.price > price], "; ".join(dict.fromkeys(notes))


def parse_dealnews(xml_text: str) -> list[OnlineDeal]:
    out: list[OnlineDeal] = []
    for it in _items(xml_text):
        title, link = clean(_field(it, "title")), _field(it, "link")
        listed = money(_field(it, "price"))
        text = _plain(_field(it, "description"))
        if not (title and link and listed) or re.search(r"/mo\b|per month|a month", title, re.I):
            continue                      # subscriptions aren't priced products
        exact = next((money(m) for m in _DN_EXACT.findall(text) if money(m) and abs(money(m) - listed) <= 1), None)
        price = exact or listed
        store = re.sub(r"\s+An Amazon Company$", "", clean(_field(it, "retailer"))) or ""
        name = clean(re.split(r"\s+for\s+\$|\s+from\s+\$", title)[0])
        elsewhere, history = _dn_compare(text, price, store)
        was = hedge = None
        m = _DN_REGULAR.search(text)
        if m:
            was = money(m.group(1) or m.group(2))
        m = None if was else _DN_OFF_LIST.search(text)
        if m:
            amt = money(m.group(1) or m.group(2))
            was, hedge = (round(price + amt, 2) if amt else money(m.group(3))), "compare at"
        dollars = None
        if was is None:
            m = _DN_SAVE.search(text)
            dollars = money(next(g for g in m.groups() if g)) if m else None
        best = max((p.price for p in elsewhere if not p.at_least), default=None) or \
            max((p.price for p in elsewhere), default=None)
        if was and was > price:
            pct, hedge = _pct(price, was), hedge or ""
            dollars = round(was - price, 2)
        elif best:                        # nothing on the store's own price, but editors priced it elsewhere
            pct, hedge = _pct(price, best), "elsewhere"
        elif dollars:
            pct, hedge = _pct(price, price + dollars), "no reference"
        else:
            pct, hedge = None, "no reference"
        if hedge in ("", "no reference") and _DN_CEILING.search(text):
            hedge = "up to"                          # "savings run as high as $74 off": a ceiling, not this item's saving
        code_m = _SD_CODE.search(text)
        code = next((g for g in code_m.groups() if g), "") if code_m else ""
        conds = ([f"code {code}"] if code else []) + [label for pat, label in _SD_CONDITIONS if pat.search(title + " " + text)]
        num = re.search(r"(\d+)\.html", link)
        out.append(OnlineDeal(
            id=f"dealnews:{num.group(1) if num else link}", source="dealnews", title=name, store=store, code=code,
            terms=DealTerms(price=price, was=was if was and was > price else None, pct_off=pct, dollars_off=dollars,
                            hedge=hedge or "", conditions=tuple(dict.fromkeys(conds))),
            url=link.split("?")[0], image_url=_img(_field(it, "description")), posted=_when(_field(it, "pubDate")),
            expires=_when(_field(it, "expires")), staff_pick=_field(it, "staffPick") == "true", history=history,
            category=_field(it, "category"), headline=title, elsewhere=elsewhere))
    return out


# --- camelcamelcamel ----------------------------------------------------------------------------------------------

_CAMEL = re.compile(rf"^(.*?)\s+-\s+down\s+([\d.]+)%\s+\({M}\)\s+to\s+{M}\s+from\s+{M}\s*$")


def parse_camel(xml_text: str) -> list[OnlineDeal]:
    out: list[OnlineDeal] = []
    for it in _items(xml_text):
        m = _CAMEL.match(clean(_field(it, "title")))
        link = _field(it, "link")
        asin = re.search(r"/product/([A-Z0-9]{10})", link)
        if not (m and asin):
            continue
        price, was = money(m.group(4)), money(m.group(5))
        out.append(OnlineDeal(
            id=f"camelcamelcamel:{asin.group(1)}", source="camelcamelcamel", title=m.group(1).replace("...", "…"),
            store="Amazon", terms=DealTerms(price=price, was=was, pct_off=_pct(price, was),
                                            dollars_off=round(was - price, 2) if price and was else None),
            url=link, store_url=f"https://www.amazon.com/dp/{asin.group(1)}", posted=_when(_field(it, "pubDate")),
            history="drop from Amazon's own tracked price"))
    return out


PARSERS = {"Slickdeals": parse_slickdeals, "dealnews": parse_dealnews, "camelcamelcamel": parse_camel}


class DealFeeds:
    def __init__(self, http: HttpClient):
        self.http = http

    async def fetch(self, source: str) -> list[OnlineDeal]:
        deals: dict[str, OnlineDeal] = {}
        for url in FEEDS[source]:
            for d in PARSERS[source](await self.http.get_text(url, ttl_s=TTL_S)):
                deals.setdefault(d.id, d)          # frontpage and popular overlap
        return list(deals.values())
