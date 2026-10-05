"""Output 2: the products with the highest discounts online in each industry, checked against other websites.

feeds -> single-product posts -> terms -> industry -> identity -> other sites' prices -> verified discount -> dedupe
-> rank per industry.
"""
from __future__ import annotations

import asyncio
import html as htmllib
import re
import statistics
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from . import industries as ind
from .config import TTL
from .db import Store as DB
from .http import FetchError, follow
from .identity import identify, model_query, models_of
from .models import BASIS_WEIGHT, OnlineDeal, PricePoint
from .reference import norm
from .sources.feeds import SOURCE_NAMES, DealFeeds, Post, plan, post_gone
from .sources.prices import PriceSources, asins_in
from .terms import conditions_of, hedge_of, is_storewide, pct, post_reference, title_price

CONDITIONAL = ("coupon required", "promo code", "Subscribe & Save", "Prime members", "mail-in rebate",
               "discount applied in cart", "& more (price varies by option)", "price varies by size or color")
MAX_AGE = timedelta(hours=72)        # a post older than this is stale unless it states a future end date
COMPARE_PER_INDUSTRY = 10            # cross-site lookups for the leading candidates in each industry
MIN_MARKET_SITES = 2                 # other sites needed before "vs other stores" becomes the discount basis
PER_SELLER_CAP = 5                   # the most deals one seller can hold in an industry's list


@dataclass
class OnlineResult:
    industries: list[str]
    deals: dict[str, list[OnlineDeal]] = field(default_factory=dict)
    excluded: Counter = field(default_factory=Counter)
    sources: list[dict] = field(default_factory=list)
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def all_deals(self) -> list[OnlineDeal]:
        seen, out = set(), []
        for lst in self.deals.values():
            for d in lst:
                if d.id not in seen:
                    seen.add(d.id)
                    out.append(d)
        return out

    def to_dict(self) -> dict:
        return {"industries": self.industries, "generated_at": self.generated_at.isoformat(),
                "deals": {k: [d.to_dict() for d in v] for k, v in self.deals.items()},
                "counts": {k: len(v) for k, v in self.deals.items()},
                "excluded": dict(self.excluded.most_common()), "sources": self.sources}


def classify_post(p: Post) -> ind.Classification:
    if p.source == "dealnews" and p.category:
        c = ind.from_dealnews(p.category, p.feed_industries)
        if c.industries:
            return c
    text = ind.from_text(p.title)
    if p.source == "hip2save" and text.industries:
        # Hip2Save's categories are broad ("beauty" includes vitamins): its feeds are hints, the title decides.
        return ind.Classification(text.industries, f"keywords:{text.rule}+feed hint", p.category)
    if p.feed_industries:
        # A category feed is strong evidence; keywords may add a second industry, never replace the feed's.
        extra = [i for i in text.industries if i not in p.feed_industries][:1] if text.industries else []
        return ind.Classification(p.feed_industries + extra, f"feed:{','.join(p.feeds[:1])}" +
                                  (f"+{text.rule}" if extra else ""), p.category)
    if p.category and p.source == "dealcatcher":
        cat = ind.from_text(p.category)
        if cat.industries:
            return ind.Classification(cat.industries, f"dealcatcher:{p.category}", p.category)
    return text


_EXACT = re.compile(r"(?:for|is|at|to|=|of|drops? to|down to)\s*\*?\s*\$\s?(\d[\d,]*\.\d\d)\b", re.I)
_MULTI = re.compile(r"\b(\d{1,2}) for \$\s?(\d[\d,]*(?:\.\d\d)?)\b", re.I)


def exact_price(text: str, price: float) -> float:
    """Titles round ("$51", "$26.40"); the description usually has the exact figure ("$50.99", "= $26.39").
    Use it when it's within a dollar of the title's."""
    for m in _EXACT.finditer(text or ""):
        v = float(m.group(1).replace(",", ""))
        if abs(v - price) < 1.0 and v != price:
            return v
    return price


def multi_qty(title: str, price: float) -> int:
    """'3 for $15': the quantity the price buys."""
    m = _MULTI.search(title or "")
    if m and int(m.group(1)) > 1 and abs(float(m.group(2).replace(",", "")) - price) < 1.0:
        return int(m.group(1))
    return 1


def score(d: OnlineDeal) -> float:
    discount = d.discount_pct or 0.0
    w = BASIS_WEIGHT.get(d.basis, 0.0)
    conf = 1.0 - 0.08 * len([c for c in d.conditions if c not in ("Prime members",)])
    if any("price varies" in c for c in d.conditions):
        conf -= 0.2
    if any(c.startswith(("store price now", "out of stock")) for c in d.conditions):
        conf = 0.15
    return round(discount * w * max(conf, 0.15), 2)


class OnlineDeals:
    def __init__(self, feeds: DealFeeds, prices: PriceSources, db: Optional[DB] = None):
        self.feeds, self.prices, self.db = feeds, prices, db

    async def run(self, industries: list[str], limit: int = 25, now: Optional[datetime] = None,
                  compare: bool = True) -> OnlineResult:
        now = now or datetime.now(timezone.utc)
        res = OnlineResult(industries)
        wanted = set(industries)
        plans = plan([i for i in industries if ind.BY_ID[i].online])
        results = await asyncio.gather(*(self.feeds.read(p) for p in plans))
        posts: dict[str, Post] = {}
        for p, (got, err) in zip(plans, results):
            res.sources.append({"name": p.name, "ok": not err, "posts": len(got), **({"error": err} if err else {})})
            for post in got:
                if post.id in posts:                       # the same post from two feeds: merge the evidence
                    have = posts[post.id]
                    have.feeds += [f for f in post.feeds if f not in have.feeds]
                    have.feed_industries += [i for i in post.feed_industries if i not in have.feed_industries]
                else:
                    posts[post.id] = post

        candidates: list[OnlineDeal] = []
        for post in posts.values():
            d = self._deal(post, now, res)
            if d is None:
                continue
            if not wanted & set(d.industries):
                res.excluded["other industry"] += 1
                continue
            candidates.append(d)

        candidates = self._dedupe(candidates, res)
        for d in candidates:
            d.score = score(d)
        if compare:
            await self._compare(candidates, wanted)
            live = []
            for d in candidates:
                if d.raw.get("gone"):
                    res.excluded["expired (post removed or marked expired)"] += 1
                else:
                    live.append(d)
            candidates = live
        for d in candidates:
            d.score = score(d)
        for i in industries:
            if not ind.BY_ID[i].online:
                continue
            pool = sorted((d for d in candidates if i in d.industries and d.discount_pct),
                          key=lambda d: (-d.score, -(d.discount_pct or 0), d.title))
            per_seller: Counter = Counter()
            picked: list[OnlineDeal] = []
            for d in pool:
                if per_seller[norm(d.seller)] >= PER_SELLER_CAP:
                    continue
                per_seller[norm(d.seller)] += 1
                picked.append(d)
                if len(picked) >= limit:
                    break
            res.deals[i] = picked
        return res

    # -- one post -----------------------------------------------------------------------------------------------
    def _deal(self, p: Post, now: datetime, res: OnlineResult) -> Optional[OnlineDeal]:
        if p.deal_type == "sale" or is_storewide(p.title):
            res.excluded["storewide sale or many products"] += 1
            return None
        if p.expires_stated and p.expires_at and p.expires_at < now:
            res.excluded["expired"] += 1
            return None
        if re.search(r"\b(?:expired|sold out|dead deal|no longer available)\b", p.title, re.I):
            res.excluded["expired"] += 1
            return None
        fresh = p.posted_at and now - p.posted_at <= MAX_AGE
        future_end = p.expires_stated and p.expires_at and p.expires_at > now
        if not (fresh or future_end):
            res.excluded["older than 72 hours"] += 1
            return None
        tprice, hedge = title_price(p.title)
        price = p.price or tprice
        if not price:
            res.excluded["no price"] += 1
            return None
        price = exact_price(p.text, price)
        qty = multi_qty(p.title, price)
        cls = classify_post(p)
        if not cls.industries:
            res.excluded["no industry"] += 1
            return None
        if p.reference and p.reference > price:
            ref, basis, text = p.reference, "store_regular", f"Reg. ${p.reference:,.2f}"
        elif p.pct_stated and 0 < p.pct_stated < 100:
            ref, basis, text = round(price / (1 - p.pct_stated / 100), 2), "store_regular", f"{p.pct_stated:g}% off"
        else:
            ref, basis, text = post_reference(p.text, price)
        conditions = conditions_of(p.title, p.text[:600])
        hedge = hedge or hedge_of(p.title)
        if hedge:
            conditions.append(hedge)
        if qty > 1:
            conditions.append(f"price is for {qty} (${price / qty:,.2f} each)")
        ident = identify(p.title)
        posted_points = [PricePoint(site=st, price=pr, url=p.url, title=p.title, match="post",
                                    observed_at=p.posted_at or now, via=f"per the {SOURCE_NAMES.get(p.source, p.source)} post")
                         for st, pr in p.others]
        if "fashion" in cls.industries and re.search(r"amazon|walmart|ebay", p.seller, re.I) and not ident.model:
            conditions.append("price varies by size or color")
        return OnlineDeal(
            id=p.id, source=SOURCE_NAMES.get(p.source, p.source), source_url=p.url, title=p.title, seller=p.seller,
            price=price, industries=cls.industries, industry_rule=cls.rule, category=cls.category or p.category,
            reference_price=ref if ref and ref > price else None, basis=basis if ref and ref > price else (
                "history" if basis == "history" else "none"),
            basis_text=text, pct=pct(price, ref), product=ident, conditions=conditions, posted_at=p.posted_at,
            expires_at=p.expires_at if p.expires_stated else None, merchant_url=p.merchant_link,
            comparisons=posted_points,
            image_url=p.image, raw={"feeds": p.feeds, "text": p.text[:1500], "links": p.links[:20]})

    def _dedupe(self, deals: list[OnlineDeal], res: OnlineResult) -> list[OnlineDeal]:
        """The same product posted by several sites: keep the lowest price, remember the others."""
        best: dict[str, OnlineDeal] = {}
        out: list[OnlineDeal] = []
        for d in sorted(deals, key=lambda d: d.price):
            key = d.product.key or f"title:{norm(d.title)[:60]}|{d.price:.2f}"
            if key in best:
                keep = best[key]
                keep.also_posted.append({"source": d.source, "url": d.source_url, "price": d.price, "seller": d.seller})
                keep.industries += [i for i in d.industries if i not in keep.industries]
                res.excluded["same product posted elsewhere"] += 1
                continue
            best[key] = d
            out.append(d)
        return out

    async def _compare(self, deals: list[OnlineDeal], wanted: set[str]) -> None:
        """For the leading candidates in each industry: read the seller's live page when it's Amazon (identity from
        its detail table, and whether the deal is still on), then look the product up on other sites."""
        todo: list[OnlineDeal] = []
        ids: set[str] = set()
        for i in wanted:
            pool = sorted((d for d in deals if i in d.industries and d.pct is not None),
                          key=lambda d: -(d.score or (d.pct or 0)))
            # the leading candidates, plus every deal with a real model number (those are the ones other sites list)
            for d in pool[:COMPARE_PER_INDUSTRY] + [d for d in deals if i in d.industries and model_query(d.product)]:
                if d.id not in ids:
                    ids.add(d.id)
                    todo.append(d)

        async def one(d: OnlineDeal) -> None:
            gone = await self._post_gone(d)
            if gone:
                d.raw["gone"] = gone
                return
            await self._enrich(d)
            q = model_query(d.product)
            if not q:
                return
            sites = ("amazon", "newegg", "flipp") if "tech" in d.industries else ("amazon", "flipp")
            if norm(d.seller) == "amazon":
                sites = tuple(x for x in sites if x != "amazon")
            points, _ = await self.prices.compare(d.product, q, exclude_site=d.seller, near_price=d.price, sites=sites)
            d.comparisons = points + [p for p in d.comparisons if p.site not in {x.site for x in points}]
            if self.db and points:
                self.db.observe_prices({"product_key": d.product.key, "site": pt.site, "title": pt.title,
                                        "price": pt.price, "regular_price": pt.regular_price, "url": pt.url,
                                        "match": pt.match} for pt in points)
            if len(points) >= MIN_MARKET_SITES:                # Slomp's own matches only, not the post's list
                d.market_median = round(statistics.median(pt.price for pt in points), 2)
                d.verified_pct = pct(d.price, d.market_median) if d.market_median > d.price else 0.0
                d.basis = "market"
        await asyncio.gather(*(one(d) for d in todo))

    async def _post_gone(self, d: OnlineDeal) -> str:
        if d.source in ("DealCatcher",):                  # behind a bot wall; can't be checked
            return ""
        try:
            page = await self.prices.http.get(d.source_url, ttl_s=TTL["feed"], html=True)
        except FetchError:
            return ""
        if page.status == 404:
            return "the post was removed (404)"
        return post_gone(d.source_url, page.final_url, page.text, d.title) if page.status == 200 else ""

    async def _amazon_candidates(self, d: OnlineDeal) -> list[str]:
        """Amazon products a deal may point to: product URLs in the post, its dealnews Buy Now link, or product
        links on the post's own page (deal pages also link related products, so callers must validate)."""
        found = asins_in(d.raw.get("text", ""), *d.raw.get("links", []), d.merchant_url)
        if found:
            return found
        if d.source == "dealnews":
            if norm(d.seller) != "amazon":
                return []
            try:
                page = await self.prices.http.get(d.source_url, ttl_s=TTL["page"] * 6, html=True)
            except FetchError:
                return []
            m = re.search(r'href="(https://www\.dealnews\.com/lw/click\.html\?[^"]+)"', page.text)
            final = await follow(self.prices.http, htmllib.unescape(m.group(1))) if m else None
            return asins_in(final or "")
        if d.source in ("Slickdeals", "9to5Toys", "The Inventory", "Ben's Bargains") and norm(d.seller) in ("", "amazon"):
            try:
                page = await self.prices.http.get(d.source_url, ttl_s=TTL["page"] * 6, html=True)
            except FetchError:
                return []
            return asins_in(page.text)[:3]
        return []

    async def _enrich(self, d: OnlineDeal) -> None:
        """Read the Amazon page a deal points to: its identity (brand, model number, UPC) for cross-site lookups,
        and, when Amazon is the seller, whether the deal price is still live."""
        if norm(d.seller) not in ("", "amazon") and model_query(d.product):
            return
        item = None
        for asin in await self._amazon_candidates(d):
            try:
                cand = await self.prices.amazon_item(asin)
            except FetchError:
                return
            if cand and same_listing(d.title, cand.title, cand.brand):
                item = cand
                break
        if not item:
            return
        if not d.seller:
            d.seller = "Amazon"
        if norm(d.seller) == "amazon" and item.price is not None:
            unit = round(d.price / multi_qty(d.title, d.price), 2)
            d.store_check = {"site": "Amazon", "url": item.url, "price": item.price, "unavailable": item.unavailable,
                             "checked_at": datetime.now(timezone.utc).isoformat()}
            conditional = any(c in d.conditions for c in CONDITIONAL)
            if item.unavailable:
                d.conditions.append("out of stock at the store when checked")
            elif item.price > unit * 1.03 + 0.25 and not conditional:
                d.conditions.append(f"store price now ${item.price:,.2f} (the deal may have ended)")
        if not model_query(d.product):
            models = [m for raw in item.models for m in models_of(raw, item.brand)]
            ident = identify(f"{item.brand} {item.title}", item.brand, item.upc)
            if models:
                ident.model = models[0]
                ident.attrs["models"] = ",".join(dict.fromkeys(models + [x for x in ident.attrs.get("models", "").split(",") if x]))
            if ident.model and not ident.accessory:
                ident.attrs["via"] = f"amazon:{item.asin}"
                d.product = ident


_STOP = {"with", "for", "and", "the", "free", "shipping", "shipped", "only", "just", "deal", "amazon", "prime", "members",
         "pack", "count", "new", "set", "off", "now", "via", "from", "your", "this", "that"}


def same_listing(post_title: str, amazon_title: str, brand: str) -> bool:
    """Is this Amazon page the product the post is about? Most of the post title's distinctive words must appear on
    the page, and the brand, when the post names it."""
    def words(t: str) -> set[str]:
        return {w for w in re.findall(r"[a-z0-9]{3,}", (t or "").lower()) if w not in _STOP and not w.isdigit()}
    pw, aw = words(re.sub(r"\$\s?[\d,.]+", " ", post_title)), words(amazon_title)
    if not pw or not aw:
        return False
    if brand and norm(brand) and norm(brand) in norm(post_title) and norm(brand) not in norm(amazon_title):
        return False
    return len(pw & aw) / len(pw) >= 0.5
