"""Retailer adapters. Each one: build a request (GTIN first, title fallback), parse the response into Listings.

Parsing is separated from transport so it can be unit-tested with recorded payloads and without keys.
Response shapes below follow the public docs as of writing; verify against the live APIs before shipping.
"""
from __future__ import annotations

import os
from typing import Any, Optional

from ..identifiers import canonical_gtin
from ..models import Condition, Listing, Product
from .base import Adapter, TokenBucket

try:  # transport is optional so the engine and tests run without it
    import httpx  # type: ignore
except Exception:  # noqa: BLE001
    httpx = None


class FixtureAdapter(Adapter):
    """Serves canned listings; used in tests and the demo service."""

    def __init__(self, retailer: str, listings: list[Listing], delay_s: float = 0.0, fail: bool = False,
                 by_product: Optional[dict[str, list[Listing]]] = None):
        self.retailer, self._listings, self.delay, self.fail = retailer, listings, delay_s, fail
        self.by_product = by_product      # product id -> listings a real search would have returned
        self.rate = TokenBucket(1000, 1000)

    async def search(self, product: Product) -> list[Listing]:
        import asyncio
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail:
            raise RuntimeError("upstream 503")
        pool = self.by_product.get(product.id, []) if self.by_product is not None else self._listings
        return [l for l in pool if l.retailer == self.retailer]


def _cond(s: Optional[str]) -> Condition:
    s = (s or "new").lower()
    if "refurb" in s:
        return Condition.REFURBISHED
    if "open" in s:
        return Condition.OPEN_BOX
    if "used" in s or "pre-owned" in s:
        return Condition.USED
    return Condition.NEW


class _HttpAdapter(Adapter):
    base_url = ""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv(f"{self.retailer.upper()}_API_KEY", "")
        self.rate = TokenBucket(4, 8)

    async def _get(self, url: str, params: dict[str, Any], headers: Optional[dict[str, str]] = None) -> Any:
        if httpx is None:
            raise RuntimeError("httpx not installed; pip install 'plum[api]'")
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url, params=params, headers=headers or {})
            r.raise_for_status()
            return r.json()


class EbayBrowseAdapter(_HttpAdapter):
    """eBay Browse API: item_summary/search supports a `gtin` filter, which is the accurate path."""
    retailer = "ebay"
    base_url = "https://api.ebay.com/buy/browse/v1/item_summary/search"

    async def search(self, product: Product) -> list[Listing]:
        params: dict[str, Any] = {"limit": 20}
        g = canonical_gtin(product.gtin)
        if g:
            params["gtin"] = g.lstrip("0")
        else:
            params["q"] = product.title
        data = await self._get(self.base_url, params, {"Authorization": f"Bearer {self.api_key}", "X-EBAY-C-MARKETPLACE-ID": "EBAY_US"})
        return self.parse(data)

    def parse(self, data: dict) -> list[Listing]:
        out = []
        for it in data.get("itemSummaries", []):
            price = it.get("price", {})
            ship = None
            opts = it.get("shippingOptions") or []
            if opts and "shippingCost" in opts[0]:
                ship = float(opts[0]["shippingCost"].get("value", 0))
            out.append(Listing(
                id=f"ebay-{it.get('itemId')}", retailer=self.retailer, title=it.get("title", ""),
                price=float(price.get("value", 0)), url=it.get("itemWebUrl", ""), gtin=it.get("gtin"),
                condition=_cond(it.get("condition")), shipping=ship, seller=(it.get("seller") or {}).get("username"),
            ))
        return out


class WalmartAffiliateAdapter(_HttpAdapter):
    """Walmart Affiliate API product search; `upc` field comes back on most items."""
    retailer = "walmart"
    base_url = "https://developer.api.walmart.com/api-proxy/service/affil/product/v2/search"

    async def search(self, product: Product) -> list[Listing]:
        q = product.gtin or product.title
        data = await self._get(self.base_url, {"query": q, "numItems": 20}, {"WM_SEC.KEY_VERSION": "1", "WM_CONSUMER.ID": self.api_key})
        return self.parse(data)

    def parse(self, data: dict) -> list[Listing]:
        out = []
        for it in data.get("items", []):
            out.append(Listing(
                id=f"walmart-{it.get('itemId')}", retailer=self.retailer, title=it.get("name", ""),
                price=float(it.get("salePrice") or it.get("msrp") or 0), url=it.get("productTrackingUrl") or it.get("productUrl", ""),
                gtin=it.get("upc"), mpn=it.get("modelNumber"), brand=it.get("brandName"),
                shipping=0.0 if it.get("freeShippingOver35Dollars") and float(it.get("salePrice") or 0) >= 35 else (float(it["standardShipRate"]) if it.get("standardShipRate") is not None else None),
                in_stock=(it.get("stock", "Available") == "Available"),
            ))
        return out


class BestBuyAdapter(_HttpAdapter):
    """Best Buy Products API supports `upc=` queries directly."""
    retailer = "bestbuy"
    base_url = "https://api.bestbuy.com/v1/products"

    async def search(self, product: Product) -> list[Listing]:
        q = f"(upc={product.gtin})" if product.gtin else f"(search={product.title})"
        data = await self._get(f"{self.base_url}{q}", {"apiKey": self.api_key, "format": "json", "show": "sku,name,salePrice,regularPrice,upc,modelNumber,manufacturer,url,onlineAvailability,shippingCost,condition", "pageSize": 20})
        return self.parse(data)

    def parse(self, data: dict) -> list[Listing]:
        out = []
        for it in data.get("products", []):
            out.append(Listing(
                id=f"bestbuy-{it.get('sku')}", retailer=self.retailer, title=it.get("name", ""),
                price=float(it.get("salePrice") or it.get("regularPrice") or 0), url=it.get("url", ""),
                gtin=it.get("upc"), mpn=it.get("modelNumber"), brand=it.get("manufacturer"),
                condition=_cond(it.get("condition")), shipping=(float(it["shippingCost"]) if it.get("shippingCost") is not None else None),
                in_stock=bool(it.get("onlineAvailability", True)),
            ))
        return out


class AmazonPaapiAdapter(_HttpAdapter):
    """Amazon Product Advertising API 5 (SearchItems / GetItems). Requires SigV4 signing and an
    Associates account with sales history; left as an interface with the parse half implemented."""
    retailer = "amazon"
    base_url = "https://webservices.amazon.com/paapi5/searchitems"

    async def search(self, product: Product) -> list[Listing]:
        raise NotImplementedError("Wire up SigV4 (or the official python SDK) and call SearchItems with Keywords/ItemIds.")

    def parse(self, data: dict) -> list[Listing]:
        out = []
        for it in (data.get("SearchResult") or {}).get("Items", []):
            offer = ((it.get("Offers") or {}).get("Listings") or [{}])[0]
            price = (offer.get("Price") or {}).get("Amount")
            ext = ((it.get("ItemInfo") or {}).get("ExternalIds") or {})
            upcs = (ext.get("UPCs") or {}).get("DisplayValues") or []
            out.append(Listing(
                id=f"amazon-{it.get('ASIN')}", retailer=self.retailer,
                title=(((it.get("ItemInfo") or {}).get("Title") or {}).get("DisplayValue") or ""),
                price=float(price or 0), url=it.get("DetailPageURL", ""), gtin=upcs[0] if upcs else None,
                condition=_cond(((offer.get("Condition") or {}).get("Value"))),
                shipping=0.0 if (offer.get("DeliveryInfo") or {}).get("IsFreeShippingEligible") else None,
            ))
        return out
