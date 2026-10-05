"""The same product's current price on other websites.

Only sources that answer an honestly identified client and whose robots.txt allows the page are used:
  Amazon      search results (price, list price, ASIN); sponsored and renewed listings skipped
  Newegg      search results' embedded data (price, original price, model number); Newegg-sold listings only
  Flipp       this week's weekly-ad price at ~70 Texas chains (Walmart, Best Buy, Target, Costco, Kohl's, ...)
Walmart, Target, Best Buy's site, eBay, Home Depot, Lowe's and others serve bot checks or hang, and are not used.

A listing counts only when identity.same_product() says it is the same product.
"""
from __future__ import annotations

import html as htmllib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import quote_plus

from ..config import TTL
from ..http import FetchError, PoliteClient
from ..identity import identify, same_product
from ..models import Identity, PricePoint
from ..terms import clean, money
from .flipp import FlippClient, item_url

REFERENCE_ZIP = "78701"   # weekly-ad prices for online comparisons are read from one Texas market (Austin)


@dataclass
class Listing:
    site: str
    title: str
    price: float
    url: str
    regular_price: Optional[float] = None
    model: str = ""
    gtin: str = ""
    seller: str = ""
    via: str = ""


def parse_amazon(page: str) -> list[Listing]:
    out = []
    for block in re.split(r'(?=<div[^>]+data-component-type="s-search-result")', page)[1:]:
        asin = re.search(r'data-asin="([A-Z0-9]{10})"', block)
        title = (re.search(r'<h2[^>]*aria-label="([^"]+)"', block)
                 or re.search(r'<h2[^>]*>\s*(?:<a[^>]*>)?\s*<span[^>]*>([^<]+)</span>', block, re.S))
        price = re.search(r'<span class="a-price"[^>]*>\s*<span class="a-offscreen">([^<]+)</span>', block)
        listp = re.search(r'a-text-price"[^>]*>\s*<span class="a-offscreen">([^<]+)</span>', block)
        if not (asin and title and price) or re.search(r">\s*Sponsored\s*<|Sponsored Ad", block[:4000]):
            continue
        t = re.sub(r"^Sponsored Ad - ", "", htmllib.unescape(title.group(1))).strip()
        p = money(price.group(1))
        if not p:
            continue
        out.append(Listing("Amazon", t, p, f"https://www.amazon.com/dp/{asin.group(1)}",
                           money(listp.group(1)) if listp else None, via="Amazon search"))
    return out


def parse_newegg(page: str) -> list[Listing]:
    m = re.search(r"window\.__initialState__\s*=\s*", page)
    if not m:
        return []
    try:
        state, _ = json.JSONDecoder().raw_decode(page[m.end():])
    except json.JSONDecodeError:
        return []
    out = []
    for p in state.get("Products") or []:
        cell = p.get("ItemCell") or {}
        seller = (cell.get("Seller") or {}).get("SellerName") or ""
        if seller and seller.lower() != "newegg":
            continue                           # marketplace sellers: unvetted, often used or gray-market
        price = money(cell.get("FinalPrice"))
        item = str(cell.get("Item") or "")
        title = clean((cell.get("Description") or {}).get("Title"))
        if not (price and item and title):
            continue
        code = "N82E168" + item.replace("-", "") if re.fullmatch(r"\d{2}-\d{3}-\d{3}", item) else item
        out.append(Listing("Newegg", title, price, f"https://www.newegg.com/p/{code}",
                           money(cell.get("OriginalUnitPrice")), model=clean(cell.get("Model")),
                           gtin=clean(cell.get("UPCCode")), seller="Newegg", via="Newegg search"))
    return out


def flipp_listings(data: dict) -> list[Listing]:
    out = []
    for i in data.get("items") or []:
        p = money(i.get("current_price"))
        if p and i.get("merchant_name") and i.get("name"):
            out.append(Listing(clean(i["merchant_name"]), clean(i["name"]), p, item_url(i.get("id")),
                               money(i.get("original_price")), via="this week's ad (Flipp)"))
    for e in data.get("ecom_items") or []:
        p = money(e.get("current_price"))
        if p and e.get("merchant") and e.get("name"):
            out.append(Listing(clean(e["merchant"]), clean(e["name"]), p, "", money(e.get("original_price")),
                               via="online listing (Flipp)"))
    return out


@dataclass
class AmazonItem:
    asin: str
    title: str = ""
    brand: str = ""
    models: list[str] = None
    upc: str = ""
    price: Optional[float] = None
    unavailable: bool = False

    @property
    def url(self) -> str:
        return f"https://www.amazon.com/dp/{self.asin}"


_ASIN = re.compile(r"amazon\.com/(?:[^\s\"'<>?]*/)?(?:dp|gp/product|gp/aw/d)/([A-Z0-9]{10})", re.I)


def asins_in(*texts: str) -> list[str]:
    out: list[str] = []
    for t in texts:
        for m in _ASIN.finditer(t or ""):
            a = m.group(1).upper()
            if a not in out:
                out.append(a)
    return out


def parse_amazon_item(asin: str, page: str) -> AmazonItem:
    """Brand, model numbers, UPC and buy-box price from a product page's detail tables."""
    def clean_cell(x: str) -> str:
        return re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", x))).replace("\u200e", "").replace(
            "\u200f", "").strip()
    fields: dict[str, str] = {}
    for k, v in re.findall(r'<th[^>]*prodDetSectionEntry[^>]*>(.*?)</th>\s*<td[^>]*>(.*?)</td>', page, re.S):
        fields.setdefault(clean_cell(k).lower(), clean_cell(v))
    for k, v in re.findall(r'<span class="a-text-bold">([^<]*?):?\s*(?:&rlm;|\u200f)?\s*:?\s*(?:&lrm;|\u200e)?\s*</span>'
                           r'\s*<span[^>]*>([^<]*?)</span>', page, re.S):
        fields.setdefault(clean_cell(k).rstrip(" :").lower(), clean_cell(v))
    t = re.search(r'id="productTitle"[^>]*>(.*?)</span>', page, re.S)
    item = AmazonItem(asin=asin, title=clean_cell(t.group(1)) if t else "")
    item.brand = fields.get("brand name") or fields.get("brand") or fields.get("manufacturer", "")
    models = [fields.get(k, "") for k in ("model name", "model number", "item model number", "part number",
                                          "manufacturer part number")]
    item.models = [m for m in dict.fromkeys(models) if m and not re.fullmatch(r"\d{11,14}", m)]
    upc = fields.get("upc") or next((m for m in models if re.fullmatch(r"\d{12,13}", m or "")), "")
    item.upc = re.sub(r"\D", "", upc.split()[0]) if upc else ""
    for anchor in ('id="corePrice_feature_div"', 'id="corePriceDisplay_desktop_feature_div"', 'id="apex_desktop"'):
        i = page.find(anchor)
        if i >= 0:
            m = re.search(r'<span class="a-offscreen">\s*([^<]+?)\s*</span>', page[i:i + 20000])
            if m and money(m.group(1)):
                item.price = money(m.group(1))
                break
    item.unavailable = amazon_unavailable(page)
    return item


class PriceSources:
    def __init__(self, http: PoliteClient, flipp: FlippClient):
        self.http, self.flipp = http, flipp

    async def amazon(self, query: str) -> list[Listing]:
        r = await self.http.get(f"https://www.amazon.com/s?k={quote_plus(query)}", ttl_s=TTL["prices"], html=True)
        return parse_amazon(r.text) if r.status == 200 else []

    async def newegg(self, query: str) -> list[Listing]:
        r = await self.http.get(f"https://www.newegg.com/p/pl?d={quote_plus(query)}", ttl_s=TTL["prices"], html=True)
        return parse_newegg(r.text) if r.status == 200 else []

    async def amazon_item(self, asin: str) -> Optional[AmazonItem]:
        r = await self.http.get(f"https://www.amazon.com/dp/{asin}", ttl_s=TTL["prices"], html=True)
        return parse_amazon_item(asin, r.text) if r.status == 200 else None

    async def flipp_ads(self, query: str) -> list[Listing]:
        return flipp_listings(await self.flipp.search(REFERENCE_ZIP, query))

    async def compare(self, ident: Identity, query: str, exclude_site: str = "", near_price: Optional[float] = None,
                      sites: tuple[str, ...] = ("amazon", "newegg", "flipp")) -> tuple[list[PricePoint], list[str]]:
        """Matching listings at other sites (cheapest per site), and errors by site. With `near_price`, listings
        under 35% or over 300% of it are ignored: at those prices a "match" is an accessory, a bundle or a
        different product, whatever its title says."""
        now = datetime.now(timezone.utc)
        points: dict[str, PricePoint] = {}
        errors: list[str] = []
        for site in sites:
            try:
                listings = await getattr(self, {"flipp": "flipp_ads"}.get(site, site))(query)
            except FetchError as e:
                errors.append(f"{site}: {e.reason}")
                continue
            for li in listings:
                if exclude_site and li.site.lower() == exclude_site.lower():
                    continue
                if near_price and not (0.35 * near_price <= li.price <= 3.0 * near_price):
                    continue
                other = identify(f"{li.title} {li.model}".strip(), ident.brand if li.site == "Amazon" else "",
                                 li.gtin)
                ok, how = same_product(ident, other)
                if not ok:
                    continue
                cur = points.get(li.site)
                if cur is None or li.price < cur.price:
                    points[li.site] = PricePoint(site=li.site, price=li.price, url=li.url, title=li.title, match=how,
                                                 observed_at=now, regular_price=li.regular_price, via=li.via)
        return sorted(points.values(), key=lambda p: p.price), errors


def amazon_unavailable(page: str) -> bool:
    """Out of stock per the buy box's availability line, not the page's script text: "Currently unavailable" is a
    message template present on every product page."""
    m = re.search(r'id="availability"[^>]*>(.*?)</div>', page, re.S)
    line = re.sub(r"<[^>]+>", " ", m.group(1)) if m else ""
    line = line.split("{")[0]
    return bool(re.search(r"currently unavailable|temporarily out of stock|out of stock", line, re.I)) and \
        'id="add-to-cart-button"' not in page
