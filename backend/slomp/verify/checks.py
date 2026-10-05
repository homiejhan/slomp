"""The live tests. Each takes one subject (a deal Slomp returned, or a source item) and re-checks it against the
source through a fetch path the pipeline didn't use, returning (verdict, detail) with verdict pass | fail |
inconclusive (the check couldn't be made: a source was down, blocked, or doesn't cover the subject).
"""
from __future__ import annotations

import random
import re
from datetime import datetime
from typing import Optional
from urllib.parse import urlsplit

from .. import industries as ind
from ..geo import ad_end_local, ad_start_local, days_between, miles, parse_time
from ..http import Blocked, Disallowed, FetchError, PoliteClient, follow
from ..identity import identify, norm_model, same_product
from ..local import LocalResult
from ..models import LocalDeal, OnlineDeal
from ..online import same_listing
from ..reference import merchant as merchant_entry, norm, store_from_domain
from ..sources.flipp import API as FLIPP_API, junk_reason
from ..terms import is_storewide, money
from . import atp, pages

Verdict = tuple[str, dict]
PASS, FAIL, INCONCLUSIVE = "pass", "fail", "inconclusive"
FRESH = 60          # cache lifetime for re-fetches: verification always reads the source as it is now


async def fresh_item(http: PoliteClient, item_id: int) -> dict:
    r = await http.get(f"{FLIPP_API}/items/{item_id}", ttl_s=FRESH, use_cache=False)
    return (r.json() if r.status == 200 else {}).get("item") or {}


def shown_price(d: LocalDeal) -> Optional[float]:
    t = d.terms
    return t.bundle_price if t.qty > 1 and t.bundle_price else t.price


# --- local ---------------------------------------------------------------------------------------------------------
async def local_fidelity(http: PoliteClient, d: LocalDeal, tz: str) -> Verdict:
    rec = await fresh_item(http, d.item_id)
    if not rec:
        return FAIL, {"why": "the item no longer exists at the source"}
    issues = []
    if merchant_entry(rec.get("merchant", "")).name != d.merchant:
        issues.append(f"merchant: source {rec.get('merchant')!r} vs shown {d.merchant!r}")
    if norm(rec.get("name", "")) != norm(d.title):
        issues.append(f"title: source {rec.get('name')!r} vs shown {d.title!r}")
    src_price = money(rec.get("current_price"))
    mine = shown_price(d)
    if mine is not None and src_price is not None and abs(src_price - mine) > 0.011:
        issues.append(f"price: source {src_price} vs shown {mine}")
    if mine is None and src_price is None and not (d.terms.pct or d.terms.savings):
        issues.append("no price or saving shown")
    vf, vt = parse_time(rec.get("valid_from")), parse_time(rec.get("valid_to"))
    if vf and vt:
        if ad_start_local(vf, tz) != d.valid_from or ad_end_local(vt, tz) != d.valid_to:
            issues.append(f"dates: source {ad_start_local(vf, tz):%b %d}-{ad_end_local(vt, tz):%b %d} vs shown "
                          f"{d.valid_from:%b %d}-{d.valid_to:%b %d}")
    return (FAIL if issues else PASS), {"issues": issues, "source_price": src_price, "shown_price": mine}


async def local_window(http: PoliteClient, d: LocalDeal, tz: str, start: datetime, end: datetime) -> Verdict:
    rec = await fresh_item(http, d.item_id)
    vf, vt = parse_time(rec.get("valid_from")), parse_time(rec.get("valid_to"))
    if not (vf and vt):
        return INCONCLUSIVE, {"why": "the source no longer gives dates"}
    vf_l, vt_l = ad_start_local(vf, tz), ad_end_local(vt, tz)
    issues = []
    if vt_l < start or vf_l > end:
        issues.append(f"outside the window: {vf_l:%b %d %H:%M}-{vt_l:%b %d %H:%M}")
    if days_between(start, vt_l, tz) != d.ends_in_days:
        issues.append(f"'ends in' label {d.ends_in_days} days, source says {days_between(start, vt_l, tz)}")
    if max(0, days_between(start, vf_l, tz)) != d.starts_in_days:
        issues.append(f"'starts in' label {d.starts_in_days} days, source says {max(0, days_between(start, vf_l, tz))}")
    return (FAIL if issues else PASS), {"issues": issues, "valid": f"{vf_l:%a %b %d}-{vt_l:%a %b %d}"}


def _osm_stores(merchant: str) -> list:
    from ..sources.stores import _dataset
    return _dataset()["merchants"].get(merchant) or []


def local_vicinity(d: LocalDeal, city_lat: float, city_lon: float, radius_mi: float) -> Verdict:
    """Does the chain's own store locator (AllThePlaces) show a store within the radius? Independent of the
    OpenStreetMap data Slomp used."""
    if d.store_status == "unmapped":
        return INCONCLUSIVE, {"why": "Slomp flags this store as unconfirmed; nothing to verify"}
    pts = atp.stores(d.merchant)
    if pts is None:
        return INCONCLUSIVE, {"why": f"no store-locator data for {d.merchant}"}
    osm_count = len(_osm_stores(d.merchant))
    tx = [p for p in pts if 25.8 <= p[0] <= 36.6 and -106.7 <= p[1] <= -93.5]
    if not tx or len(tx) < 0.5 * osm_count:
        return INCONCLUSIVE, {"why": f"store-locator data for {d.merchant} looks incomplete "
                                     f"({len(tx)} Texas stores vs {osm_count} mapped)"}
    near = min(pts, key=lambda p: miles(city_lat, city_lon, p[0], p[1]))
    dist = miles(city_lat, city_lon, near[0], near[1])
    detail = {"locator_nearest_mi": round(dist, 1), "locator_store": near[3], "slomp_store_mi": d.store.distance_mi
              if d.store else None, "slomp_store": d.store.address if d.store else None}
    if d.store:
        same = min(miles(d.store.lat, d.store.lon, p[0], p[1]) for p in pts)
        detail["slomp_store_confirmed_within_mi"] = round(same, 2)
    if dist <= radius_mi + 1.0:
        return PASS, detail
    return FAIL, {**detail, "why": f"the chain's own locator shows no store within {radius_mi:g} mi"}


RETAILER_BLOCKED = ("kohls.com", "harborfreight.com", "cvs.com", "tractorsupply.com", "dickssportinggoods.com",
                    "walmart.com", "cabelas.com", "gamestop.com", "kroger.com", "homedepot.com", "bestbuy.com",
                    "lowes.com")


async def local_retailer(http: PoliteClient, d: LocalDeal) -> Verdict:
    """The retailer's own product page, read fresh: does it show the ad's price, or at least the regular price
    Slomp states? Weekly-ad prices can be in-store only, so a page showing the regular price is noted, not failed."""
    if not d.retailer_url or any(b in d.retailer_url for b in RETAILER_BLOCKED):
        return INCONCLUSIVE, {"why": "no readable retailer page"}
    page, info = await _page(http, d.retailer_url)
    if page is None:
        return INCONCLUSIVE, {"why": info}
    text = pages.plain(page)
    offer = pages.jsonld_offer(page).get("price")
    shown = shown_price(d)
    detail = {"url": d.retailer_url[:160], "ad_price": shown, "regular_shown": d.terms.regular, "page_offer": offer}
    if shown is None:
        return INCONCLUSIVE, {**detail, "why": "a promotion without a single price"}
    if (offer and abs(offer - shown) <= 0.011) or pages.has_price(text, shown):
        return PASS, {**detail, "result": "the retailer's page shows the ad price"}
    if d.terms.regular and ((offer and abs(offer - d.terms.regular) <= 0.011) or pages.has_price(text, d.terms.regular)):
        return PASS, {**detail, "result": "the page shows the regular price Slomp states; the ad price is the store's"}
    if offer is None:
        return INCONCLUSIVE, {**detail, "why": "the page doesn't expose the product's price to a script"}
    return FAIL, {**detail, "why": f"the retailer's page shows ${offer} (neither the ad price nor the stated regular price)"}


async def local_math(http: PoliteClient, d: LocalDeal) -> Verdict:
    t = d.terms
    issues = []
    if t.price is not None and t.regular is not None and t.pct is not None and not t.bogo:
        exp = round((1 - t.price / t.regular) * 100, 1)
        if abs(exp - t.pct) > 0.15:
            issues.append(f"percent {t.pct} doesn't follow from {t.price} vs {t.regular} ({exp})")
        if t.savings is not None and abs((t.regular - t.price) - t.savings) > 0.011:
            issues.append(f"savings {t.savings} != {t.regular} - {t.price}")
    rec = await fresh_item(http, d.item_id)
    if rec:
        text = " ".join(str(rec.get(k) or "") for k in ("name", "sale_story", "pre_price_text", "price_text"))
        if re.search(r"\bBOGO\b|\bbuy \d+,? get \d+\b|\bbuy one,? get one\b", text, re.I) and not t.bogo:
            issues.append("source is a buy-X-get-Y offer; Slomp didn't read it as one")
        pct_src = rec.get("percent_off")
        if pct_src and t.pct and not t.bogo and t.qty == 1 and abs(float(pct_src) - t.pct) > 1.5:
            issues.append(f"percent: source {pct_src} vs shown {t.pct}")
        dol = money(rec.get("dollars_off"))
        if dol and t.savings and t.qty == 1 and not t.bogo and abs(dol - t.savings) > 0.02 and t.basis != "list":
            issues.append(f"savings: source ${dol} vs shown ${t.savings}")
        orig = money(rec.get("original_price"))
        if orig and t.regular and abs(orig - t.regular) > 0.02 and t.qty == 1:
            issues.append(f"regular price: source ${orig} vs shown ${t.regular}")
    return (FAIL if issues else PASS), {"issues": issues, "summary": t.summary}


async def local_recall(http: PoliteClient, res: LocalResult, industry: str, rng: random.Random,
                       flipp) -> Verdict:
    """Pick a random item with a stated saving from one of the city's ads that the source itself files under this
    industry, and check Slomp shows it or excluded it for a valid reason."""
    flyers = [f for f in await flipp.flyers(res.city.zip)
              if ad_end_local(f.valid_to, res.city.tz) >= res.window_start
              and ad_start_local(f.valid_from, res.city.tz) <= res.window_end]
    rng.shuffle(flyers)
    shown = {d.item_id: d for d in res.all_deals()}
    for f in flyers[:6]:
        items = [i for i in await flipp.flyer_items(f.id) if not junk_reason(i)]
        hits = {i.get("id"): i for i in await flipp.merchant_items(res.city.zip, f.merchant)}
        pool = []
        for it in items:
            h = hits.get(it.get("id"))
            if not h or not (it.get("discount") or h.get("original_price")):
                continue
            if industry in ind.from_taxonomy(h.get("_L1"), h.get("_L2")).industries:
                pool.append((it, h))
        if not pool:
            continue
        it, h = rng.choice(pool)
        iid = int(it["id"])
        subject = {"item": it.get("name"), "merchant": f.merchant, "taxonomy": f"{h.get('_L1')} > {h.get('_L2')}"}
        if iid in shown:
            return PASS, {**subject, "shown_as": shown[iid].kind}
        why = res.excluded_items.get(iid)
        if why is None:
            return FAIL, {**subject, "why": "qualifying item missing from Slomp's output with no recorded reason"}
        ok_reasons = ("nearest store", "no store within", "item already ended", "item starts after", "same item in",
                      "implausible saving")
        if why.startswith(ok_reasons):
            return PASS, {**subject, "excluded_for": why}
        if why.startswith("other industry"):
            # This oracle is the source's own category. Slomp departs from it only on purpose (a dog gate at PetSmart
            # that Flipp files under Baby Safety, a diamond ring at JCPenney filed under Food), so the blind-judge
            # tests, not this oracle, decide who is right.
            return INCONCLUSIVE, {**subject, "why": f"Slomp overrides the source's category on purpose ({why})"}
        return FAIL, {**subject, "excluded_for": why}
    return INCONCLUSIVE, {"why": f"no {industry} item with a stated saving in this city's ads"}


# --- online --------------------------------------------------------------------------------------------------------
async def _page(http: PoliteClient, url: str) -> tuple[Optional[str], str]:
    try:
        r = await http.get(url, ttl_s=FRESH, html=True, use_cache=False)
    except Disallowed:
        return None, "robots.txt disallows the page"
    except Blocked:
        return None, "the site served a bot check"
    except FetchError as e:
        return None, e.reason
    if r.status != 200:
        return None, f"HTTP {r.status}"
    return r.text, str(r.final_url)


async def _follow(http: PoliteClient, url: str) -> Optional[str]:
    return await follow(http, url, ttl_s=FRESH)


def _title_tokens(title: str) -> list[str]:
    t = re.sub(r"\$\s?\d[\d,.]*|\b(for|with|and|the|free|shipping|shipped|only|just|deal|on|at|via|amazon|w/)\b", " ",
               title.lower())
    return [w for w in re.findall(r"[a-z0-9][a-z0-9'-]{2,}", t)][:10]


async def online_fidelity(http: PoliteClient, d: OnlineDeal) -> Verdict:
    page, info = await _page(http, d.source_url)
    if page is None:
        return INCONCLUSIVE, {"why": info}
    text = pages.plain(page)
    issues = []
    if d.price > 0 and not pages.has_price(text, d.price):     # restaurant promotions carry no single price
        issues.append(f"price ${d.price} not on the post page")
    toks = _title_tokens(d.title)
    found = [w for w in toks if w in text.lower()]
    if toks and len(found) / len(toks) < 0.5:
        issues.append(f"title words missing from the page ({len(found)}/{len(toks)})")
    exp = pages.expired_marker(text)
    if exp:
        issues.append(f"post marked expired ({exp!r})")
    return (FAIL if issues else PASS), {"issues": issues, "page": info}


async def online_merchant(http: PoliteClient, d: OnlineDeal) -> Verdict:
    """Follow the deal to the store: the link must land on the claimed store, and a product page price, when
    there is one, must match (codes, coupons and memberships can explain a difference)."""
    links = pages.direct_links(d.raw.get("text", ""))
    if not links and d.source == "dealnews":
        page, _ = await _page(http, d.source_url)
        buy = pages.dealnews_buy_link(page or "")
        if buy:
            final = await _follow(http, buy)
            if final is None:
                return INCONCLUSIVE, {"why": "the dealnews link couldn't be followed (robots or network)"}
            links = [final]
    if not links and d.source not in ("Hip2Save", "DealCatcher"):
        page, _ = await _page(http, d.source_url)
        links = pages.direct_links(page or "")
    if not links and d.store_check.get("url"):
        links = [d.store_check["url"]]            # the store page Slomp resolved; re-read fresh below
    if not links:
        return INCONCLUSIVE, {"why": "no direct store link in the post"}
    url = links[0]
    host = urlsplit(url).netloc
    store = store_from_domain(host)
    detail = {"link": url[:160], "store_from_link": store, "seller_shown": d.seller}
    if d.seller and norm(store) != norm(d.seller) and not norm(d.seller).startswith(norm(store)[:5]):
        return FAIL, {**detail, "why": "the link goes to a different store than the one shown"}
    if "amazon.com" in host and pages.asin_of(url):
        page, info = await _page(http, f"https://www.amazon.com/dp/{pages.asin_of(url)}")
        if page is None:
            return (PASS if d.seller else INCONCLUSIVE), {**detail, "price_check": info}
        prod = pages.amazon_product(page)
        if prod.get("title") and not same_listing(d.title, prod["title"], ""):
            detail["store_title"] = prod["title"][:100]
            if pages.asin_of(d.store_check.get("url", "")) == pages.asin_of(url):
                return FAIL, {**detail, "why": "Slomp's store check points at a different product"}
            # A store link found on the post page (posts also link related products), or a headline-style title
            # that shares few words with the listing: not evidence about the deal Slomp shows.
            return INCONCLUSIVE, {**detail, "why": "can't confirm this store link is the deal's product"}
        p = prod.get("price")
        qty = next((int(m.group(1)) for c in d.conditions for m in [re.match(r"price is for (\d+)", c)] if m), 1)
        unit = round(d.price / qty, 2)
        detail.update({"store_price": p, "store_title": prod.get("title", "")[:100], "deal_unit_price": unit})
        if p is None:
            return PASS, {**detail, "price_check": "no buy-box price on the page"}
        if abs(p - unit) <= max(0.5, 0.02 * unit):
            return PASS, detail
        flagged = next((c for c in d.conditions if c.startswith("store price now")), None)
        if flagged and abs(money(flagged) - p) <= max(0.5, 0.02 * p):
            return PASS, {**detail, "price_check": f"Slomp already shows the store's current price ({flagged})"}
        conditional = [c for c in d.conditions if c in ("coupon required", "promo code", "Subscribe & Save",
                                                        "Prime members", "mail-in rebate", "discount applied in cart",
                                                        "& more (price varies by option)", "price varies by size or color")]
        if conditional and p > unit:
            return PASS, {**detail, "price_check": f"store price is before the stated condition ({conditional[0]})"}
        return FAIL, {**detail, "why": f"store page price ${p} vs deal ${unit}"}
    return PASS, detail


async def online_comparison(http: PoliteClient, d: OnlineDeal, i: int) -> Verdict:
    pt = d.comparisons[i]
    detail = {"site": pt.site, "shown_price": pt.price, "url": pt.url[:160], "deal": d.title[:80]}
    if not pt.url:
        return INCONCLUSIVE, {**detail, "why": "no link for this listing"}
    if pt.match == "post":                       # a price the deal post itself lists for another store
        page, info = await _page(http, pt.url)
        if page is None:
            return INCONCLUSIVE, {**detail, "why": info}
        text = pages.plain(page)
        ok = pages.has_price(text, pt.price) and pt.site.lower() in text.lower()
        return (PASS if ok else FAIL), {**detail, "issues": [] if ok else [f"the post no longer lists {pt.site} at ${pt.price}"]}
    if "flipp.com" in pt.url:
        iid = re.search(r"/item/(\d+)", pt.url)
        rec = await fresh_item(http, int(iid.group(1))) if iid else {}
        title, price = rec.get("name", ""), money(rec.get("current_price"))
    elif "amazon.com" in pt.url:
        page, info = await _page(http, pt.url)
        if page is None:
            return INCONCLUSIVE, {**detail, "why": info}
        prod = pages.amazon_product(page)
        title, price = prod.get("title", ""), prod.get("price")
    else:
        page, info = await _page(http, pt.url)
        if page is None:
            return INCONCLUSIVE, {**detail, "why": info}
        prod = pages.jsonld_offer(page)
        title, price = prod.get("title", "") + " " + prod.get("model", ""), prod.get("price")
    detail.update({"page_title": title[:120], "page_price": price})
    if not title:
        return INCONCLUSIVE, {**detail, "why": "page has no product title"}
    ok, why = same_product(d.product, identify(title, d.product.brand if "amazon" in pt.url else ""))
    issues = [] if ok else [f"not the same product ({why})"]
    if price is None:
        issues.append("no price on the page")
    elif abs(price - pt.price) > max(1.0, 0.02 * pt.price):
        issues.append(f"page price ${price} vs shown ${pt.price}")
    return (FAIL if issues else PASS), {**detail, "issues": issues}


def online_ranking(d: OnlineDeal, lst: list[OnlineDeal], now: datetime) -> Verdict:
    issues = []
    if d.basis == "market":
        if not d.market_median or len(d.comparisons) < 2:
            issues.append("'vs other stores' basis without 2+ comparisons")
        elif d.verified_pct and abs((1 - d.price / d.market_median) * 100 - d.verified_pct) > 0.15:
            issues.append("verified percent doesn't follow from price and median")
    elif d.reference_price and d.pct is not None:
        if abs((1 - d.price / d.reference_price) * 100 - d.pct) > 0.15:
            issues.append("percent doesn't follow from price and reference")
    if is_storewide(d.title):
        issues.append("storewide sale in the product list")
    fresh = d.posted_at and (now - d.posted_at).total_seconds() <= 72 * 3600 + 3600
    if not fresh and not (d.expires_at and d.expires_at > now):
        issues.append("post older than 72 hours with no future end date")
    idx = lst.index(d)
    if idx > 0 and lst[idx - 1].score + 1e-6 < d.score:
        issues.append("ranked above a higher-scoring deal")
    keys = [x.product.key for x in lst if x.product.key]
    if d.product.key and keys.count(d.product.key) > 1:
        issues.append("same product listed twice")
    return (FAIL if issues else PASS), {"issues": issues, "rank": idx + 1, "score": d.score}
