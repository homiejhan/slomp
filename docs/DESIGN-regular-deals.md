# Regular deals: design

A **regular deal** is a standing offer that repeats on a schedule: Schlotzsky's buy-one-get-one pizzas on Wednesdays,
half-price movie tickets on Tuesdays, kids eat free on Sundays. Slomp v1 misses most of them, because they are not in
weekly ads and rarely appear in deal feeds: nobody posts news about an offer that has run every week for a year. Some
are announced only on the day, on social media, or never.

This document asks whether Slomp can find them from public sources, and designs the part that can be built.
Every source finding below was checked live on **Oct 5, 2026**.

**Short answer.** Yes for chains, partly for local businesses, and no for deals announced only on social media:

| Where the deal is stated | Can Slomp read it under its own rules? | What the design does |
|---|---|---|
| Day-of-week roundup pages kept current by editors | **Yes.** Two sites, 12 pages, about 400 entries | Parsed automatically every 12 hours |
| The company's own website or rewards page | **Often.** 24 of 38 sites probed served readable text; 8 served a bot check | A curated registry points at the page and the words that must be on it; Slomp re-reads it daily |
| A dated news or blog article | **Yes**, but it ages | Counts as evidence for 180 days |
| A site that tells AI assistants, by name, to keep out | **Not used**, though the general rule would let Slomp's reader in | The registry is researched and kept up with an AI assistant, so such a page is not evidence (2.2) |
| Social media only (Instagram, Facebook, X, TikTok) | **No.** Every platform forbids automated readers | You add the deal yourself; Slomp shows it labeled "added by you" |
| Nowhere in advance (decided on the day) | **No**, by definition | Same: a standing entry keeps it on its day |

So a deal that is "not announced until the day of" still shows on its day, as long as it is known to be a standing
offer from one of the first three rows or from you. What Slomp cannot do is discover a brand-new offer that exists
only in an Instagram story.

---

## 1. Requirements

### 1.1 Functional

| # | Requirement |
|---|---|
| R1 | Output 1 also lists every regular deal that runs on at least one day of the next 7 days at a place within the radius, for the chosen industries. |
| R2 | Each one shows the days it runs, its next dates, any time window ("after 5 pm"), its conditions ("rewards members", "dine-in only", "select drinks"), and the nearest branch. |
| R3 | Each one shows **how Slomp knows**: the kind of evidence, a link to it, and when it was last confirmed. |
| R4 | A regular deal appears on its day whether or not anyone announced it that day. It disappears when its evidence goes stale, says it ended, or its stated end date passes. |
| R5 | A fourteenth industry, **Movies & Entertainment**, holds cinema, arcade, bowling and museum discount days. It is local-only, like Restaurants & Dining. |
| R6 | You can add regular deals of your own in a file, for the ones only you know about. |
| R7 | The web page, API and CLI all show them. The web page shows them by day. |
| R8 | 200 live tests in the Austin, Houston and Dallas areas check accuracy and quality. |

### 1.2 Non-functional

| Property | Target | Why |
|---|---|---|
| Fidelity to evidence | ≥ 97% of shown regular deals have the day and the offer that their evidence page states today | The claim is "this runs every Wednesday"; a wrong day wastes a trip |
| No dead deals | 0 shown past a stated end date; evidence no older than the limits in 4.3 | Standing offers end quietly |
| Honest labels | Every card names its evidence; nothing is shown as confirmed unless the company's own page was read | The user must be able to judge how much to trust it |
| Vicinity | ≥ 95% have a branch within the radius per an independent store list | "Near you" must mean near you |
| Latency | Adds < 1 s to a warm search, < 20 s to a cold one | About 12 roundup pages and 40 company pages, each cached |
| Cost and politeness | $0, keyless, robots.txt respected, honest User-Agent, no logins, no bot-wall workarounds | Same constraints as v1 |

### 1.3 Constraints and assumptions

- Same rules as v1: public sources that need no key, robots.txt honored for web pages, bot checks never worked around.
- One rule is new. Where a site's robots.txt turns away an AI assistant's agents by name, its pages are not used as
  registry evidence, even though the same file lets ordinary readers such as Slomp in (2.2).
- "Participating locations" cannot be checked per branch. Slomp shows the condition and the nearest branch, and says
  that participation varies.
- A schedule is weekly (a set of weekdays) or monthly ("first Tuesday"), with an optional time window and an optional
  end date. Blackout dates such as holidays are shown as a condition, not modeled.
- Texas cities, the city's own time zone, and the three radii (10, 25, 50 miles), as before.

---

## 2. What the research found

"Slomp's reader" below means the same client the product uses: it identifies itself as `Slomp/1.0`, checks robots.txt
before reading a page, and treats a bot check as a refusal.

### 2.1 Social media

| Platform | robots.txt verdict for a profile or page | Notes |
|---|---|---|
| Instagram | Disallowed | Profiles also redirect to a login page |
| Facebook | Disallowed | Pages show a login wall after the title |
| X | Disallowed | Reading needs an account; the API has been pay-per-read since Feb 2026 ($0.005 per post), with no free tier |
| Threads | Disallowed | |
| Reddit | Disallowed (pages and JSON) | |
| Nextdoor, Pinterest, Linktree | Disallowed | |
| Yelp, Google Maps, Google Search | Disallowed | Business listings and their "offers" posts are off-limits too |
| TikTok | Could not be reached from the test network | The campus network blocks it |
| Bluesky | Allowed, and it has a keyless public API | Almost no restaurant or cinema chains post there |
| Telegram public channels | Allowed and readable | Almost no US businesses use them |

The official route does not help either. Meta's "Page Public Content Access" (reading posts of Pages you do not
manage) needs app review and business verification, granted case by case. X charges per post read. Neither is a
public, keyless source, so neither fits Slomp's constraints today. Section 8 lists them as an opt-in to revisit.

**Conclusion:** Slomp cannot read social media. What it can do is read the places where the same information is
repeated in the open: the company's own site, and editors who watch the brands' feeds and emails for a living.

### 2.2 Company websites and rewards pages

Slomp's reader requested one page from each of 38 company sites (cinemas, restaurants, entertainment, retail):

| Outcome | Sites | Examples |
|---|---|---|
| Readable text | 24 | Cinemark, Topgolf, Rosa's Café, Fuzzy's, Sonic, Chuy's, Dave & Buster's, Goodwill Central Texas |
| Bot check | 8 | AMC, Regal, Alamo Drafthouse, Studio Movie Grill, Star Cinema Grill, Violet Crown, Applebee's, Kohl's |
| Page is an empty shell filled in by JavaScript | 5 | Schlotzsky's, Whataburger, ShowBiz, LOOK, Flix Brewhouse's home page |
| Certificate does not match the site | 1 | Moviehouse & Eatery |

Where the page is readable, the deal is usually stated in plain words. Examples read by Slomp's reader:

- Cinemark, `/discount-tuesdays`: "Participating Cinemark theatres offer up to 50% off movie tickets on Discount Tuesdays."
- Rosa's Café, home page: "All Taco Plates are only $6.65 every Tuesday."
- Topgolf, home page data: "Enjoy Half-Off Golf all day Monday-Thursday when you book online."
- Schlotzsky's, FAQ page: "Schlotzsky's BOGO Wednesday offer is only available on Wednesdays."

The page that states a deal is often not the home page. Schlotzsky's home page is a JavaScript shell with no deal
text, and its FAQ page states the offer in full. So the registry (4.3) points at the exact page. Of the 127 pages the
research cited as evidence, Slomp's reader could read 107, and 18 answered with a bot check.

**Sites that turn away AI assistants.** Some robots.txt files let ordinary readers in under `User-agent: *` and then
name AI agents to keep out. Of the 65 sites the registry cites or was going to cite, three name Anthropic's agents:
the Fort Worth Zoo (its list includes `Claude-Code`), the Bullock Texas State History Museum, and The Infatuation,
whose city guides list local happy hours. Slomp's reader is not one of the named agents, so the standard would let it
read them. But the registry is researched and maintained with an AI assistant, which reads a page to write an entry
and to fix one later, and that assistant is exactly who those rules address. So these pages are not evidence: the
confirmer refuses them (`turns_away_ai` in `slomp/http.py`), two entries were removed (the zoo's half-price Wednesdays
and the museum's free first Sunday), and The Infatuation's guides were not used. You can still add such a deal
yourself (4.4); your entries are never fetched.

Rewards programs have two parts. The public page that describes the program is an ordinary web page and is read like
any other. The offers inside an account or an app need a login, so they are out of scope.

### 2.3 Day-of-week roundups

Two deal sites keep a page per weekday listing chains' standing offers. Both allow automated readers.

| Site | Pages | Structure | Kept current? |
|---|---|---|---|
| The Krazy Coupon Lady | Monday to Friday | Two lists per page, "Limited-Time" and "Every-[day]", one line per chain: `Chain: sentence` | Each page states its last-modified date; all five were modified between Sep 29 and Oct 5 |
| EatDrinkDeals | All seven days | A heading per chain, then paragraphs | Last-modified dates of Oct 1 to Oct 5 |

A prototype parser read all 12 pages: **404 entries**, of which **215 belong to 85 chains that OpenStreetMap maps in
Texas** (Sonic 728 locations, Schlotzsky's 205, Buffalo Wild Wings 90, Freebirds 48, Chuck E. Cheese 48, and so on).
The rest are chains with no Texas branches, or names the map files under another spelling.

The two sites are independent of each other, so when both list the same chain, day and offer, that agreement is
evidence. They also disagree at times, with each other and with the companies: one page says Dave & Buster's
half-price games run Sunday to Thursday, and the company's own page says "every Wednesday & Sunday". That is why a
company page outranks a list (4.5) and why the verification in section 5 checks lists against company pages.

Also found: The Krazy Coupon Lady's kids-eat-free guide and movie-discount article (modified May 19, 2026), and
Houston on the Cheap's kids-eat-free list of about 100 local restaurants by day. The last one was modified in February
2026, which is too old to trust under the rules in 4.3.

### 2.4 Maps and other structured data

- OpenStreetMap has a `happy_hours` tag. In all of Texas, **9** places carry it. Not usable.
- OpenStreetMap does map the venues: 399 cinemas (Cinemark 76, AMC 39, Alamo Drafthouse 18, Regal 18, …), 252
  bubble-tea shops, 105 bowling alleys, Dave & Buster's 11, Main Event 11. That is what places a deal near a city.
- The US Census geocoder turns a street address into coordinates, keyless. It places local shops that the map lacks.

### 2.5 The three examples from the request

| Example | Where it is stated | Result |
|---|---|---|
| Schlotzsky's BOGO Wednesday | The company's FAQ page ("only available on Wednesdays", one offer per transaction, some stores in the app only), and The Krazy Coupon Lady's Wednesday list | **Integrated**, confirmed on the company's site |
| Half-price movie tickets | Cinemark's own page (readable). AMC's and Regal's pages sit behind bot checks, so their evidence is dated third-party articles | **Integrated**; each chain labeled with the evidence it has |
| DOKA's BOGO Wednesday on select drinks | DOKA Bubble Tea, 2815 Guadalupe St, Austin. The offer appears only on its Facebook page. Its website forbids all automated readers in robots.txt, and its ordering page is a JavaScript app | **Not readable.** It becomes one of your own entries (4.4) |

DOKA is the honest limit of this design. A single shop that announces on Facebook and nowhere else can only enter
Slomp through a person.

### 2.6 What the research produced

Five research passes (cinemas and entertainment, quick-service chains, sit-down chains, local places in the three
metros, retail discount days) returned 207 candidate deals with their sources. Slomp's reader then re-read every
cited page. The registry was seeded with the 76 whose evidence it could read and match word for word. The two
verification runs (section 5) then took two out, under the rule in 2.2, and added 33 that two independent lists of
deals had and Slomp lacked. It now holds 107, on 69 pages of 62 sites:

| Kind | Entries | Examples |
|---|---|---|
| Movies and entertainment | 26 | Cinemark Discount Tuesdays, AMC 50% off Tuesdays and Wednesdays, Flix Brewhouse $6 Wednesdays, Dave & Buster's half-price games, Topgolf Half-Off Golf, free days at eleven museums and the Houston Zoo |
| Retail discount days | 8 | Goodwill Central Texas (four weekday sales), Walgreens Seniors Day, Ross 55+ Tuesdays, Savers Senior Tuesday, Rack Room Shoes' military Tuesday |
| Restaurant chains and groups | 41 | Schlotzsky's, BJ's daily specials, Pluckers, Perry's, Kerbey Lane, Luby's, Torchy's Hooky Hour, Taco Cabana, Hopdoddy, la Madeleine, Texas Roadhouse's Early Dine |
| Local places | 32 | Hank's, Quality Seafood and Sour Duck Market (Austin), Bryan Street Tavern and Maroma (Dallas), seven Houston steak nights, Uchi's happy hour in all three cities, six Dallas-Fort Worth kids-eat-free days |

Left out, as the rules require: deals whose only evidence was older than 180 days (Kohl's 60+ Wednesdays, Studio
Movie Grill $5 Tuesdays), pages behind bot checks with no dated article to stand in (Alamo Drafthouse, Santikos,
three museums), and places with no address to put on the map. One entry exists only to stop a false positive: the
roundups list Red Robin's weekday happy hour, and Red Robin's own page limits it to named restaurants in California,
Nevada and Arizona.

---

## 3. High-level design

### 3.1 Components

```
   ┌──────────────────────────┐  ┌───────────────────────┐  ┌──────────────────────────┐
   │ Roundup pages            │  │ Registry (in repo)    │  │ Your entries             │
   │ Krazy Coupon Lady Mon–Fri│  │ regulars.json: brand, │  │ ~/.config/slomp/          │
   │ EatDrinkDeals Mon–Sun    │  │ offer, days, evidence │  │   regulars.json          │
   └────────────┬─────────────┘  │ URLs + words to find  │  └────────────┬─────────────┘
                │ parse          └───────────┬───────────┘               │
                ▼                            ▼                           ▼
   ┌─────────────────────────────────────────────────────────────────────────────────────┐
   │ Regulars pipeline (same for every city, cached 6 hours)                             │
   │  1 Collect    roundup entries + registry entries + your entries                     │
   │  2 Normalize  chain → venue set · days and time window · offer terms · conditions   │
   │  3 Confirm    re-read each evidence page; record found / not found / unreadable     │
   │  4 Merge      same chain, same offer → one regular with all its evidence            │
   │  5 Gate       keep only those with live evidence; count the rest with the reason    │
   └───────────────────────────────────────┬─────────────────────────────────────────────┘
                                           ▼
   ┌─────────────────────────────────────────────────────────────────────────────────────┐
   │ Per search (city, industries, radius)                                               │
   │  6 Locate     nearest branch within the radius (OpenStreetMap venues, or the        │
   │               address on the entry)                                                 │
   │  7 Expand     the dates it runs on in the next 7 days, in the city's time zone      │
   │  8 Rank       discount strength × evidence strength; today first                    │
   └───────────────────────────────────────┬─────────────────────────────────────────────┘
                                           ▼
        LocalResult.regulars  →  API /api/v1/local · CLI `slomp local` · web page "Regulars" tab
```

It reuses v1's parts: the polite HTTP client and its cache, the offline OpenStreetMap datasets, `terms.py` for
buy-one-get-one and price wording, and the verification harness.

### 3.2 Data flow

1. **Collect.** Fetch the 12 roundup pages (12-hour cache) and parse them into entries: chain, weekday, sentence, the
   page's last-modified date. Load the registry and your file.
2. **Normalize.** Match the chain name to a venue set. Read the sentence for the time window, an end date, the offer
   (buy-one-get-one, percent, price and regular price) and conditions. Drop what is not a standing offer (4.5).
3. **Confirm.** For registry evidence, fetch the page (24-hour cache) and look for every required phrase in its
   visible text and in the text inside its data blocks. Record the result with the time.
4. **Merge.** Entries for the same chain whose offers match become one regular deal; its days are the union, its
   evidence is the list of everything that states it.
5. **Gate.** A regular deal needs at least one live piece of evidence (4.3). Others are counted under "left out".
6. **Locate, expand, rank** per search, then attach to the local result.

### 3.3 API, CLI and web page

- `GET /api/v1/local` gains `regulars` (a list) and `counts.regulars`. Each item has the usual deal fields plus
  `regular`: `days`, `days_text`, `time_text`, `next` (dates in the window), `until`, `status`, `evidence[]`.
- `GET /api/v1/meta` lists the fourteenth industry and marks which industries have online deals.
- `slomp local austin -i dining,entertainment` prints a REGULARS section grouped by day.
- `slomp regulars` prints the registry with each entry's evidence status, for upkeep.
- The web page gets a third tab, **Regulars**: a strip of the next seven days with a count on each, today selected,
  and a sort menu shared with the other tabs (best deal, ending soonest, name A–Z or Z–A).
  Regular deals are words, not product pictures, so their cards are compact rows: an icon for the kind of place,
  the brand and distance, the offer, "Every Wednesday · after 5 pm", and a small evidence label ("✓ Company site",
  "Listed by 2 sites", "Reported", "Added by you"). The details view lists the schedule, the next dates, conditions,
  the nearest branch and every piece of evidence with its link, its date and the words found.

### 3.4 Storage

- Roundup and company pages live in the existing HTTP cache.
- A new table `regular_checks` (regular id, URL, checked at, found, page date) keeps the confirmation history, so
  "last confirmed Oct 3" survives a day when the page is down.
- `slomp/data/regulars.json` is the registry. `slomp/data/venues_tx.json` is a new offline dataset built from the same
  OpenStreetMap extract: cinemas, entertainment venues and chains the restaurant dataset lacks.

---

## 4. Deep dive

### 4.1 Model

```
Regular deal  = brand · offer text · industries · schedule · terms · conditions · evidence[] · status
Schedule      = weekdays (Mon..Sun) or a monthly rule · start/end time of day · valid until (date)
Terms         = v1's Terms: buy-one-get-one, percent, price, regular price, basis
Evidence      = kind (official | rewards | list | article | yours) · source name · URL · the words found
                · the page's own date · when Slomp last checked · found?
```

On the wire a regular deal is a `LocalDeal` with one more field, `regular`, so the page, the ranking and the
verification harness handle it with the code they already have. `valid_from` and `valid_to` are its first and last
occurrence in the window.

### 4.2 Reading the roundups

- **Day.** The page is the day. An entry on the Tuesday page is a Tuesday deal even when the sentence does not repeat
  the word. On EatDrinkDeals, whose paragraphs often describe a chain's whole week, only sentences that name the
  page's day are kept.
- **Chain.** Matched to the map's chain names and aliases, with spelling variants normalized ("BJ's Restaurant" and
  "BJ's Restaurant & Brewhouse"). An entry whose chain has no mapped branch in Texas is dropped and counted.
- **Time window.** "after 5 p.m.", "from 2-5PM", "until 4 p.m.", "3-6 pm".
- **End date.** "through Dec. 31", "every Wednesday in September", "through Oct. 30". Past its end date an entry is
  dropped, even though the page still carries it.
- **Offer.** v1's wording rules: buy-one-get-one forms, "half price", "50% off", "$5.99 (reg. $9.99)", "kids eat
  free". A sentence with no concrete offer ("find coupons in the app every day") is dropped.
- **Conditions.** Rewards membership, an account, app or online only, dine-in only, at the bar, promo code, a minimum
  purchase, limits, "participating locations". A condition often comes a sentence or two after the offer ("You can
  only get the special for dine-in orders"), so a later sentence that restricts the offer is read for conditions even
  when it is not shown, up to the entry's next offer.
- **One offer at a time.** An entry often holds several offers. The hours in "plus Happy Hour specials from 3-6 pm"
  are the happy hour's, not those of the $8 martinis before it. A sentence that lists several offers with their own
  days ("an every day Value Menu starting at $1, taco specials on Tuesdays and Thursdays") gives each day only its
  own part, and nothing where the figure belongs to another day.
- **Text shown.** A trimmed copy of the roundup's own sentence, with a link to the page.

### 4.3 The registry and the confirmer

The registry covers what the roundups do not: cinemas, entertainment, retail discount days, Texas chains, and company
pages that confirm a roundup entry. One entry:

```json
{"id": "cinemark-discount-tuesdays", "brand": "Cinemark", "industries": ["entertainment"],
 "offer": "Discount Tuesdays: movie tickets up to 50% off, all day", "days": ["tue"], "pct": 50, "hedge": "up to",
 "conditions": ["participating theatres", "best price for Movie Rewards members (free to join)",
                "premium formats cost extra", "not on some holiday dates"],
 "evidence": [{"kind": "official", "url": "https://www.cinemark.com/discount-tuesdays",
               "find": ["up to 50% off movie tickets on Discount Tuesdays"]}]}
```

The confirmer reads each evidence page and looks for every phrase in `find`, in the visible text and in the text
inside the page's data blocks. The phrases must sit within 500 characters of each other, so "Tuesday" at the top of a
page and "kids eat free" at the bottom do not add up to a Tuesday deal. Case, quote style and dashes are ignored.
`absorbs` lists words that mark a roundup entry as the same offer, and `suppress` turns an entry into a stop for a
roundup entry known not to apply in Texas. Two more fields cover cases the first run turned up:

- `exact_days` says the company's page gives these days and no others for the offer. A list that puts the same offer
  on more days is then not followed (Dave & Buster's games: the company says Wednesday and Sunday).
- `sold_out` on an evidence page is a pattern such as `"{month} {day} - SOLD OUT"`. A free day that needs a reserved
  ticket can run out, and the Houston Zoo's page says so date by date. A date the page marks sold out is not shown.
- `expires_after` names the offer's own words on a coupon page. The date that follows them ("Expires 10/19/2026")
  becomes the deal's last day. Chuck E. Cheese's weekly coupons carry such a date, and their page moves it forward.
- `since` holds a deal back until a date. The Modern's galleries are closed until Oct 30, 2026, so its free Fridays
  and half-price Sundays start again on Oct 31.

Some sites serve two versions of a page at random (Fuzzy's home page carried its promotions in one and not in the
other for some hours on Oct 5, before dropping them). So where a page said it before, a miss is read again, up to two
more times, before it counts. The first design forgave one miss for a day instead; the second run's audit showed
that kept two deals up as "confirmed" after their page had stopped stating them.

A page on a site that turns away AI assistants (2.2) is refused before it is read. What counts as live:

| Evidence | Live when | Shown as |
|---|---|---|
| Company page (`official`, `rewards`) | Read within 7 days and every phrase found | "Confirmed on cinemark.com" + date read |
| Roundup list | The page was modified within 45 days and still lists it | "Listed by The Krazy Coupon Lady" + the page's date; two lists are stronger than one |
| Dated article | Published or modified within 180 days and every phrase found | "Reported by …" + its date |
| Your entry | Always | "Added by you" |

A company page that is read and no longer says it ends the deal at once. A page that cannot be read (bot check,
outage) is not a miss: the last successful check stands until it is 7 days old. A registry entry left with no live
page of its own steps aside, so a list that still carries the deal shows it in the list's own words.

### 4.4 Your own entries

`~/.config/slomp/regulars.json` (or the path in `SLOMP_REGULARS`) holds entries in the registry's format. An entry can
name a chain, or a single place by street address; Slomp geocodes the address with the Census geocoder. A `note` and
a `link` (for example the shop's Facebook page) are shown to you but never fetched. These are the only regular deals
Slomp shows without evidence it read itself, and each card says so.

### 4.5 Merging, and what is left out

Two entries for the same chain on the same day are one deal when the offers match: both buy-one-get-ones on a shared
item, the same price (within a few cents) on a shared item, or mostly the same words. Their evidence is pooled, which
is how a deal comes to be "listed by 2 sites". Days are pooled only when the wording is the same sentence seen on
several days' pages (a weekday happy hour): "BOGO traditional wings" on Tuesday must not borrow Thursday from "BOGO
boneless wings". A registry entry absorbs the roundup entries that match it, which is how a deal gets both
"confirmed" and "listed" evidence. When two lists describe one deal, the card carries the conditions of both, since
either may state a restriction the other leaves out. Where they disagree on how to order, the condition names the
list that states it: "dine-in only, says EatDrinkDeals" on a card whose other list says online orders count too.
When two lists give different prices for the same item, neither is shown, since
one of them is out of date and Slomp cannot tell which; a price that two sources agree on survives a third that
differs. When a list disagrees with the company's own page on a price, or on the days of an entry marked
`exact_days`, the company's page is followed and the list's version is left out.

Left out, each with a counted reason: one-off dates, grand openings, sweepstakes and gift-card offers, deals limited
to named places outside Texas, delivery-app promotions, entries past their end date, entries with no concrete offer,
everyday offers tied to no day or time, chains with no branch in the radius, dates a page marks sold out, and regular
deals whose evidence is not live.

### 4.6 Where it is

Restaurants use v1's dataset. `scripts/build_stores.py` gains a third output, `venues_tx.json`: every Texas cinema,
arcade, bowling alley and similar venue of the brands in `venue_brands.json`, matched by brand tag or by name
("Cinemark 17 and IMAX" is a Cinemark). Retail discount days use v1's store dataset. An entry with a street address
needs no dataset.

**Closed branches.** OpenStreetMap keeps a restaurant on the map long after it has closed: it still shows a Buca di
Beppo in Austin that the chain no longer lists. A regular deal's card names one branch, so a closed one costs a trip.
`scripts/build_branch_checks.py` compares the map with the chains' own store locators, as republished by
AllThePlaces, for the 74 chains that have one. A mapped branch with no locator branch within 0.75 miles is recorded
as unlisted in `branch_checks.json`, and the venue lookup skips it. Of 6,462 mapped branches of 68 chains, 550 (8.5%)
are unlisted: 10 of Red Lobster's 48, 19 of Dickey's 48, 7 of Quiznos' 8. Six locators looked incomplete (fewer
branches near Texas than 80% of the mapped count; Jack in the Box's scrape has 16 against 504) and are not used.
The cost is that a real branch a locator misses is skipped, and the next nearest one is shown instead. This applies
to regular deals only; v1's weekly-ad and promotion matching is unchanged.

**Logos.** Each card shows the company's logo. `scripts/build_logos.py` writes `logos.json` with one picture address
per chain or place, and the page loads the picture from where it lives. The company's own website comes first: its
home page is read under the usual rules (robots.txt, no bot-check workarounds, nothing from a site that turns away AI
assistants), its square app icon is preferred, then the largest icon it links, then `/apple-touch-icon.png` and
`/favicon.ico`. The website is the one a registry entry is confirmed on, a `site` the entry or venue rule names, the
chain's Wikidata website, or the link a deal list gives. A chain whose site gives nothing falls back on its Wikidata
logo, as a Wikimedia Commons thumbnail. Two guards: the site's address or title must name the brand (a deal-list link
can point at an ordering service; Wikidata itself lists a menu-price site as Texas Roadhouse's), and a WordPress
default icon is not a logo. Pictures under 32 pixels, or wider than 3.2 to 1, are not used, since they are
unreadable in a 56-pixel tile.

On Oct 5, 2026, 99 of the 137 chains and places had a logo, 94 from their own sites and 5 from Wikidata. Every one
was looked at on a single sheet; five were wrong and are excluded (two WordPress default icons, a hosting company's
generic file icon, a white logo invisible on white, and a plain gradient square), as was Wikidata's Cracker Barrel
logo, the 2025 redesign the company withdrew. The other 38 show the icon for their kind of place: sites behind bot
checks (Wingstop, Regal, la Madeleine), sites without a usable icon, and local places with no website found.

### 4.7 Occurrences in the next 7 days

For each day in `[now, now + 7 days]` in the city's time zone: the weekday must be in the schedule, the date must
not be past the end date, and for today the time window must not be over. A weekly deal therefore always has exactly
one or two dates in the window; the page shows the next one. "Until 4 pm" at 5 pm on a Wednesday means next
Wednesday.

### 4.8 Ranking

`score = percent × basis weight × evidence weight`, with v1's basis weights (a stated regular price counts fully, no
reference counts nothing) and evidence weights of 1.0 for a company page, 0.9 for two lists, 0.75 for one list, 0.7
for an article and 0.5 for your own. Within a day, higher scores come first.

### 4.9 Caching and error handling

- Roundup pages 12 hours, company pages 24 hours, the built set of regular deals 6 hours, all through v1's cache.
- A roundup page that fails to load removes only its own entries; the response's `sources` says so.
- If a roundup changes its layout, its parser finds few or no entries. Fewer than 5 entries from a page is reported
  as a source error instead of being trusted.

---

## 5. Verification

200 live tests on searches in the three areas (cities such as Austin, Round Rock, Cedar Park, San Marcos; Houston,
Sugar Land, Katy, Pasadena, The Woodlands; Dallas, Plano, Irving, Frisco, Arlington), with Restaurants & Dining,
Movies & Entertainment and the retail industries that have discount days. As in v1, every check uses its own fetch
and its own code, never the pipeline's cached copy or parser.

| Test | Count | Passes when |
|---|---|---|
| R-SRC evidence fidelity | 45 | The evidence page, fetched fresh and read by the test's own reader, states this chain, a day it runs on, and every amount, percent and buy-one-get-one the card shows |
| R-X other source | 25 | A source Slomp did not use for the deal (the other deal-site list for that day) states the same offer. The same item at a different price fails |
| R-DAY schedule | 30 | The dates shown are exactly the dates a separate calendar computes from the stated days, hours and end date, in the city's time zone |
| R-GEO vicinity | 30 | The distance shown is right and within the radius, and the branch shown is itself in the chain's own store locator (AllThePlaces, fetched fresh; used only when it is complete enough to say); for a single place, the Census geocoder puts its address where Slomp does |
| R-IND industry | 20 | A blind judge, given only the brand and the offer, picks an industry Slomp showed it under |
| R-TXT faithful summary | 20 | A blind judge, given Slomp's card and the text of every page it cites, finds no wrong day, price or condition and no missing condition that matters |
| R-REC recall | 30 | A deal from an answer key researched without sight of Slomp's data is in Slomp's results for that metro (50 miles): the place, a shared day and something of the offer must match. Absent is a fail, whatever the reason |

A test that cannot be made is recorded as inconclusive and replaced. Failures are triaged as a Slomp bug, a source
error or a test bug, fixed with a regression test, and re-run. Results go to `docs/VERIFICATION.md`.

**What the two runs found** (Oct 5, 2026; 400 tests, 361 passed):

- The tests of what Slomp shows passed 336 of 340: 166 of 170 in the first run and all 170 in the second. The
  non-functional targets in 1.2 for fidelity, dates and vicinity were met on every sampled card.
- Recall was 19 of 30 against a list of the best-known deals and 6 of 30 against a second list that excluded the
  first one's businesses. Local places are where it falls short, as the short answer at the top says.
- Samples were not enough. A sample of 20 summaries passed 16, and reading all 177 cards found 16 with a condition
  or a detail missing; a sample of 30 branches passed 30, and checking every branch found that 1 in 12 on the map is
  no longer in its chain's own locator. So the verification now has two parts: the 200-test run, and an audit of
  every deal (`regulars_run --audit`) that is cheap enough to run after any change to the parsing rules.
- Four rules came out of the runs and are described above: sites that turn away AI assistants are not registry
  evidence (2.2); a second list's conditions count (4.5); a page read three times that no longer states a deal ends
  it at once (4.3); and a branch its chain no longer lists is not shown as the nearest (4.6).

---

## 6. Scale and reliability

- **Load.** 12 roundup pages twice a day and 69 evidence pages once a day: about 100 requests a day, spread over
  about 65 hosts. Nothing here grows with the number of cities, because the set of regular deals is the same
  statewide; only the distance check is per city, and it is arithmetic.
- **Failure of one roundup.** The other still lists most chains, with weaker evidence ("one list").
- **Failure of both.** Registry entries with company pages remain. The response names the failed sources.
- **Silent rot** is the real risk: an offer ends and a page keeps it. The limits in 4.3, the end-date reading in 4.2
  and the company cross-check in section 5 are the defenses. `slomp regulars` shows every entry's evidence age.

---

## 7. Trade-offs

| Decision | Chosen | Alternative | Why |
|---|---|---|---|
| Social media | Not read | Scrape with a logged-in session, or pay for X's API | Every platform's robots.txt forbids it, and logins and paid keys break Slomp's constraints |
| Discovery | Editors' roundups, parsed | Crawl every chain's site | Two sites already do the watching; 85 Texas chains for 12 requests |
| Trust | Show the evidence and its age on every card | A single "verified" mark | Roundups are sometimes wrong, and the user should see what a claim rests on |
| Company pages | Curated URL plus phrases to find | Generic "find the deals page" crawler | A phrase check is exact and cheap; a crawler guesses, and half the sites are JavaScript or walled |
| Local shops | Registry entries where the place's own page or a dated local article states the deal; otherwise your own entries | Parse local guides wholesale | A guide is its publisher's own work, and the best one found turns away AI assistants; a registry entry restates one fact in Slomp's words and links to the page |
| Sites that turn away AI assistants | Not used for the registry | Read them under the general robots rule, which allows it | The registry is kept up with an AI assistant, and those rules are addressed to it; it cost two entries and one guide site |
| Shown text | The source's sentence, trimmed | Rewrite every offer | A rewrite can change the meaning; the judge test (R-TXT) checks what is shown |
| Per-branch participation | Shown as a condition | Read each branch's page | Thousands of pages, mostly unreadable |
| Which branch is nearest | The map's branches, minus those the chain's own locator no longer lists | The map alone | 8.5% of mapped branches of the 68 chains checked are not in their chain's locator; a closed branch on a card costs a trip |
| Model | One more field on `LocalDeal` | A separate type | The page, ranking and tests already handle `LocalDeal` |

## 8. What to revisit as it grows

- **Opt-in social reading**: a Meta developer app (after its review) or X's paid API, behind a key the user supplies.
- **The operating system's certificate store**, so sites with very new certificate chains verify as they do in a browser.
- **Per-branch pages** for cinemas, which often list their own discount day.
- **More roundups**, especially maintained local ones, as a third independent list.
- **Local coverage.** The first run's independent list had 9 well-known local deals Slomp lacked; local places are
  where recall is weakest, and each one is added by hand today.
- **A registry kept up without an AI assistant** would be free to use the pages ruled out in 2.2.
- **A form on the web page** for adding your own entries, and sharing them between users.
- **History**: once `regular_checks` has months of data, "confirmed every week since June" becomes a real signal.

## 9. What was built

| Part | Where |
|---|---|
| Schedule model, wording rules, occurrences | `slomp/schedule.py` |
| The two roundup parsers | `slomp/sources/roundups.py` |
| Venue lookup over the three map datasets | `slomp/sources/venues.py`, `slomp/data/venue_brands.json`, `venues_tx.json` (a third output of `scripts/build_stores.py`) |
| Branches the chains' own locators no longer list | `scripts/build_branch_checks.py`, `slomp/data/branch_checks.json` |
| Logos for the cards | `scripts/build_logos.py`, `slomp/data/logos.json` |
| Collect, normalize, confirm, merge, gate, locate, rank | `slomp/regulars.py` |
| The registry | `slomp/data/regulars.json` |
| Industry 14, service, API, CLI (`slomp regulars`), the Regulars tab | `industries.py`, `service.py`, `api.py`, `cli.py`, `static/index.html` |
| The 200 live tests, and the audit of every deal | `slomp/verify/regular_checks.py`, `regulars_run.py` (`--audit`), `JUDGE-REGULARS.md` |
