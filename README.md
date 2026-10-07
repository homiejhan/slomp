# Slomp

Pick a **Texas city** and one or more **industries**. Slomp returns:

1. **Near you, next 7 days:** every deal, discount or promotion at stores near that city, valid at some point in
   the next 7 days. It reads the weekly ads retailers publish for the city's ZIP code, plus restaurant-chain
   promotions that a nearby branch honors, plus **regular deals**: standing offers that repeat on a schedule, such
   as BOGO Wednesdays or discount movie Tuesdays.
2. **Biggest discounts online:** the products in each industry with the highest discounts right now. Where other
   stores sell the exact same product, the discount is measured against their prices rather than a list price.
3. **Online stores' sales:** store-wide and category sales, promo codes and sale events at online stores that ship
   anywhere in Texas (122 stores by name, from Amazon, eBay and Walmart to Kohl's and Best Buy), and the stores
   themselves, each with what it has on. These are the same for every city.

Everything comes from public, keyless sources. [docs/DESIGN.md](docs/DESIGN.md) covers the design and the research
behind it, [docs/DESIGN-regular-deals.md](docs/DESIGN-regular-deals.md) does the same for regular deals, and
[docs/DESIGN-online-stores.md](docs/DESIGN-online-stores.md) for online stores' sales.
[docs/VERIFICATION.md](docs/VERIFICATION.md) has the results of the live accuracy tests.

## Open it

**[homiejhan.github.io/slomp](https://homiejhan.github.io/slomp/)**: nothing to install or start. A scheduled job
reads the sources every 6 hours and the page does each search in your browser (see [The published
site](#the-published-site) below). To run Slomp on your own computer instead, with every source read at the moment
you search, follow the next section.

## Run it

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate   # keeps Slomp's packages out of your base Python
pip install -e '.[dev]'
slomp cities "san an"                          # find a city id (1,256 Texas places)
slomp local austin -i tech,fashion             # deals near Austin in the next 7 days
slomp local alpine -i grocery,dining -r 50     # small towns: widen the radius
slomp local austin -i dining,entertainment     # restaurant promotions and regular deals, by the day they next run
slomp regulars                                 # every regular deal Slomp knows, with the state of its evidence
slomp online -i tech,home -n 10                # biggest verified online discounts
slomp sales -i fashion,home -n 20              # sales at online stores (the Sales and Stores tabs)
slomp top                                      # the home page's 9 biggest deals, the same anywhere in Texas
slomp serve                                    # web page at http://localhost:8000, API docs at /docs
pytest                                        # offline unit tests
slomp verify --iteration 1                     # 200 live accuracy tests (about 30 minutes)
slomp verify --iteration 1 --plan regulars     # 200 live tests of regular deals (Austin, Houston, Dallas areas)
slomp verify --iteration 1 --plan sales        # 200 live tests of online stores' sales
python -m slomp.verify.regulars_run --audit    # every regular deal near those cities, not a sample
slomp site build --out ../site                 # the published site's files (see below)
python -m slomp.verify.site_check --out ../site  # the site's page against the server on 60 searches (needs Node)
```

## The web page

`slomp serve` opens a single page: search a city, tap a distance and what you're shopping for, and browse cards under
five tabs, **Near you**, **Regulars**, **Online**, **Sales** and **Stores**. Click a card for the details: what the discount is measured
against, dates, the nearest store, conditions, other stores' prices, and links to the ad or deal post. Searches are
kept in the address bar, so a results page can be bookmarked or shared. Pictures are the ad clippings and deal-post
photos, loaded from their sources.

Each tab has a **Sort** menu: best deal first (the biggest discount on the card's badge; something free counts as 100%
off, or 50% when it takes a purchase), ending soonest, or the company's name A–Z or Z–A. The page remembers the
choice.

**Before you search,** the home page shows **Biggest deals right now**: nine of the biggest deals that need no city,
at chains with branches all over Texas (their regular deals and promotions) and at the big online stores (their deals
and sales). Three show at a time and the next three slide in every 8 seconds. Anything you do with them (a swipe, a
click, a key, the pointer moving over them) starts the 8 seconds again, so they wait while you look and carry on 8
seconds after you stop; they also wait while a deal's details are open, and **Pause** stops them until **Play**. Tap
one for its details; a chain's deal has **Find one near you**, which searches your city and opens the deal at the
nearest branch. [docs/DESIGN-top-deals.md](docs/DESIGN-top-deals.md) has which deals count and how they're ranked.

**New here?** The **Tour** button at the top walks through the page in six short steps. It opens by itself on a first
visit.

**Your card.** Tap **+** on any deal, or **Add to card** in its details, to put it on your card (up to 12). **Your
card**, at the bottom right, shows them as one picture, with each deal's photo, price, place and dates, to **Share**
(your phone's or computer's share menu) or **Save** as a PNG or JPG. The card is kept in your browser, nowhere else,
and empties at midnight. [docs/DESIGN-share-card.md](docs/DESIGN-share-card.md) has the design.

## Online stores and their sales

Online stores ship anywhere, so they belong to no city. Two tabs cover them, the same for every search:

- **Sales**: one card per store-wide sale, category sale, promo code or sale event at an online store that ships,
  in the categories you chose. Each shows the store's logo, the offer ("Up to 60% off + extra 25% off"), the promo
  code when there is one (the details view has a **Copy** button), when it ends, and its conditions (Prime or rewards
  members, minimum order, select items, in the app). Every card links to the post it came from.
- **Stores**: the online stores with something on in your categories, as logo tiles. Open one to see its sales and
  its product deals from the Online tab, with a link to its site.

Where sales come from: dated posts by deal-site editors (dealnews, including each major store's own dealnews feed,
Hip2Save, Slickdeals and 9to5Toys). Coupon-code sites are not used: their codes carry no dates. A promo code is shown
only when the post states it, and only if its own sentence makes it this sale's code (not a cardholder's, another
store's, or one whose day has passed). A sale is shown until its end (dealnews' own end date, or the post's words:
"ends October 8", "through 10/13", "today only"); a sale with no end is shown for 7 days after it was posted, and
nothing posted more than 30 days ago is shown, which keeps out the old "sitewide promo code" posts deal sites leave in
their feeds. "Best deal first" counts an "up to" percentage at half its distance above what is certain, since it is a
ceiling on a few items. The stores Slomp knows by name are in
[backend/slomp/data/online_stores.json](backend/slomp/data/online_stores.json); their logos come from each store's own
site or its Wikidata entry (`python scripts/build_logos.py --stores`).

## Regular deals

The **Regulars** tab shows the deals that repeat every week, one button per day of the coming week. Each card shows
the company's logo, when the deal runs (and until when, if it ends), where the nearest branch is, and how Slomp knows:

| Label | Meaning |
|---|---|
| ✓ Company site | Slomp read the company's own page in the last 7 days and found the offer's words on it |
| Listed by 1 or 2 sites | The Krazy Coupon Lady's or EatDrinkDeals' day-of-week list carries it, and the list was updated in the last 45 days |
| Reported | A dated article states it, and the article is under 180 days old |
| Added by you | It is in your own file (below); Slomp has not checked it |

A deal stops showing when its evidence goes stale, its page stops saying it, or its stated end date passes. A free
day that needs a reserved ticket is left out for a date its own page marks sold out.
`slomp regulars` prints every entry with the state of its evidence. The curated entries live in
[backend/slomp/data/regulars.json](backend/slomp/data/regulars.json): each names the page that states the deal and the
words that must be found there.

**Your own regular deals.** Slomp can't read Instagram, Facebook, X or TikTok (they all forbid automated readers), so
a deal announced only there is missing until you add it. Put entries in `~/.config/slomp/regulars.json` (or the file
named by `SLOMP_REGULARS`), in the format of [docs/regulars.example.json](docs/regulars.example.json):

```json
[{"brand": "DOKA Bubble Tea", "offer": "BOGO Wednesday: buy one, get one free on select drinks", "days": ["wed"],
  "kind": "cafe", "bogo": "buy 1 get 1 free", "conditions": ["select drinks"],
  "places": [{"name": "DOKA Bubble Tea", "address": "2815 Guadalupe St Ste A, Austin, TX 78705"}],
  "link": "https://www.facebook.com/p/Doka-Bubble-Tea-100070021503436/", "note": "Announced on their Facebook page."}]
```

`days` takes weekdays (`"mon"` to `"sun"`), `"daily"`, `"weekdays"`, or a monthly rule (`"first tue"`, `"7th"`).
`time` is optional (`"after 5 pm"`, `"3-6 pm"`). Give `places` with a street address for a single shop (Slomp looks up
its coordinates), or leave it out for a chain the map knows. `link` and `note` are shown to you; Slomp never fetches
the link. `site`, the place's own website, lets `scripts/build_logos.py` find its logo.

The first search for a city reads about 150 source pages (about 10–60 seconds). Results are cached in
`~/.cache/slomp` (`SLOMP_CACHE_DIR` moves it). Set `SLOMP_CONTACT` to a URL or email to add it to the User-Agent.

## The published site

[.github/workflows/pages.yml](.github/workflows/pages.yml) runs `slomp site build` every 6 hours and publishes the
result on GitHub Pages. The build reads every source once for the whole state and writes data files; the page's
`engine.js` then answers any search itself, in the same shape as the server's API, so the page looks and works the
same in both places. [docs/DESIGN-static-site.md](docs/DESIGN-static-site.md) has the design. How it differs from
`slomp serve`:

- **Data age.** Up to about 6 hours old. Dates still count from the moment you search, so a deal that ended an hour
  ago is gone. The page says when its data was read, and warns when that was more than a day ago.
- **Weekly ads by area.** Flipp lists ads by ZIP code. The build reads the ads for 303 anchor cities: every city of
  50,000 people or more, plus enough others that every Texas city is within 20 mi of one. A smaller city shows its
  nearest anchor's ads, with distances measured from the city itself, and the page names that anchor.
- **Your own regular deals** (`~/.config/slomp/regulars.json`) stay on your computer and only show in `slomp serve`.
- **Some company sites turn away GitHub's servers** with a bot check (Cinemark, Uchi, Goodwill Central Texas and about
  ten more on Oct 5, 2026). The regular deals only their pages confirm, about 18, are missing from the published
  site; `slomp serve` shows them. The workflow's log lists the pages it couldn't read.

To refresh it now: the repository's **Actions** tab, **Publish the site**, **Run workflow**. Or:

```bash
gh workflow run pages.yml
```

GitHub pauses a public repository's scheduled workflows after 60 days without activity (a push counts). If the page
warns that its deals are old, turn the workflow back on from the Actions tab, or:

```bash
gh workflow enable pages.yml
```

To build and look at the site on your computer:

```bash
cd backend && slomp site build --out ../site      # about 15 minutes the first time, a minute after that
python3 -m http.server 8020 --directory ../site   # then open http://localhost:8020
```

## Rebuilding the reference data

```bash
python scripts/build_texas_cities.py                                         # Census 2026 / PEP 2025 / ACS 2024
uv run --no-project --with osmium python scripts/build_stores.py             # OpenStreetMap Texas stores, restaurants
                                                                             # and venues (cinemas etc.), weekly
python scripts/build_branch_checks.py                                        # branches the chains' own locators no
                                                                             # longer list (AllThePlaces), after it
python scripts/build_logos.py                                                # a logo for each place a regular deal
                                                                             # is at, from its own website
```

## Industries

Tech & Electronics, Sports & Outdoors, Fashion & Apparel, Home & Garden, Beauty & Personal Care, Health & Wellness,
Grocery & Household, Toys Games & Hobbies, Baby & Kids, Pets, Automotive, Office & School, Restaurants & Dining and
Movies & Entertainment. The last two are local only: promotions and regular deals at places near you.

## Limits

- Weekly ads are the retailer's published claim. Prices can change after posting, so every deal links to its source.
- Walmart, Target, Best Buy's site, eBay, Home Depot, Lowe's and several other retailers block automated readers,
  and Slomp doesn't work around that. Their prices reach Slomp only through their weekly ads and deal posts.
- Store locations come from OpenStreetMap, which misses some regional chains. Those deals are shown as
  "store not confirmed" rather than dropped.
- Regular deals: Slomp shows the nearest branch, but can't tell whether that branch takes part, so each card carries
  the conditions and its evidence. The map can keep a branch after it closes; where a chain's own store locator is
  available, Slomp skips the branches it no longer lists (about 1 in 12), and elsewhere a card can still name a
  closed one. Deals announced only on social media, and chains whose pages sit behind bot checks
  with no dated article to stand in (Alamo Drafthouse's Tuesday tickets, for one), are missing.
- Regular deals at local places are the thinnest part: each is added by hand from the place's own page or a dated
  article. A few sites tell AI assistants by name to keep out (the Fort Worth Zoo, the Bullock Museum, The
  Infatuation's guides). Their pages are not used, because the curated list is kept up with an AI assistant. Add
  those deals to your own file if you want them.
- Online stores' sales come from deal sites' posts, not from the stores: Slomp re-reads each post to check it is
  still up, but can't check the sale on the store's own site (a fifth of stores answer with a bot check, and Amazon's
  and eBay's sites tell AI assistants by name to keep out). A sale that only a store's own site or email announces is
  missing.
- For personal research: respect each source's terms.
