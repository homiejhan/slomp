# Slomp v1: system design

Slomp takes a **Texas city** and one or more **industries** and returns:

1. **Near you, next 7 days:** every known deal, discount or promotion at stores in the vicinity of that city that is valid at
   any point in the next 7 days, filtered to the chosen industries.
2. **Biggest discounts online:** the products in the chosen industries with the highest discounts right now, each
   checked against what other websites charge for the *same* product.

Everything is built on public, keyless sources. This document records the requirements, the research behind each source
choice (all verified live on **Oct 4, 2026**), the architecture, the trade-offs, and how accuracy is verified.

---

## 1. Requirements

### 1.1 Functional

| # | Requirement |
|---|---|
| F1 | Inputs come from fixed lists: a city from **all Texas cities** (every incorporated city, town and village, plus census-designated places with 10,000+ people), and 1+ industries from a fixed set of 13 (14 since the regular-deals addendum in section 10). |
| F2 | Output 1 lists **all** deals at stores within a radius of the city (default 25 mi) whose validity window overlaps `[now, now + 7 days]`, in the city's own time zone. |
| F3 | Output 2 lists the products with the **highest discounts** in each chosen industry, with the same product's price on other websites where it can be found. |
| F4 | Every deal says **what its discount is measured against** (the store's own regular price, other stores' prices, a list price, or nothing) and carries links to its source. |
| F5 | Results explain what was left out and why (expired, too far away, not a real discount, storewide sale, duplicate). |
| F6 | A web page, a JSON API and a CLI expose the same results. |
| F7 | A live verification harness runs 200 accuracy and quality tests per iteration against the sources themselves. |

### 1.2 Non-functional

| Property | Target | Why |
|---|---|---|
| Accuracy (source fidelity) | ≥ 98% of displayed prices, dates and merchants match the source exactly | A deal app that misquotes prices is worse than none |
| Industry precision | ≥ 90% of deals belong to the chosen industry (blind judge) | Wrong-industry results read as noise |
| Vicinity | ≥ 95% of local deals have a mapped store of that merchant within the radius | "Near you" must mean near you |
| Freshness | 0 expired deals; local ads refreshed at least daily; online feeds every 30 min | Deals expire fast |
| Latency | Warm city < 2 s; cold city < 45 s (one-time per ZIP per day); online < 3 s warm | Single user, testing phase |
| Cost | $0: no paid APIs, runs on a laptop | Constraint |
| Politeness | Per-host rate limits, caching, robots.txt respected for HTML pages, honest User-Agent | We depend on others' goodwill |
| Degradation | A failing source removes only its own results, and the response says so | 10+ independent sources |

### 1.3 Constraints and assumptions

- **Public, keyless data only.** No API keys, logins, captcha solving, or bot-wall circumvention. A source that blocks
  automated clients is not used.
- **Texas only, for testing.** The design is state-agnostic (city list and time zones are data), so other states are a
  data build, not a code change.
- **Single process, single user.** One Python service with SQLite. Section 7 covers what changes at scale.
- **"Vicinity"** = the merchant has a mapped store within the radius of the city's census internal point (default 25 mi,
  options 10/25/50).
- **"Next 7 days"** = the deal is valid at some moment in `[now, now + 7d]`. Deals starting later in the window are
  included and labelled ("starts Wed").
- **Prices can change after publication.** Weekly ads are the retailer's published claim; every deal links to the
  source so the user can confirm.

---

## 2. What the research found

Each row was checked live on Oct 4, 2026. "Honest UA" means the source answers a client that identifies itself as
`Slomp/1.0` rather than impersonating a browser.

### 2.1 Local deals and store locations

| Source | What it gives | Verdict |
|---|---|---|
| **Flipp weekly ads** (`backflipp.wishabi.com/flipp`): `/flyers?postal_code=` | Every weekly ad for a ZIP: 47 in Austin 78701, 70–72 in Houston ZIPs; merchant, validity, merchant-level category | **Use.** Backbone of Output 1 |
| Flipp `/flyers/{id}` | All items in an ad: name, price, headline % off, per-item validity | **Use** |
| Flipp `/items/search?q={merchant}` | All of that merchant's ad items (≤150) **with Google Product Taxonomy categories** (`_L1`/`_L2`) and `original_price` | **Use** for industry classification. Best Buy: 116/116 items labelled, Old Navy 51/51 |
| Flipp `/items/{id}` | Full record: sale story, $ off, % off, description, disclaimer, retailer product URL | **Use** for top items and for verification |
| OpenStreetMap, Geofabrik Texas extract (723 MB, daily) | Every mapped store: 8,871 stores of 76 registry merchants and 16,867 locations of 399 restaurant chains, extracted in 20 s | **Use.** Built into a local dataset weekly. Live Overpass was tried first: the public servers answered 406, timed out or returned 504 under load |
| AllThePlaces (weekly scrape of chains' own store locators) | Per-chain GeoJSON with addresses | **Verification only.** Independent of OSM, but uneven run to run (Target 545–1,370 US stores; Walmart in 1 of 6 runs), so it checks Slomp rather than feeding it |
| US Census Gazetteer 2026 + PEP 2025 + ACS 2024 | Every Texas place with type, internal point, population; ZCTA centroids | **Use** for the fixed city list |
| Google Product Taxonomy (2021-09-21) | The 21 top-level and ~190 second-level categories Flipp labels items with | **Use** as the industry mapping backbone |

### 2.2 Online deals

| Source | What it gives | Verdict |
|---|---|---|
| **Slickdeals RSS** (frontpage, popular, keyword search) | 25 items per feed, fresh (newest minutes old); title carries price and store; description carries code/coupon conditions. No paging | **Use**; keyword feeds per industry widen coverage |
| **dealnews category RSS** (`/c{id}/{name}/?rss=1`) | 20–50 items per category with editor comparisons: "You'd pay $65 elsewhere", "best price we could find by $2", "$419 off the $703 list price" | **Use**; categories map cleanly to industries (Electronics c142, Computers c39, Sports c211, Clothing c202, Home c196, Health c765, Beauty c759, Groceries c214, Pets c221, Baby c224, Toys c226, Automotive c238, Office c182, Restaurants c377) |
| Hip2Save category feeds | "Only $X on <Store> (Reg. $Y)": groceries, beauty, baby, kids, toys, pets, office, home | **Use**; fills industries dealnews covers thinly |
| Ben's Bargains, The Inventory, 9to5Toys, DealCatcher | General feeds; "$X at <Store>", "is now $36.27 (40% off)" | **Use**, classified by keywords |
| Woot API, TechBargains, Brad's Deals, DealsPlus, Reddit JSON | Key required, Cloudflare, bot page, dead domain, 403 | **No** (Reddit RSS works but allows one request per 40 s) |

### 2.3 Cross-site prices (the "same product on other websites" part)

| Site | Reachable by a script? | Price data | Verdict |
|---|---|---|---|
| Amazon | Yes (search and product pages, robots-allowed) | Price, list price, ASIN in search HTML | **Use**, ≤ 1 req / 3 s |
| Best Buy | Only to clients posing as browsers; an honestly identified client's connections hang | `priceBlocks` JSON | **No.** Best Buy prices still arrive through its Flipp weekly ad |
| Newegg | Yes | `window.__initialState__`: FinalPrice, original price, **Model** | **Use** (tech) |
| Flipp search by model | Yes | This week's ad price at ~70 Texas merchants (Walmart, Best Buy, Target, Costco, Kohl's, …) | **Use** (all industries) |
| Foot Locker | Yes | Prices in search HTML | **Use** (sneakers by style code) |
| Academy | Yes | JSON-LD offers | **Use** (sports, outdoors) |
| Costco, Sam's Club | Yes (allowed paths) | Search HTML / `__NEXT_DATA__` | **Maybe** (bulk/home) |
| PetSmart, Office Depot | Product pages only; search disallowed by robots.txt | JSON-LD | **No** (can't discover products) |
| Walmart, Target, eBay, Home Depot, Lowe's, Kohl's, Macy's, Dick's, GameStop, Staples, B&H, Adorama, Micro Center, Chewy, camelcamelcamel | No: bot walls (PerimeterX, Akamai, Cloudflare) or 403 | | **No**: never circumvented |

Consequence: cross-site comparison is strongest for **Tech** (model numbers; Amazon, Best Buy, Newegg, Flipp) and
weakest for **Fashion/Beauty** (no model numbers; key retailers blocked). The design treats comparison coverage as a
measured quantity per industry rather than promising it everywhere.

### 2.4 Local promotions beyond weekly ads

Restaurant-chain promotions (dealnews Restaurants c377, Slickdeals restaurant search and freebies forum) are national
promotions honored at local branches, such as Chuy's free entrée on National Taco Day (Oct 6) or KFC's $10 Tuesday
bucket. Slomp shows one only when OSM has a branch within the radius and its dates (ranges, "through Oct 21", "every
Tuesday") overlap the window. Checked and not used: Groupon and Simon malls (bot walls); Eventbrite and DoStuff event
listings (only some metros, and events fit no industry); MLB promotions (no Texas home games Oct 4–11); Texas sales-tax
holidays (none in the window; a static table if added).

### 2.5 Lessons carried over from Slomp v0.2

The previous build (in git history) taught rules this design keeps:

- An ad's "You save $76" can be a **compare-at** price, not the store's own. Firm savings need the store's regular price.
- BOGO "50% off" is a 25% saving; "2 for $8" must keep its quantity; "up to" is a ceiling, not a promise.
- Page furniture and placeholder codes (`BESBU093025390110`) are not items.
- Per-item dates beat ad dates (one item ran a single day inside a week-long ad).
- Matching across sites must use real identifiers (model numbers, GTINs, screen sizes), never loose text similarity.
- Price aggregators with stale offers (UPCitemdb) are worse than no comparison.

---

## 3. High-level design

### 3.1 Components

```
                 ┌─────────────────────────────────────────────────────────┐
  Browser ──────►│  Web page (static)          CLI (slomp ...)               │
                 └───────────────┬────────────────────────┬────────────────┘
                                 ▼                        ▼
                 ┌─────────────────────────────────────────────────────────┐
                 │  API (FastAPI)  /api/v1/meta  /local  /online  /health  │
                 └───────────────┬─────────────────────────────────────────┘
                                 ▼
                 ┌─────────────────────────────────────────────────────────┐
                 │  SlompService: validates inputs against the fixed lists, │
                 │  fans out to both pipelines, caches results 30 min      │
                 └──────┬──────────────────────────────────────┬───────────┘
                        ▼                                      ▼
   ┌──────────────────────────────────────┐   ┌─────────────────────────────────────────┐
   │ Local pipeline (Output 1)            │   │ Online pipeline (Output 2)              │
   │ city → ZIP → ads → items → terms     │   │ feeds → single-product offers → terms   │
   │ → industry → stores/distance         │   │ → industry → product identity           │
   │ → 7-day window → rank                │   │ → cross-site prices → verified discount │
   │ + restaurant/local promotions        │   │ → dedupe → rank                         │
   └──────────────┬───────────────────────┘   └───────────────┬─────────────────────────┘
                  ▼                                           ▼
   ┌─────────────────────────────────────────────────────────────────────────────────────┐
   │ Shared domain modules: industries (taxonomy maps) · terms (price/claim parsing)      │
   │ identity (brand, model, GTIN, size) · geo (distance, time zones) · ranking          │
   └─────────────────────────────────────┬───────────────────────────────────────────────┘
                                         ▼
   ┌─────────────────────────────────────────────────────────────────────────────────────┐
   │ Source connectors: flipp · stores (Overpass, AllThePlaces) · feeds (Slickdeals,     │
   │ dealnews, …) · prices (Amazon, Best Buy, Newegg, Flipp, Foot Locker, Academy) · promos│
   └─────────────────────────────────────┬───────────────────────────────────────────────┘
                                         ▼
   ┌─────────────────────────────────────────────────────────────────────────────────────┐
   │ PoliteHTTP: per-host rate limits · retries with backoff · circuit breaker per host  │
   │ · hard deadline · robots.txt check for HTML · honest User-Agent · response cache    │
   └─────────────────────────────────────┬───────────────────────────────────────────────┘
                                         ▼
   ┌─────────────────────────────────────────────────────────────────────────────────────┐
   │ SQLite (~/.cache/slomp/slomp.db): http_cache · price_observations · verify_runs/results│
   │ Reference data (in repo): texas_cities.json · merchants.json · industries           │
   └─────────────────────────────────────────────────────────────────────────────────────┘

   Verification harness (slomp verify) ── calls SlompService like a user, then re-checks a
   sample of results against the sources through its own, independent fetch paths.
```

### 3.2 Data flow: Output 1 (near you, next 7 days)

1. **Resolve the city** from `texas_cities.json`: internal point, representative ZIP, county, time zone (El Paso and
   Hudspeth counties are Mountain time; the rest of Texas is Central).
2. **Ads:** `GET /flyers?postal_code={zip}`. Keep ads whose window overlaps `[now, now+7d]`. Ads starting later in the
   window are kept and labelled.
3. **Items:** for each ad, `GET /flyers/{id}` (prices, % off, per-item dates) and `GET /items/search?q={merchant}`
   (taxonomy, original price, sale story). Join on item id. Drop page furniture, placeholders and items outside the
   window, counting each reason.
4. **Terms:** parse each item into a typed claim (price, regular price, $ off, % off, multi-buy, BOGO, hedges such as
   "up to" and "starting at", conditions such as "with card"). An item with a price but no stated saving is an ad
   price, not a deal, and is excluded.
5. **Industry:** map `_L1/_L2` through the taxonomy table; fall back to the merchant's ad category and keyword rules.
   Keep items in the chosen industries.
6. **Stores:** look up the nearest mapped store of each merchant in the local Texas dataset (OSM, matched by
   `brand:wikidata` or exact name). Merchants with no store in range are excluded and counted. Merchants the map can't
   speak for (no brand id and no mapped stores, or chains OSM is known to under-map) are shown as "store not
   confirmed" rather than dropped.
7. **Detail pass:** fetch the full item record (`/items/{id}`) for the top-ranked items to get the retailer link and
   fine print. Fine print can only lower a deal's score, so reading stops once nothing unread can enter the top N.
8. **Promotions:** national restaurant promotions with dates in the window, kept when OSM has a branch in range.
9. **Rank** (§4.6) and return all deals, grouped as *deals* (firm price and saving), *promotions* (percent-off,
   BOGO, hedged) and *excluded* (counts by reason).

### 3.3 Data flow: Output 2 (biggest discounts online)

1. **Ingest** dealnews category feeds and Slickdeals frontpage, popular and per-industry keyword feeds (cached 30 min).
2. **Single products only:** drop storewide sales ("up to 70% off"), "from $X", gift cards, memberships, travel,
   expired and stale posts (> 72 h unless an explicit end date is still in the future). Those go to an *excluded*
   count, or to a "store events" list for the promotions view.
3. **Parse** price, reference price and its **basis** from the post: the store's own price before a code or coupon,
   "you'd pay $X elsewhere" (other stores), "list price" (MSRP), "best price Amazon has charged" (history).
4. **Industry:** feed category first (dealnews categories, Slickdeals keyword feed), then keyword rules.
5. **Identity:** extract brand, model number, GTIN, and variant attributes (size, capacity, pack count, condition).
6. **Cross-site prices:** for products with a brand and model, query the price sources in §2.3 with the model number,
   keep only listings whose identity matches exactly (same model, same size/capacity, new condition, not an accessory),
   and record each as a price observation.
7. **Verified discount** = `1 − price / median(other sites' current prices)` when 2+ other sites match; otherwise the
   post's own basis, at reduced weight.
8. **Dedupe** the same product posted on several feeds (same product key; keep the lowest price, merge sources).
9. **Rank** per industry by verified discount and return the top N with their comparison tables.

### 3.4 API

All endpoints are `GET` and return JSON. Inputs must come from the fixed lists; anything else is a `422` listing the
valid values.

| Endpoint | Purpose |
|---|---|
| `/api/v1/meta` | The fixed lists: cities (id, name, county, population, ZIP) and industries (id, name, description) |
| `/api/v1/local?city=austin&industries=tech,sports&radius_mi=25` | Output 1 |
| `/api/v1/online?industries=tech,fashion&limit=25` | Output 2 |
| `/api/v1/search?city=austin&industries=tech` | Both outputs in one response |
| `/api/v1/health` | Per-source status: last success, error rate, circuit state |

Response shape (abridged):

```jsonc
// /api/v1/local
{
  "city": {"id": "austin", "name": "Austin", "zip": "78701", "tz": "America/Chicago"},
  "window": {"start": "2026-10-04T16:00:00-05:00", "end": "2026-10-11T16:00:00-05:00"},
  "industries": ["tech"],
  "deals": [{
    "id": "flipp:1044517149", "kind": "item",
    "title": "Samsung - 48\" Class S85H OLED 4K UHD ... TV (2026)", "merchant": "Best Buy",
    "industries": ["tech"], "category": "Electronics > Video",
    "price": 999.99, "regular_price": 1199.99, "savings": 200.00, "discount_pct": 16.7,
    "basis": "store_regular", "terms": {"multi_buy": null, "bogo": false, "hedged": false, "conditions": []},
    "valid_from": "2026-09-29", "valid_to": "2026-10-05", "ends_in_days": 1,
    "store": {"name": "Best Buy", "address": "…", "distance_mi": 4.2, "source": "osm"},
    "links": {"source": "https://flipp.com/en-us/item/1044517149", "retailer": "https://www.bestbuy.com/product/…"},
    "score": 16.7
  }],
  "promotions": [ /* percent-off, BOGO, hedged and restaurant promotions */ ],
  "excluded": {"no_saving_stated": 812, "outside_window": 14, "no_store_in_radius": 3, "other_industry": 2290},
  "sources": [{"name": "Flipp", "ok": true, "fetched_at": "…"}]
}
```

```jsonc
// /api/v1/online
{
  "industries": ["tech"],
  "deals": [{
    "id": "dealnews:22243040", "title": "Bose SoundLink Max SE Portable Bluetooth Speaker",
    "product": {"brand": "Bose", "model": "SOUNDLINKMAXSE", "gtin": null},
    "seller": "Best Buy", "price": 229.00,
    "reference": {"price": 349.00, "basis": "store_regular", "text": "That's a $120 savings"},
    "comparisons": [{"site": "Amazon", "price": 299.00, "url": "…", "observed_at": "…", "match": "model"}],
    "market_median": 299.00, "verified_discount_pct": 23.4,
    "conditions": [], "posted_at": "…", "sources": [{"name": "dealnews", "url": "…"}], "score": 23.4
  }],
  "excluded": {"storewide_sale": 31, "stale": 12, "no_price": 4}
}
```

### 3.5 Web page

One static file (`backend/slomp/static/index.html`): no framework and no build step, with light and dark themes.

- **Inputs:** a searchable city picker over the fixed list (most populous matches first), a three-way distance
  control, and industry chips. The search lives in the URL, so results can be bookmarked.
- **Results:** two tabs, *Near you* and *Online*, each filtered by industry. Firm deals, promotions and
  store-unconfirmed deals share one list ordered by score, 24 at a time.
- **Cards** show only what a shopper scans for: picture, discount badge, store and distance, name, price, end date,
  and up to two conditions. Everything else (basis, dates, address, other stores' prices, links) is in a details
  dialog.
- **Pictures** come from the sources and are loaded by the browser, without a referrer. For weekly ads the only
  picture is the clipping from the ad itself. Ads built from a retailer's product feed put the product on top and
  the ad's own price text below, so cards crop to the product and the dialog shows the whole clipping. Deal feeds
  supply product photos. A deal with no picture gets its industry's icon.
- **Honesty in the UI:** struck-through prices appear only for a store's own regular price or a list price (which is
  labelled); a failed source shows a notice; "What Slomp left out, and why" lists every exclusion count.

### 3.6 Storage

| Store | Contents | Why |
|---|---|---|
| `backend/slomp/data/*.json` (in git) | Texas cities, merchant registry | Fixed inputs must be reproducible and reviewable; rebuilt by scripts |
| SQLite `http_cache` | Raw responses keyed by URL + params, with expiry | Politeness and speed; the verification harness can read exactly what the pipeline saw |
| SQLite `price_observations` | (product key, site, price, url, observed_at) | Cross-site comparisons and later price history |
| SQLite `verify_runs`, `verify_results` | Every test with its evidence | Iteration-over-iteration tracking |

SQLite is enough for one process; nothing here needs a server database yet.

---

## 4. Deep dive

### 4.1 Reference data

**Cities.** `scripts/build_texas_cities.py` downloads, caches and joins:
- 2026 Census Gazetteer, Texas places: 978 cities, 230 towns, 22 villages, 634 CDPs, each with an internal point;
- Vintage 2025 population estimates (incorporated places, with county parts) and ACS 2024 5-year totals (CDPs);
- 2026 ZCTA Gazetteer: the representative ZIP is the Texas ZCTA whose centroid is nearest the place's internal point.

It keeps every incorporated place and CDPs with 10,000+ people (The Woodlands, Spring, Atascocita, …). Ids are slugs
(`austin`; duplicates get the county, e.g. `reno-lamar-county`). One ZIP per city is a deliberate simplification:
Houston ZIPs share ~90% of their ads, and the rest are store-specific versions of the same chains.

**Industries (13).** Each maps from the Google Product Taxonomy that Flipp uses, from dealnews categories, and from
keyword rules. A deal can belong to more than one industry.

| id | Industry | Google taxonomy (L1, or L1 > L2) | dealnews |
|---|---|---|---|
| `tech` | Tech & Electronics | Electronics; Cameras & Optics; Software | Computers c39, Electronics c142, Video Games c191 |
| `sports` | Sports & Outdoors | Sporting Goods; Mature > Weapons | Sports & Fitness c211 |
| `fashion` | Fashion & Apparel | Apparel & Accessories; Luggage & Bags | Clothing & Accessories c202 |
| `home` | Home & Garden | Home & Garden (except Household Supplies); Furniture; Hardware | Home & Garden c196 and children |
| `beauty` | Beauty & Personal Care | Health & Beauty > Personal Care | Beauty c759 |
| `health` | Health & Wellness | Health & Beauty > Health Care; Business & Industrial > Medical | Health c765 |
| `grocery` | Grocery & Household | Food, Beverages & Tobacco; Home & Garden > Household Supplies | Food & Drink c213, Cleaning c637, Laundry c804 |
| `toys` | Toys, Games & Hobbies | Toys & Games; Arts & Entertainment > Hobbies & Creative Arts, Party & Celebration | Toys & Hobbies c226, Board Games c294, Crafts c311 |
| `baby` | Baby & Kids | Baby & Toddler; Furniture > Baby & Toddler Furniture | Babies & Kids c224, Kids' Clothes c205 |
| `pets` | Pets | Animals & Pet Supplies | Pets c221 |
| `auto` | Automotive | Vehicles & Parts | Automotive c238 |
| `office` | Office & School | Office Supplies; Business & Industrial (other) | Office & School c182 |
| `dining` | Restaurants & Dining | (local promotions only) | Restaurants c377 |

**Merchants.** `merchants.json` maps each Flipp merchant name to a canonical name, Wikidata brand id (for OSM and
AllThePlaces), web domains (to confirm that an outbound link really goes to that store), and a prior industry. Unknown
merchants still work: they fall back to exact-name OSM matching and are flagged for registry review.

### 4.2 Polite HTTP layer

One client wraps every network call:
- **Rate limits per host** (token bucket): Flipp 4/s, Overpass 1 concurrent, dealnews and Slickdeals 1/s, Amazon 0.5/s,
  other retailers 1/s.
- **Retries** on timeouts, 429 and 5xx: exponential backoff with jitter, max 3, honoring `Retry-After`.
- **Circuit breaker per host:** opens after 5 consecutive failures for 60 s, so one broken source cannot slow the rest
  (v0.2 had a single shared breaker; that bug is designed out).
- **Hard deadline per request** (20 s) so a stalled connection can't hang a run.
- **robots.txt** is fetched and honored for HTML pages; JSON endpoints that a site's own pages call are used only when
  robots.txt does not disallow them.
- **User-Agent:** `Mozilla/5.0 (compatible; Slomp/1.0)`, plus a contact from `SLOMP_CONTACT` if set.
- **Cache:** SQLite with TTLs per source (below). Errors are cached briefly (2 min) to avoid hammering a failing host.

### 4.3 Deal model and discount basis

Every deal states its **basis**, the reference its discount is measured against. Ranking weights encode how much each
basis can be trusted:

| Basis | Meaning | Example | Weight |
|---|---|---|---|
| `market` | Below the median current price at 2+ other sites that Slomp itself checked | Amazon $298, Best Buy $299 vs deal $229 | 1.0 |
| `store_regular` | Below the same store's own regular price | Best Buy "Was $1,199.99"; Flipp item with `original_price` | 0.9 |
| `editor_compare` | An editor's statement about other stores | dealnews "You'd pay $65 elsewhere" | 0.8 |
| `history` | A price-history claim | "the best price Amazon has charged" | 0.6 |
| `list` | List price, MSRP, compare-at | "off the $703 list price" | 0.5 |
| `none` | No reference given | ad price only | not ranked |

Hedged claims ("up to 50% off", "starting at") are kept as promotions at half weight. BOGO and multi-buy are
converted to the effective per-unit saving.

### 4.4 Industry classification

Order of evidence, strongest first: (1) the source's own taxonomy (Flipp `_L1/_L2`, dealnews category); (2) keyword
rules on title and brand; (3) the merchant's prior (Old Navy → fashion). Multi-label is allowed where it reflects
reality (Dick's running shoes are both fashion and sports). Each label records which rule produced it, so the
verification harness can attribute errors to a rule.

### 4.5 Product identity and cross-site matching

A product key is `brand + normalized model` (for example `sony|WH1000XM5`) or a GTIN. Two listings are the same
product only if:
- their GTINs match, or their brand and normalized model match exactly (XM5 ≠ XM4);
- size-like attributes agree (screen inches, storage GB/TB, ounces, pack count);
- neither is an accessory ("case for", "compatible with", "replacement") or a different condition (renewed, open-box,
  refurbished).

When those can't be established, the deal is shown **without** a comparison. A missing comparison is better than a
wrong one.

### 4.6 Ranking

`score = discount_pct × basis_weight × confidence`, tie-broken by dollars saved. Confidence starts at 1 and drops for
conditions the user may not meet (membership, loyalty card, code that may expire, "limit 1"). A diversity cap (default
5 per merchant in each industry's top list) keeps one retailer from filling the page. Output 1 returns everything,
ordered by score; Output 2 returns the top N per industry.

### 4.7 Caching

| Data | TTL | Reason |
|---|---|---|
| Flipp ad list for a ZIP | 6 h | New ads appear mid-week |
| Ad items, merchant search | until the ad ends, max 24 h | Items change rarely within an ad |
| Item detail | 24 h | |
| Store dataset | rebuilt weekly | Stores open and close slowly |
| Online feeds | 30 min | Deals move fast |
| Cross-site prices | 6 h | Prices move daily |
| robots.txt | 24 h | |
| Final results | 30 min; online results per industry, warmed at startup | Repeat views are instant, and every industry combination reuses the same per-industry work |

### 4.8 Error handling

Each connector returns results plus a status. A failed source becomes a `sources[].ok = false` entry with the error,
never a 500. Malformed records are dropped with a counted reason, never guessed at. The service never invents data:
if a field isn't in the source, it is absent from the output.

---

## 5. Verification

Unit tests (offline, recorded fixtures) cover parsing and rules. Accuracy against the real world needs **live**
tests, which `slomp verify` runs:

**Per iteration:** draw a seeded random sample of cities stratified by size (3 large ≥ 200k, 3 mid 20k–200k, 4 small
< 20k) and industries (every industry appears at least once), run Slomp like a user, then run **200 tests** that
re-check its output against the sources through **independent fetch paths** (a different endpoint, or the retailer's
own page), never the pipeline's cached copy:

| Group | Test | Count | Passes when |
|---|---|---|---|
| Local | Source fidelity | 30 | The item's own Flipp record (`/items/{id}`) has the same merchant, title, price, regular price/saving and dates |
| Local | Retailer page | 10 | The retailer's own product page shows the ad price, or the regular price Slomp states (added in iteration 4) |
| Local | Time window | 15 | The source dates overlap `[now, now+7d]` in the city's time zone, and the labels (ends/starts) are right |
| Local | Vicinity | 20 | The claimed store exists in the map source with that brand, and its recomputed distance ≤ radius |
| Local | Industry | 20 | A blind judge, given only title and merchant, assigns an industry that Slomp also assigned |
| Local | Terms and math | 10 | Savings and % recomputed from raw source fields match; BOGO/multi-buy/hedges handled |
| Local | Recall | 15 | A random qualifying item pulled directly from Flipp for that ZIP and industry is in Slomp's output, or excluded for a valid reason |
| Online | Source fidelity | 25 | The deal's own post page shows the same price and store, and is not marked expired |
| Online | Merchant link | 15 | The outbound link lands on the claimed store's domain; if the page exposes a price, it matches (allowing for stated codes/coupons) |
| Online | Comparisons | 20 | Each comparison listing, re-fetched, is the same product (model/GTIN) at the stated price (±2% or $1) |
| Online | Industry | 10 | Blind judge agrees |
| Online | Ranking and quality | 10 | Discount recomputes; order follows score; no duplicates; no storewide sales or stale posts in the product list |

Vicinity is checked against AllThePlaces (the chains' own store locators), which is independent of the OpenStreetMap
data Slomp uses. Each test records pass, fail or **inconclusive** (for example a site that is down). Inconclusive tests are replaced
from a reserve sample so each iteration reports 200 conclusive results where possible, and the inconclusive count is
reported too. The blind judge is a separate model run given only the deal's text, never Slomp's labels.

**Iteration loop (×10):** run → triage every failure as *Slomp bug*, *source error* or *test bug* → fix with a
regression unit test → next iteration on a fresh sample, plus a re-run of every earlier failure. Results go to
`docs/VERIFICATION.md`.

---

## 6. Scale and reliability

**Load today:** one user, ~1,300 cities × 13 industries of possible inputs. A cold city costs ~1 ad list + ~45 ad
item lists + ~45 merchant searches + ~30 item details + 1 Overpass query ≈ 120 requests (~30 s at Flipp's rate limit),
then nothing for 6–24 h. Online feeds are shared by every city: ~30 feed requests per 30 min.

**Statewide precompute (if needed):** Texas has ~1,300 places but far fewer distinct ad sets. Ads are keyed by ad id,
so items are fetched once per ad, not once per city: about 3,000 distinct ads and ~3,000 merchant searches per day
statewide, ~1 h at polite rates. That makes a nightly warm job feasible.

**Path to more users:** move result computation to a scheduled job that writes per-ZIP snapshots; serve reads from
Postgres or a key-value store; put the API behind a CDN; keep the per-host rate limits global (one worker pool), since
sources, not compute, are the bottleneck.

**Monitoring:** `/api/v1/health` exposes per-source success rate, latency and circuit state; the verification harness
doubles as a canary (run a small daily sample; alert if fidelity < 98% or a source returns zero items).

---

## 7. Trade-offs

| Decision | Chosen | Alternative | Why |
|---|---|---|---|
| Local deal source | Flipp weekly ads | Scrape each retailer's weekly ad | One keyless source covers ~70 Texas merchants with structure and a product taxonomy; per-retailer scraping is brittle and often blocked |
| Industry classification | Source taxonomy first, rules second | ML classifier | Flipp already labels items with Google's taxonomy; rules are auditable and testable; no training data yet |
| Store locations | OSM Texas extract, built weekly into a local dataset | Live Overpass per request; AllThePlaces | Public Overpass servers blocked or timed out; stores change slowly; ATP is uneven run to run, so it serves as the independent check instead |
| One ZIP per city | Nearest ZCTA to the city's internal point | Several ZIPs per large city | ~90% of ads are shared across a metro; several ZIPs would show near-duplicate store variants |
| Compute model | On demand + cache | Precompute all of Texas nightly | Testing phase; avoids ~3,000 daily requests we don't need yet |
| Cross-site matching | Exact identifiers only | Fuzzy title similarity | Wrong comparisons destroy trust; v0.2 found accessories and size variants posing as matches |
| Blocked retailers | Not used | Headless browsers or rotating proxies | Circumventing bot walls is off the table; coverage gaps are reported instead |
| Storage | SQLite | Postgres | Zero ops for one process |
| "Highest discount" | Verified against other sites when possible | Trust the post's "was" price | Inflated list prices are the most common fake discount |

## 8. What to revisit as it grows

- **Per-neighborhood ZIPs** for the big metros, once store-specific prices matter.
- **Price history** from `price_observations`, so "lowest in 30 days" can be computed rather than quoted.
- **Retailer partnerships or affiliate APIs** (Walmart, Target, eBay, Best Buy keys) to close the comparison gaps
  that bot walls create today.
- **Nightly precompute** when there is more than one user.
- **Other states:** rebuild the city list; time zones and taxonomy are already data.
- **Personalization:** saved cities and industries, alerts when a deal crosses a threshold.

## 9. Build plan

1. Reference data: city list, industries, merchant registry.
2. Polite HTTP layer and SQLite cache.
3. Connectors: Flipp, Overpass, feeds, price sources.
4. Domain modules: terms, identity, classification, ranking.
5. Pipelines, service, API, CLI, web page.
6. Offline unit tests.
7. Verification harness, then 10 iterations of 200 live tests, fixing what each finds.


## 10. Addendum: regular deals (Oct 5, 2026)

Standing offers that repeat on a schedule (BOGO Wednesdays, discount movie Tuesdays, kids eat free on Sundays) are not
in weekly ads and rarely in deal feeds, so v1 missed them. They are now a third list in Output 1, `regulars`, with
their own design document: [DESIGN-regular-deals.md](DESIGN-regular-deals.md). In short: two day-of-week roundup
pages are parsed automatically, a curated registry points at company pages and the words that must be on them, each
card names its evidence, and deals announced only on social media can be added by hand. The fourteenth industry,
Movies & Entertainment, is local-only like Restaurants & Dining. Two 200-test runs in the Austin, Houston and Dallas
areas and an audit of every regular deal are in [VERIFICATION.md](VERIFICATION.md#regular-deals).


## 11. Addendum: the published site (Oct 5, 2026)

Slomp also runs as a static site on GitHub Pages, so it opens with nothing to install:
[DESIGN-static-site.md](DESIGN-static-site.md). The pipelines are unchanged. A scheduled GitHub Actions job runs them
for the whole state (weekly ads for 303 anchor ZIPs: every city of 50,000+ people, and every Texas city within 20 mi
of one) and writes data files;
the page's `engine.js` does the per-search part (nearest store or branch, radius, the next 7 days in the city's own
time zone, duplicates, order) and returns the server's `/api/v1/search` shape. A parity check
(`python -m slomp.verify.site_check`) compares the two on the same data.
