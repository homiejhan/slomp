# The home page's biggest deals: design

**Request (Oct 7, 2026):** on the home page, show 9 of the biggest deals from franchises' regular deals, franchise
deals and online deals and discounts, taken from franchises in general and big online stores rather than Texas-local
places. Show 3 at a time, and turn to the next 3 every 8 seconds until the person does something with them; after 8
seconds without that, turn again and go back to turning on their own.

## What it shows

Before a search there is no city, so nothing near one can be shown. The home page (the welcome, under the search box)
shows **Biggest deals right now**: deals that are the same wherever you are in Texas.

| Kind | From | Counts when |
|---|---|---|
| Regular deal ("Every week") | the Regulars tab's statewide set | it's at a chain found all over Texas, and runs in the next 7 days |
| Promotion ("Limited time") | restaurant chains' offers in deal-site posts, as on the Near you tab | the same chain test, and its dates overlap the next 7 days |
| Online deal ("Online") | the Online tab's ranked deals, every online category | the seller is one of the 122 stores in `data/online_stores.json` |
| Online sale | the Sales tab's store-wide and category sales | the store is one of those 122, and the sale is live |

**A chain found all over Texas** is one with at least 5 mapped branches spread over an area at least 150 mi across,
corner to corner. Neither number works alone: the map has 9 of Main Event's branches, from El Paso to Houston, and 10
of Kerbey Lane Cafe's, all between Round Rock and San Antonio. Left out: a single place (a museum, a zoo, one
restaurant), one area's operator of a chain (Goodwill Central Texas), a chain in one part of the state (P. Terry's,
Austin to San Antonio; Star Cinema Grill, around Houston), and your own entries, which Slomp hasn't checked. A Texas-only chain with branches across the state (Taco Cabana, Whataburger) counts: the map
can't tell a national chain from a statewide one, and either is near most visitors.

## How big a deal is

The home page ranks every candidate by **the percent it saves, times how far that percent can be trusted**, so a
checked 40% beats an "up to 80%" or a discount from a list price nobody charges:

- **Size:** the percent on its badge, as "Best deal first" counts it. Something free is 100% off, or 50% when it takes
  a purchase ("kids eat free with an adult entrée", "free fries w/ any purchase"); a price with nothing to compare it
  to has no size and is left out.
- **Trust:** each tab's own weights. Online deals and sales use their tab's score as it is (what the discount is
  measured against; conditions; an "up to" counted at half its distance above what is certain). A regular deal is
  weighted by what its percent is measured against (a free item, against its own price), halved for a hedge ("up to",
  "select weeks"), and by how Slomp knows it (the company's own site 1.0, two deal lists 0.9, one 0.75, an article
  0.7). A promotion rests on one deal-site post, so it is weighted like a regular deal an article reports (0.7); its
  offer is read from the post's title the way regular deals' wording is (a percent, buy one get one, something free).

Free things rank high on purpose: that is how the page's own "Best deal first" counts them.

## Which nine

1. Each kind's candidates, best first, one per brand: the best 12 of each kind are kept.
2. Of those live at the moment, the nine biggest, one per brand (Amazon once, not as a deal and a sale), and at most
   3 of a kind while other kinds still have deals to fill the rest.
3. Biggest first, except that each group of three takes a kind it doesn't have yet when there is one, so every three
   on screen mix kinds.

"Live" is checked at the moment the page is opened, not when the deals were read: a sale's end, a deal's stated
expiry, a promotion's last day (or 3 days after it was posted, when it gives no dates), a regular deal's stated end
(or, for a monthly one, its one day this month).

## How it turns

- Three cards at a time. On a phone the three are rows, one above the other, and the page swipes.
- **Every 8 seconds** the next three slide in; after the last three, the first three again. The current dot fills
  over the 8 seconds.
- **Anything you do with them starts the 8 seconds again:** a swipe, a scroll of the mouse or trackpad, a click or tap
  (on a card, an arrow, a dot), a key, or the pointer moving over them. So they wait while you look, and 8 seconds after
  you stop they turn and carry on turning on their own. The pointer resting on them doesn't hold them: 8 seconds after
  it last moved, they turn.
- **They wait, with no 8 seconds counting,** while a deal's details (or any popup) are open, while the keyboard is on
  them (what's focused must not slide away), and while the tab is hidden; each starts the 8 seconds again when it ends.
- **Pause** stops them until **Play**: moving content needs a way to stop it (WCAG 2.2.2). On a phone the arrows are
  left out (the page swipes, and the dots still go to any three); Pause stays.
- With reduced motion asked for, the three change without sliding and the dot doesn't fill.
- Keyboard: Previous, Next and Pause, then the three cards shown, then the dots. The three not shown are out of reach
  of Tab and of screen readers until they are; what changes is announced only while they aren't turning on their own.
- Fewer than 3 deals: the section is left out. 3 to 8: as many groups as they fill.

## Tapping a deal

The same details as in its tab. A sale or an online deal can go on your card from there. A chain's regular deal or
promotion has no branch to name before a city is chosen, so its details say "Branches all over Texas" and offer
**Find one near you**: it adds the deal's categories to the search and, with a city chosen, searches and opens the tab
and day that show the deal at the nearest branch; with none, it puts the cursor in the city box.

## Where it comes from

- **`slomp serve`:** `GET /api/v1/top` picks the nine at the moment of the request (`slomp/top.py`). It waits for the
  regular deals, promotions and sales (the warm-up reads those first), but not for the online deals of categories not
  yet computed: those join on a later visit, computed in the background one category at a time, as the warm-up does.
- **The published site:** the build writes `data/top.json`, every kind's best 12 with the moments each can be shown
  between, and `engine.js` picks the nine in the browser at the moment the page is opened, with the same steps.
- **`slomp top`** prints the nine, in their groups of three, with each one's rank.

## Checked

- `tests/test_top.py` (14 tests): the chain test on real chains; sizes and ranks; the candidates from real registry
  entries at their real chains, with made-up posts, online deals and sales; the nine, one per brand, 3 per kind and
  mixed threes, and what one kind does when the others run out; liveness at several moments; the server using the
  online deals it has and computing the rest in the background; the API; the build's file; the command line; and
  `engine.js` picking the same nine as the server at six moments (Node).
- `python -m slomp.verify.site_check` now also compares the home page's nine, server against page, on a real build.
  The sources can't be reached from where this was written, so it hasn't been run against live data yet.
- In Chromium (Playwright), on a local copy of the published site built from the test deals, with stand-in pictures,
  and on `slomp serve` with the same deals: with the clock held, the first turn comes at 8 s, then every 8 s, wrapping
  after the last three; the pointer moving over them, a click on Next or Previous or a dot, a sideways scroll, each
  start the 8 seconds again, and they turn 8 s after the last; Pause holds them for 30 s and Play starts the 8
  seconds; an open details popup, the first-visit tour, the keyboard on them and a hidden tab each hold them, and they
  turn 8 s after; at real speed the turn slides smoothly. The three sit side by side at 1280 px and as rows at 390 px;
  light and dark; no sideways scroll of the page; each kind's details; an online deal onto the card; Find one near you
  with no city (the city box, with the category chosen) and then a search, which opens the Regulars tab on today with
  the deal; 2, 3 and 5 deals, and no file at all; no console errors. Found and fixed while checking: the screen-reader
  words of a check seal on the pages out of sight sat outside the carousel's clipping and widened the whole page.
