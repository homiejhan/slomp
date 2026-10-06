# Slomp on GitHub Pages: design

**Goal:** open the page and it works. No server, no install, no setup. Same page, same three tabs, same sources and
rules.

**Constraint:** GitHub Pages serves static files only. Nothing runs on request, so every network read happens ahead of
time, on a schedule, and the page does the per-search work itself.

## 1. What moves where

Slomp's server does two kinds of work. Reading the sources (weekly ads, deal feeds, evidence pages) is slow, rate
limited and the same for everyone. Answering one search (which stores are near this city, which deals run in the next
7 days from now) is fast arithmetic over what was read. The split follows that line.

```
GitHub Actions, every 6 hours                                   the browser, on each search
┌──────────────────────────────────────────────┐                ┌──────────────────────────────────────┐
│ slomp site build                             │                │ index.html + engine.js               │
│  weekly ads: every ad running near Texas     │   static JSON  │  city -> its ads -> nearest store    │
│    anchor ZIPs (section 2), items processed  │ ─────────────► │    -> radius -> 7-day window -> rank │
│  regular deals: the statewide confirmed set  │  GitHub Pages  │  regular deals: nearest branch,      │
│  restaurant promotions: the offers           │                │    dates in the next 7 days          │
│  online deals: ranked per industry           │                │  promotions: nearest branch, dates   │
│  store, branch and city coordinates          │                │  online: the chosen industries       │
└──────────────────────────────────────────────┘                └──────────────────────────────────────┘
```

| Part | Depends on the city? | Built on GitHub | Done in the browser |
|---|---|---|---|
| Online deals | No | The full ranked result per industry | Pick the chosen industries |
| Regular deals | Nearest branch, local dates | The statewide set with its evidence, schedule and branch locations | Nearest branch, radius, the dates it runs from now |
| Restaurant promotions | Nearest branch, local dates | The offers, their stated dates and chain locations | Nearest branch, radius, window |
| Weekly ads | Which ads (by ZIP), nearest store | Every ad live at any anchor ZIP, every item classified, termed and ranked | The city's ads, nearest store, radius, window, duplicates, order |

The page builds the same response the server's `/api/v1/search` returns, so the rest of the page is unchanged. The
server keeps working as before (`slomp serve`); the static engine is a second way to answer the same question.

## 2. Weekly ads: anchors

Flipp lists the ads running at one ZIP per request. Reading all 1,256 city ZIPs every run is 1,256 requests, most of
them returning the same ads, because ads cover regions. Measured on the 104 ZIPs cached from the verification runs
(pairs read within 6 hours of each other), the share of ads two ZIPs have in common falls slowly with distance:

| Distance | Ads in common | Merchants in common |
|---|---|---|
| 0–10 mi | 93% | 97% |
| 10–20 mi | 89% | 95% |
| 20–30 mi | 84% | 92% |
| 30–40 mi | 80% | 90% |

So the build reads a set of **anchor** ZIPs: every city of 50,000 people or more (79 of them, where most searches will
be; they read their own ZIP's ads, exactly as the server does), then the largest city not yet within 20 mi of an
anchor, until every Texas city is within 20 mi of one (303 anchors). A city uses its nearest anchor's ads; distances to
stores are measured from the city itself, never from the anchor. When the anchor isn't the city, the page says whose
ads it shows ("weekly ads as published for Georgetown, 10 mi away").

Ads are shared across anchors, so each ad is processed once. The expensive step per merchant, Flipp's item search (the
taxonomy labels and original prices), is skipped when every ad of that merchant at an anchor was already searched at
another: on the same 104 ZIPs that is 251 searches instead of 3,945. One search returns at most ~150 items, though, and
which ones depends on what else the merchant advertises at that ZIP (Family Dollar's weekly ad has 137 items; a search
returns 113 or 123 of them, by ZIP). An item without a search result often has no saving to show and is left out, by
the server too. So for a merchant whose items still lack results, the build searches again at other anchors that have
those items, up to 6 more times and until three searches in a row find none of them. About 20% of the items in Texas
ads still have no result (Walgreens' ads run to 420 items); the server, searching one ZIP, has the same gap.

**Fine print (the detail pass).** The server reads the full record of the 24 leading deals per industry for the
searched city. The build does the same for every anchor at each radius (10, 25 and 50 mi) and reads the union, with
the same three rounds as the server, so the deals a search shows first have had their fine print read. A deal further
down the list may not have been.

## 3. Files

```
index.html            the page (the server's page plus engine.js; a flag switches it to static mode)
engine.js             the per-search work (section 1), the same response shape as /api/v1/search
data/meta.json        cities (with coordinates, time zone and anchor), industries, radii, build time, source status
data/ads/index.json   every live ad: merchant, dates; each anchor's ads; per-merchant map flags
data/ads/<id>.json    one ad's deals, all industries (a search loads its anchor's, ~40 of these)
data/stores.json      every mapped store of the merchants that advertise
data/regulars.json    the statewide regular deals, their evidence, schedules and branch locations
data/promos.json      restaurant promotions and the branch locations of their chains
data/online/<id>.json the ranked online deals for one industry
```

One file per ad, not per anchor: neighbouring anchors share most ads, so per-anchor files would repeat them, and the
browser keeps the ones it has loaded for the next search nearby. GitHub Pages compresses JSON on the way out.

## 4. Time

The page computes in the city's own time zone (El Paso and Hudspeth counties are on Mountain time) with the browser's
time-zone database, from the moment the page is used, not the moment the data was built. A deal that ended an hour ago
is gone even if the data is five hours old, and a deal starting in the next 7 days shows even if it started after the
build. To make that possible the build reads one day further ahead than the server (8 days).

## 5. Schedule, cost and politeness

- The workflow runs every 6 hours (00:23, 06:23, 12:23 and 18:23 Central daylight time) and can be started by hand.
- The response cache (SQLite, the same cache and lifetimes as the server) is carried between runs with GitHub's
  Actions cache, so an ad's items are read once a day, an item's full record once, and an evidence page once a day.
  Entries past their lifetime are kept a few days so a source that is briefly down falls back to its last good answer,
  as the server does.
- Per run: 303 ad lists from Flipp plus what changed (new ads, their searches and items), the deal feeds, the evidence
  pages due for a check, and the online price checks. Rate limits, robots.txt, the User-Agent and bot-wall handling are
  the server's, unchanged.
- A run an AI assistant starts sets `SLOMP_ASSISTANT=1`, which skips every site whose robots.txt turns AI assistants
  away by name (Amazon among Slomp's sources). Scheduled runs are Slomp's own and follow the general rules, as `slomp
  serve` does.

## 6. Trade-offs and limits

| Decision | Gained | Given up |
|---|---|---|
| Static files, built on a schedule | No server, instant to open, free | Data up to ~6 hours old; a deal posted an hour ago may be missing |
| Anchors instead of every ZIP | 303 requests per run instead of 1,256 | A city 10–20 mi from its anchor shares ~89% of its ads; a local grocer's own ad version can be missing |
| One file per ad | Each ad stored once; nearby searches reuse loaded files | A search loads ~50 small files instead of one |
| The page computes dates and distances | Correct for the moment and the city | A second implementation of that logic (in JavaScript) that must match the server's; section 7 tests it |

- **Public.** The site republishes what the sources publish (deal titles, prices, ad pictures loaded from Flipp, short
  quotes from evidence pages), always with a link to the source.
- **Your own regular deals** (`~/.config/slomp/regulars.json`) stay on your computer: they appear in `slomp serve`, not
  on the public site.
- **GitHub pauses a schedule after 60 days without repository activity.** Any push resets it, and the workflow can be
  re-enabled from the Actions tab or with `gh workflow enable`. The page shows when its data was built and warns when
  it is more than a day old. (Workarounds that fake activity exist; the best known one was taken down by GitHub for
  breaking its terms, so Slomp doesn't use one.)

## 7. Verification

1. **Parity.** Build the site, then answer the same searches with the server from the same cache at the same moment.
   For anchor cities the weekly ads, regular deals, promotions and online deals must match: the same deals, stores,
   distances, dates, terms and order. For other cities, regular deals, promotions and online deals must match, and
   weekly ads differ only by the anchor's ads.
2. **The anchor approximation.** For cities that aren't anchors, compare their own ZIP's ads (live, as the server
   reads them) with the anchor's: how many of the server's deals the page also shows.
3. **The published page.** Open the deployed site at desktop and phone widths: searches in several regions, every
   tab, sorting, details, no console errors.

## 8. What was built

| Piece | Where |
|---|---|
| The build: anchors, weekly ads, regular deals, promotions, online deals, the data files | `backend/slomp/site.py` (`slomp site build`) |
| The per-search engine, the same response as `/api/v1/search` | `backend/slomp/static/engine.js` |
| The page in both modes: it uses the engine when `engine.js` is loaded, the server otherwise | `backend/slomp/static/index.html` |
| The schedule and the deployment | `.github/workflows/pages.yml` |
| The parity check (section 7) | `backend/slomp/verify/site_check.py` |
| Skipping sites that turn AI assistants away, for runs an assistant starts | `SLOMP_ASSISTANT=1` (`config.py`, `http.py`) |

Built on Oct 5, 2026, around 7:45 PM Central: 303 anchors, 364 live ads, 43,716 items, 8,616 deals (114 ads from
retailers' product feeds), 401 merchant searches (about 12,000 had each anchor been searched like a city), the fine
print of 3,066 leading deals, 217 regular deals, 27 restaurant promotions and the online deals of 12 industries: 383
files, 7.8 MB (a first search downloads 0.6–0.8 MB compressed; the next ones nearby reuse most of it). From an empty cache the build takes about
12 minutes, almost all of it Flipp's rate limit; with the cache from the previous run, about a minute. The parity check
is in [VERIFICATION.md](VERIFICATION.md#the-published-site).
