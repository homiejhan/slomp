# Plum: find the plum deal near you

Plum answers two questions:

- **What's on sale near me this week?** `plum deals "Austin, TX"` reads the weekly ads retailers publish for a city's
  ZIP code, keeps only what's running now, works out what each ad actually promises, and ranks the real savings. Each
  deal comes with its fine print, the nearest store, and links to the ad and the retailer's own page.
- **Where is this exact item cheapest?** `plum search "chicken breast" --near 78701` compares one item across
  nearby stores' ads by unit price. The original product engine (matching, coupon scoring, landed cost) is still
  here too, and `plum demo` runs it on simulated stores.

## Quick start

```bash
cd backend
pip install -e '.[live]'                      # '.[dev,api]' adds the tests and the HTTP API
plum deals "Austin, TX"                       # best deals + other offers, 25-mile radius
plum deals 78704 --category Groceries --limit 10
plum deals "Austin, TX" --store "H-E-B" --store Randalls --confirmed-only
plum search "chicken breast" --near "Austin, TX"
plum deals "Austin, TX" --json > deals.json
plum demo "sony xm5"                          # the product engine on simulated stores, offline
uvicorn plum.api:app --reload                 # web page at http://localhost:8000, API docs at /docs
pytest                                        # 95 tests, all offline
```

The first run for a city takes about a minute (≈45 ads, ≈110 full ad records, two map queries). Responses are cached
under `~/.cache/plum` (`PLUM_CACHE_DIR` to move it, `--no-cache` to bypass): ads for an hour, stores for a week,
places for a month. Set `PLUM_CONTACT` to an email or URL to include it in the User-Agent, as Nominatim's usage
policy asks.

## Where the data comes from, and how far to trust it

| Source | Used for | Checked in Austin, Sept 24 2026 |
|---|---|---|
| Flipp weekly ads (`backflipp.wishabi.com`) | The ads retailers publish for a ZIP: 44 running in 78701, 4,823 items | **Retailer-feed items** (linked to the retailer's product page): 12 of 15 matched the retailer's live site exactly. The other 3 had changed price or sold out *after* the ad ran. **Ad-transcribed items**: 23 of 27 matched the printed ad image. The 4 misses led to the accuracy rules below; 3 are now caught. |
| OpenStreetMap: Overpass API | Is there really a store nearby, and where | Found a store in range for 34 of 37 merchants. Addresses spot-checked correct (Dick's #347 at 3210 Kramer Ln, Target at 901 E 5th St). Misses some regional chains. |
| OpenStreetMap: Nominatim | City or ZIP → coordinates → the ZIP the ads are published for | "Austin, TX" → 78701 |

All three are public and need no API key. Flipp's endpoints are the ones flipp.com's own web app calls; they're
undocumented, so every field is read defensively, and Plum spaces its requests and caches them. Retailers publish the
ads, and Flipp notes that prices can change after posting. **The ad is the source of truth, not the store's current
price**, which is why every deal links to both.

## How local deals work

1. **Place.** Geocode the city (preferring the city over, say, Austin County), then reverse-geocode its center to get
   a ZIP. A ZIP can also be passed directly.
2. **Ads.** Fetch every ad for the ZIP. Items carry their own dates (one Fiesta Mart item ran for a single day inside
   a week-long ad), so validity is checked per item. Ads that start later are listed under "Starting soon".
3. **Items.** Read each ad's item index. Page furniture, placeholder codes (`BESBU093025990119`), expired or
   not-yet-started items, and the same item repeated across overlapping ads are dropped and counted. An item with a
   price but no stated saving is a weekly-ad price, not a deal.
4. **Rank, then read.** Rank by the index's headline saving, then read the full ad record (all the ad text plus the
   retailer link) for the leaders only. Full terms can only *lower* a score (a BOGO's 50% headline is a 25% saving),
   so reading stops once nothing unread can make the top N. A merchant already holding its 3 slots isn't read
   further. Austin needs about 110 of 4,823 records.
5. **Terms** ([terms.py](backend/plum/terms.py)). Multi-buys keep their quantity ("2 for $8", $4 ea). BOGOs are
   counted at their effective saving. "Up to", "starting at" and compare-at claims are marked as hedges. Conditions
   are pulled out of the ad and its fine print: loyalty card, coupon, online price, members only, buy N+,
   "limit 10 lb", full case only, membership at warehouse clubs.
6. **Two lists.** *Best deals* have a firm price and a saving against the store's own regular price. *Other offers*
   cover percent-off promos, BOGOs, and hedged savings, which are ranked at half weight so that a promised 30% beats
   an "up to 50%".
7. **Stores.** Attach the nearest mapped store (with address when mapped). A merchant with none in range is flagged
   rather than dropped, because maps miss some chains; `--confirmed-only` drops them instead.

## Accuracy rules, each from a real Austin ad that was wrong without it

| What the data said | What the printed ad said | Rule |
|---|---|---|
| CVS So De La Renta: $24.99, "You save 76.00" (so Plum printed "reg. $101, 75% off") | "Depart. store value 101.00": a compare-at price, not CVS's own | For ads transcribed from print (no retailer feed), a saving counts as firm only if the data states the store's own regular price ("Was $4.79", "PRICE DROPS"). Otherwise it's shown as "saves $76.00 (the ad gives no regular price)" |
| Restaurant Depot avocado pulp: $2.80, original $12.35, 77% off | "$28.20 cs only, $2.35 lb": no discount at all | Numbers that no ad text backs up are dropped. "cs only" is a rule ("full case only"), not a per-case unit |
| Restaurant Depot blender: price $50, 50% off | "$50 OFF" | A dollars-off amount recorded as the price is treated as a saving with no price ("200 OFF/CS" = $2.00 off) |
| Gyro kones $4.62/lb, "original" $184.95, 98% off | the 40 lb case at $4.62/lb | A "regular price" equal to pack weight × the per-lb price is not a discount |
| CVS Osteo Bi-Flex 50% off | "Buy 1 get 1 50% off" | BOGOs are counted at their effective saving: 25% |
| CVS "2/$8.00 or reg retail ea." | two for $8 | Keep the quantity: "2 for $8.00 ($4.00 ea)", needs: buy 2 |
| Randalls chicken $1.79/lb | "Limit 10 lbs. Each" | Read the fine-print field too |
| "You save 76.00" (Flipp computed 76.01) | 76.00 | The ad's own printed figure wins over a computed one |
| Costco items | membership warehouse | Costco / Sam's Club / BJ's: "membership"; Restaurant Depot: "business membership" |

## Known limitations

- **Ads go stale within the week.** Old Navy's two $20 hoodies (Was $44.99, valid through Sep 27) showed $35.99
  online on Sep 24, although its $8 striped tee still matched. Best Buy's $8.49 Ken doll had sold out. There's no
  keyless live-price or inventory source, so check the store page before you go.
- **The source can drop fine print.** Restaurant Depot's "5% off *when you buy 48+ cs*" arrives as "5% OFF", and a
  CVS ad whose data says only "You save" can still be a compare-at claim (now shown as "no regular price given").
- **Maps are incomplete.** La Michoacana Meat Market has at least 4 Austin stores that aren't in OpenStreetMap, so its
  deals are flagged "no store mapped". Belk's flag is correct: its nearest mapped store is 76 mi away.
- **Coverage is what Flipp carries.** H-E-B's Flipp ad had 32 items, far fewer than its full weekly ad.
- **Search is word-based.** "eggs" also finds "Egg Spaetzle". Model numbers are checked (XM6 is not XM5), and
  accessories are dropped ("case for AirPods").
- US only. The Flipp endpoints are unofficial and may change or be rate-limited; use Plum for personal research, and
  respect each source's terms.

## The product engine

The v0.1 engine (identifiers → text features → matching → coupons + pricing → ranking) still runs through
[service.py](backend/plum/service.py) and the `/search`, `/probe`, `/coupons`, `/deals` endpoints:

- **Matching**: shared valid GTIN → exact. Shared model code +0.45, near-miss code (XM4 vs XM5) −0.35. Word overlap,
  accessory and size-clash penalties, and brand checks. Rejections are explained ("different model (wh1000xm4)").
- **Coupons**: reliability = Wilson lower bound of the success rate × a 14-day-half-life recency factor. A code only
  counts toward the price once it has worked ≥50% of the time recently.
- **Pricing and ranking**: sticker − code + shipping − cash back. Offers are sorted by what you pay, and commission
  is never a sort key.

Its demo data ([demo_data.py](backend/plum/demo_data.py)) is **simulated**: invented prices, codes and votes. The HTTP
adapters for eBay, Walmart, Best Buy and Amazon need API keys (`EBAY_API_KEY`, …) and haven't been verified against
the live APIs. The `frontend/PlumApp.jsx` that the previous README described isn't in this repository.

Bugs fixed in 0.2, each with a regression test in [test_engine_fixes.py](backend/tests/test_engine_fixes.py):

- One circuit breaker was shared by every adapter, so after one store failed three times every store reported
  "circuit open" for 30 s.
- "Lowest in 90 days" was claimed on the very first search (5 of 6 offers). Prices were recorded on every search
  and compared with themselves; now each fetch is recorded once and compared only with earlier ones.
- A global feature cache keyed by product id returned another product's features, so a perfect AirPods match was
  rejected.
- A probe mutated the module-level demo coupons, so stats drifted between services and tests.
- A store without a shipping policy crashed the whole search; it's now skipped with a reason.
- eBay received 11-digit GTINs (`lstrip("0")` on UPC 027242923508). Best Buy queries weren't URL-encoded.
- Smaller fixes: the TTL cache treated a TTL of 0 as the default and couldn't cache `None`; the cart-total parser read
  "$12.34 (2 items)" as 12.342; `RECENCY_HALF_LIFE_DAYS` wasn't a half-life.

## Layout

```
backend/plum/
  cli.py                 plum deals | search | demo
  local.py               LocalDealService: place → ads → items → rank → read → stores → report
  terms.py               deal terms from ad text: multi-buy, BOGO, units, hedges, conditions, sanity rules
  geo.py                 Nominatim geocoding, distances
  net.py                 polite HTTP: User-Agent, per-host spacing, retries, disk cache
  render.py              text and JSON views
  adapters/flipp.py      Flipp weekly-ad client and item parsers
  adapters/osm.py        Overpass store locator with strict merchant matching
  models.py              dataclasses for both halves
  service.py, matching.py, coupons.py, pricing.py, ranking.py, identifiers.py, textfeatures.py, cache.py
  adapters/base.py, retailers.py, affiliate_feed.py, checkout_probe.py
  api.py                 FastAPI app: the web page at /, /local/deals, /local/search, and the product engine
  static/index.html      the web page: a city or ZIP box, and the deals as cards
  demo_data.py           simulated catalog for the product engine
backend/tests/           95 tests; fakeweb.py stands in for Flipp, Nominatim and Overpass
```
