# Plum

Pick a **Texas city** and one or more **industries**. Plum returns:

1. **Near you, next 7 days:** every deal, discount or promotion at stores near that city, valid at some point in
   the next 7 days. It reads the weekly ads retailers publish for the city's ZIP code, plus restaurant-chain
   promotions that a nearby branch honors.
2. **Biggest discounts online:** the products in each industry with the highest discounts right now. Where other
   stores sell the exact same product, the discount is measured against their prices rather than a list price.

Everything comes from public, keyless sources. [docs/DESIGN.md](docs/DESIGN.md) covers the design and the research
behind it. [docs/VERIFICATION.md](docs/VERIFICATION.md) has the results of the live accuracy tests.

## Run it

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate   # keeps Plum's packages out of your base Python
pip install -e '.[dev]'
plum cities "san an"                          # find a city id (1,256 Texas places)
plum local austin -i tech,fashion             # deals near Austin in the next 7 days
plum local alpine -i grocery,dining -r 50     # small towns: widen the radius
plum online -i tech,home -n 10                # biggest verified online discounts
plum serve                                    # web page at http://localhost:8000, API docs at /docs
pytest                                        # offline unit tests
plum verify --iteration 1                     # 200 live accuracy tests (about 30 minutes)
```

## The web page

`plum serve` opens a single page: search a city, tap a distance and what you're shopping for, and browse picture
cards under two tabs, **Near you** and **Online**. Click a card for the details: what the discount is measured
against, dates, the nearest store, conditions, other stores' prices, and links to the ad or deal post. Searches are
kept in the address bar, so a results page can be bookmarked or shared. Pictures are the ad clippings and deal-post
photos, loaded from their sources.

The first search for a city reads about 150 source pages (about 10–60 seconds). Results are cached in
`~/.cache/plum` (`PLUM_CACHE_DIR` moves it). Set `PLUM_CONTACT` to a URL or email to add it to the User-Agent.

## Rebuilding the reference data

```bash
python scripts/build_texas_cities.py                                         # Census 2026 / PEP 2025 / ACS 2024
uv run --no-project --with osmium python scripts/build_stores.py             # OpenStreetMap Texas stores, weekly
```

## Industries

Tech & Electronics, Sports & Outdoors, Fashion & Apparel, Home & Garden, Beauty & Personal Care, Health & Wellness,
Grocery & Household, Toys Games & Hobbies, Baby & Kids, Pets, Automotive, Office & School, and Restaurants & Dining
(local promotions only).

## Limits

- Weekly ads are the retailer's published claim. Prices can change after posting, so every deal links to its source.
- Walmart, Target, Best Buy's site, eBay, Home Depot, Lowe's and several other retailers block automated readers,
  and Plum doesn't work around that. Their prices reach Plum only through their weekly ads and deal posts.
- Store locations come from OpenStreetMap, which misses some regional chains. Those deals are shown as
  "store not confirmed" rather than dropped.
- For personal research: respect each source's terms.
