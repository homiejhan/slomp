# Plum — find the plum deal

One question, one answer: *where is this exact item cheapest after codes, shipping and cash back?*

Plum is two halves that share one engine design:

| | |
|---|---|
| `frontend/PlumApp.jsx` | Single-file React app. Bubbly UI + the full engine in JavaScript, with simulated store adapters so it runs anywhere (including as a Claude artifact). Set `window.PLUM_API` and it renders reports from the backend instead. |
| `backend/` | Python 3.11 package: identifiers → text features → matching → coupons + pricing → ranking, plus adapters, cache, a checkout probe interface and a FastAPI service. 32 tests. |

## How the engine works

**1. Resolve the product.** Barcode first (GTIN-8/12/13/14 check-digit validated, canonicalised to GTIN-14 so UPC-A and EAN-13 compare equal), then token/prefix/model-code search over titles and aliases.

**2. Fan out to stores.** Every adapter runs at once under a time budget (1.4 s). Slow stores show as *slow · retry*; a broken store never sinks the request. Per-store token buckets and a circuit breaker keep partners happy; a single-flight TTL cache coalesces identical queries.

**3. Match listings to the product** (`matching.py` / `match()` in the JSX). Evidence, strongest first:
- shared valid GTIN → *exact*
- shared model code (`WH-1000XM5`, `10281`, `Pegasus 41` as a bigram) → +0.45; a near-miss code (`XM4` vs `XM5`, `V11` vs `V15`, `9-in-1` vs `7-in-1`) → −0.35, applied even when another code is shared
- word overlap (Jaccard on compacted tokens) × 0.5, or × 0.95 when the product has no model number at all (AirPods)
- accessory/bundle words (`case`, `bundle`, `cover`…) −0.6, size clashes (`30 oz` vs `40 oz`) −0.5, brand mismatch caps the score at 0.3, a different UPC is −0.4 unless everything else says "colour variant"

Tiers: exact ≥ confident (0.75) ≥ likely (0.55) ≥ rejected. Rejections are shown to the user with the reason ("looks like an accessory", "different model (wh1000xm4)").

**4. Score the codes** (`coupons.py`). Reliability = Wilson lower bound of the success rate (3/3 is not treated like 300/300) × a 14-day recency decay; expired codes are 0. Applicability checks scope, category, brand exclusions, minimum cart and condition. A code only counts toward the displayed price when it has worked ≥50% recently — until you test it.

**5. Price the cart** (`pricing.py`). `sticker − code − (free-shipping code) + shipping − cash back`. "You pay today" is the big number; net after cash back is the sort key.

**6. Rank** by what the shopper actually pays, then match confidence, then store trust. Commission is never a key. Community deals rank by `votes / (hours + 2)^1.2 × (1 + depth)`.

**7. Verify.** "Test codes on this cart" runs the probe (simulated here; a Playwright recipe interface is provided) and every pass/fail feeds back into the same success-rate ledger the crowd signal uses.

## Run it

**Frontend** — drop `frontend/PlumApp.jsx` into any React project (or open it as a Claude artifact). It needs nothing else. To drive it from the service:

```js
window.PLUM_API = "http://localhost:8000";   // before the module loads
```

**Backend**

```bash
cd backend
pip install -e '.[dev,api]'
pytest                                   # 32 tests: identifiers, matching, coupons, pricing, service, API, data parity
python demo.py "sony xm5"                # ranked receipt, skipped listings, probe, verified re-run
uvicorn plum.api:app --reload            # GET /search?q=  GET /deals  POST /probe/{listing}?product_id=  GET /coupons/{store}
```

Real adapters (`plum/adapters/retailers.py`) ship with request shapes and response parsers for the eBay Browse API (`gtin` filter), Walmart Affiliate API, Best Buy Products API (`upc=` query) and Amazon PA-API 5; add keys via `EBAY_API_KEY` etc. The demo wires `FixtureAdapter`s instead. Affiliate coupon feeds (FMTC/CJ/Impact-style rows) normalise through `adapters/affiliate_feed.py`.

## Layout

```
frontend/PlumApp.jsx        UI + JS engine + simulated adapters (+ optional remote mode)
backend/plum/
  models.py                 dataclasses: Product, Listing, Coupon, Quote, DealPost, …
  identifiers.py            GTIN check digits, canonical form, extraction from text
  textfeatures.py           tokens, model codes, sizes, near-code detection
  matching.py               match() + ProductIndex (inverted-index blocking, barcode/text find)
  coupons.py                Wilson reliability, applicability, ranking, outcome ledger, feed dedupe
  pricing.py                landed-cost quote
  ranking.py                offer ordering, deal heat, period lows
  cache.py                  TTL + single-flight
  adapters/base.py          Adapter ABC, TokenBucket, CircuitBreaker, run_adapters fan-out
  adapters/retailers.py     Fixture, eBay, Walmart, Best Buy, Amazon adapters
  adapters/affiliate_feed.py
  adapters/checkout_probe.py SimulatedProbe + PlaywrightProbe/CheckoutRecipe
  service.py                DealService: find → fetch → assemble → rank; test_codes
  api.py                    FastAPI app (CORS on)
  demo_data.py              the same catalog/listings/codes/deals the frontend uses
backend/tests/              pytest suite
```

Demo data is simulated (stores, prices, codes, votes). The engine is not.
