"""Readers for the pages verification re-checks: product pages, deal-post pages, merchant links."""
from __future__ import annotations

import html as htmllib
import json
import re
from typing import Optional

from ..terms import money

_EXPIRED = re.compile(r"this deal (?:has )?expired|deal (?:has )?expired|\bexpired deal\b|no longer available|"
                      r"this deal is no longer|deal has ended|offer has ended|sold out", re.I)


def plain(page: str) -> str:
    page = re.sub(r"<(script|style|noscript)[^>]*>.*?</\1>", " ", page, flags=re.S | re.I)
    return re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", page)))


def price_forms(p: float) -> list[str]:
    """How a price can be written: $1,299.99 / $1299.99 / $1,299 / $1299 / $1.3K is not accepted."""
    forms = {f"${p:,.2f}", f"${p:.2f}"}
    if abs(p - round(p)) < 0.005:
        forms |= {f"${p:,.0f}", f"${p:.0f}"}
    return sorted(forms, key=len, reverse=True)


def has_price(text: str, p: float) -> bool:
    for f in price_forms(p):
        if re.search(r"\$\s?" + re.escape(f[1:]) + r"(?![\d])", text):
            return True
    return False


def expired_marker(text: str) -> Optional[str]:
    m = _EXPIRED.search(text[:6000])
    return m.group(0) if m else None


def amazon_product(page: str) -> dict:
    """Title and the buy-box price of an Amazon product page."""
    out: dict = {}
    t = re.search(r'id="productTitle"[^>]*>(.*?)</span>', page, re.S)
    out["title"] = re.sub(r"\s+", " ", htmllib.unescape(t.group(1))).strip() if t else ""
    for anchor in ('id="corePrice_feature_div"', 'id="corePriceDisplay_desktop_feature_div"', 'id="apex_desktop"',
                   'id="buybox"'):
        i = page.find(anchor)
        if i >= 0:
            m = re.search(r'<span class="a-offscreen">\s*([^<]+?)\s*</span>', page[i:i + 20000])
            if m and money(m.group(1)):
                out["price"] = money(m.group(1))
                break
    if "price" not in out:
        m = re.search(r'"priceAmount"\s*:\s*([\d.]+)', page)
        if m:
            out["price"] = float(m.group(1))
    out["unavailable"] = amazon_unavailable(page)
    return out


def jsonld_offer(page: str) -> dict:
    """Name and price from schema.org Product/Offer data."""
    for m in re.finditer(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', page, re.S | re.I):
        try:
            data = json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            continue
        stack = [data]
        while stack:
            x = stack.pop()
            if isinstance(x, list):
                stack += x
            elif isinstance(x, dict):
                t = x.get("@type")
                if t == "Product" or (isinstance(t, list) and "Product" in t):
                    offers = x.get("offers") or {}
                    offers = offers[0] if isinstance(offers, list) and offers else offers
                    price = money(offers.get("price") or offers.get("lowPrice")) if isinstance(offers, dict) else None
                    return {"title": str(x.get("name") or ""), "price": price, "model": str(x.get("mpn") or x.get("model") or "")}
                stack += [v for v in x.values() if isinstance(v, (dict, list))]
    return {}


_DIRECT = re.compile(r"https?://(?:www\.)?(?:amazon\.com/(?:[^\s\"'<>]*/)?(?:dp|gp/product)/[A-Z0-9]{10}|"
                     r"walmart\.com/ip/[^\s\"'<>]+|bestbuy\.com/site/[^\s\"'<>]+|newegg\.com/p/[^\s\"'<>]+|"
                     r"target\.com/p/[^\s\"'<>]+|woot\.com/offers/[^\s\"'<>]+)", re.I)
_SHORT_AMAZON = re.compile(r"(?<![\w/])amazon\.com/(?:dp|gp/product)/([A-Z0-9]{10})", re.I)


def direct_links(text: str) -> list[str]:
    """Merchant product URLs written out in a post or page."""
    out = [htmllib.unescape(m.group(0)).split("?")[0].rstrip(".,)") for m in _DIRECT.finditer(text or "")]
    out += [f"https://www.amazon.com/dp/{m.group(1)}" for m in _SHORT_AMAZON.finditer(text or "")]
    return list(dict.fromkeys(out))


def dealnews_buy_link(page: str) -> Optional[str]:
    m = re.search(r'href="(https://www\.dealnews\.com/lw/click\.html\?[^"]+)"', page)
    return htmllib.unescape(m.group(1)) if m else None


def asin_of(url: str) -> Optional[str]:
    m = re.search(r"/(?:dp|gp/product)/([A-Z0-9]{10})", url or "")
    return m.group(1) if m else None


def amazon_unavailable(page: str) -> bool:
    """Out of stock per the buy box's availability line, not the page's script text: "Currently unavailable" is a
    message template present on every product page."""
    m = re.search(r'id="availability"[^>]*>(.*?)</div>', page, re.S)
    line = re.sub(r"<[^>]+>", " ", m.group(1)) if m else ""
    line = line.split("{")[0]
    return bool(re.search(r"currently unavailable|temporarily out of stock|out of stock", line, re.I)) and \
        'id="add-to-cart-button"' not in page
