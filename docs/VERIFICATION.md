# Verification log

Slomp is checked against the real sources, not against itself. Each iteration samples 10 Texas cities (3 with 200k+
people, 3 with 20k–200k, 4 under 20k) and spreads all 13 industries across them. It runs Slomp the way a user would,
then runs **200 live tests** that re-read each result from the source by a different route than the pipeline used.
Regular deals, added on Oct 5, have their own plan and results in [their own section](#regular-deals) below, and so
do online stores' sales, added on Oct 6 ([Online stores' sales](#online-stores-sales)). What Slomp misses, measured
against a manual search on Oct 13, is at the end ([Against a manual search](#against-a-manual-search-oct-13)).

Slomp was called Plum until Oct 5, 2026. The reports in `docs/verification/` from before the rename keep the old
name, in field names such as `plum_industries` and in the User-Agent they record (`Plum/1.0`).

| Group | Test | Count | Passes when |
|---|---|---|---|
| Local | Source fidelity | 40 | The item's own Flipp record, fetched fresh, has the merchant, title, price and dates Slomp shows (restaurant promotions: the post page still shows the offer) |
| Local | Time window | 15 | The source's dates overlap the next 7 days in the city's time zone, and "ends"/"starts" labels are right |
| Local | Vicinity | 20 | The chain's own store locator (AllThePlaces, independent of the OpenStreetMap data Slomp uses) has a store within the radius |
| Local | Industry | 20 | A blind judge, shown only the title and store, puts the item in the industry Slomp showed it under |
| Local | Terms and math | 10 | Percent and savings follow from the prices shown, and agree with the fresh record's own % off, $ off and original price; buy-X-get-Y offers are read as such |
| Local | Recall | 15 | A random item with a stated saving, which the source itself files under the industry, is in Slomp's output or was left out for a valid reason (no store nearby, ended, duplicate) |
| Online | Source fidelity | 25 | The deal's post page shows the price and product, and isn't marked expired |
| Online | Merchant link | 15 | The deal's store link (followed like a browser would) lands on the store Slomp names; an Amazon page's buy-box price matches, allowing for stated codes and coupons |
| Online | Comparisons | 20 | Each "same product elsewhere" listing, re-fetched, is the same product at the price shown (±2% or $1) |
| Online | Industry | 10 | Blind judge agrees |
| Online | Ranking and quality | 10 | Discounts recompute from the prices shown; order follows score; no duplicates, storewide sales or stale posts |

**Rules.** A test that can't be made (the source is down, blocks automated reading, or doesn't cover the subject) is
recorded as *inconclusive* and replaced by another subject of the same kind. A category that runs out of subjects
hands its remaining tests to its side's source-fidelity tests. Pass rates are over conclusive tests, and inconclusive
counts are reported alongside. Every failure is triaged as a **Slomp bug**, a **source error** (the source itself is
wrong or changed) or a **test bug**, fixed with a regression unit test where it is a Slomp bug, and the next iteration
runs on a fresh sample. Full per-test evidence is in `docs/verification/iteration-NN.json`.

## Summary

**1,968 of 2,000 live tests passed (98.4%)** over ten iterations: 100 city queries across 79 Texas places, from Corral City (population 41) to San
Antonio (1.5 million), including 20 places under 1,000 people, and all 13 industries (each queried 12–19 times). Another 437 attempts were inconclusive (a source
was down, blocked automated reading, or didn't cover the subject) and were replaced. The first iteration passed 94.5%;
the next nine passed 98.0–99.5%.

The 32 failures broke down into 26 **Slomp bugs**, all fixed with a regression test; 3 **source errors or drift** (an ad
mislabelled by its source, a post whose price changed); and 4 **test bugs**, fixed in the harness. One dog-bed failure
was both drift and a Slomp bug. Reviewing runs and auditing labels between iterations found about 20 more Slomp issues
before any test hit them; the biggest was false "out of stock" flags on Amazon pages.

| Category | Pass | Fail | Rate | Inconclusive |
|---|---|---|---|---|
| L-FID source fidelity | 329 | 1 | 99.7% | 0 |
| L-GEO vicinity | 199 | 1 | 99.5% | 84 |
| L-IND industry (blind judge) | 190 | 10 | 95.0% | 0 |
| L-MATH terms and math | 99 | 1 | 99.0% | 0 |
| L-REC recall | 148 | 2 | 98.7% | 63 |
| L-RET retailer page | 67 | 3 | 95.7% | 22 |
| L-WIN time window | 150 | 0 | 100.0% | 1 |
| O-CMP cross-site comparison | 10 | 0 | 100.0% | 3 |
| O-FID source fidelity | 435 | 5 | 98.9% | 0 |
| O-IND industry (blind judge) | 96 | 4 | 96.0% | 0 |
| O-MER merchant link | 145 | 5 | 96.7% | 264 |
| O-RANK ranking and quality | 100 | 0 | 100.0% | 0 |

**What the numbers do and don't say**

- **Local deals are accurate to their source.** Price, dates, merchant and title matched Flipp's own record 329 of
  330 times. The one miss was an ad Flipp pulled at 11:59 PM Eastern while Slomp still showed it until local midnight
  (fixed). The retailer's own product page confirmed the ad price or Slomp's stated regular price 67 of 70 times.
- **Industry labels are the weakest part:** 95% agreement with a blind judge for local deals, 96% online. Each miss
  was a keyword or a source label that read an item wrongly (a wine at a pharmacy, gardening gloves filed as apparel,
  a body wash "with vitamin B3"); each got a targeted fix. Expect a long tail of such cases.
- **"Near you" holds up.** 199 of 200 vicinity tests passed against the chains' own store locators, which are
  independent of the map data Slomp uses. 84 more couldn't be checked: AllThePlaces' Walmart and Target scrapes are
  partial, and it doesn't cover restaurant chains.
- **Cross-site comparison is the gap.** All 10 comparison listings tested were correct, but there were only 10. Per
  iteration, 2–5 of ~122 online deals carried a model number or UPC, and about one had 2+ other sites. Most deals in
  the feeds are no-name products sold in one place, and Walmart, Target, Best Buy and eBay block automated readers.
  Elsewhere each deal states its basis: the store's own regular price (~64%), a deal editor's check of other stores
  (~12%), price history (~8%) or a list price (~16%).
- **Merchant-link tests were mostly inconclusive** (264 of 409 attempts). Hip2Save and Slickdeals hide store links
  behind scripts or robots-disallowed redirects. The 150 conclusive ones passed 96.7%.
- **The iteration 10 fixes** (removed dealnews posts, the Eastern-time ad cutoff) were verified with regression tests
  and a live spot-check, not by an 11th iteration.

**Quality metrics** (recorded from iteration 4):

| Iter | Local deals | Firm basis | Online deals | With identity | 2+ other sites | Store-checked | Flagged changed |
|---|---|---|---|---|---|---|---|
| 4 | 1838 | 57% | 121 | 5 | 0 | 14 | 1 |
| 5 | 2226 | 50% | 121 | 5 | 0 | 13 | 0 |
| 6 | 2479 | 56% | 121 | 5 | 0 | 14 | 0 |
| 7 | 2003 | 51% | 122 | 5 | 1 | 15 | 1 |
| 8 | 1904 | 53% | 122 | 5 | 1 | 15 | 1 |
| 9 | 2046 | 52% | 122 | 4 | 1 | 14 | 0 |
| 10 | 2053 | 46% | 123 | 2 | 1 | 15 | 0 |


## Results by iteration

| Iter | Date | Cities (industries) | Passed | Rate | Inconclusive | Local | Online | Slomp bugs found |
|---|---|---|---|---|---|---|---|---|
| 1 | Oct 4 | San Antonio, El Paso, McKinney, Seguin, Pflugerville, Rockwall, Sun Valley, Woodway, Vinton, San Elizario (all 13) | 189/200 | 94.5% | 37 | 117/120 | 72/80 | 9 |
| 2 | Oct 4 | Arlington, Dallas, McKinney, Melissa, La Porte, North Richland Hills, Pottsboro, Graham, Vidor, Bayside | 199/200 | 99.5% | 35 | 120/120 | 79/80 | 1 (found by inspection) |
| 3 | Oct 5 | Irving, Garland, Plano, Horizon City, Royse City, Euless, Carthage, Noonday, Sadler, Poynor | 197/200 | 98.5% | 47 | 119/120 | 78/80 | 3 |
| 4 | Oct 5 | El Paso, Plano, Dallas, Missouri City, Deer Park, Odessa, Nome, Lyford, Pittsburg, Asherton | 196/200 | 98.0% | 38 | 117/120 | 79/80 | 3 |
| 5 | Oct 5 | Austin, Irving, Lubbock, Benbrook, Texarkana, Lufkin, Lake Worth, Rangerville, Mount Vernon, Scurry | 199/200 | 99.5% | 44 | 119/120 | 80/80 | 1 (+5 by audit, 1 by inspection) |
| 6 | Oct 5 | Irving, Lubbock, Grand Prairie, Hurst, Southlake, West Odessa, Corral City, Morgan, Savoy, Diboll | 196/200 | 98.0% | 60 | 116/120 | 80/80 | 2 (+4 by audit) |
| 7 | Oct 5 | Irving, Plano, Grand Prairie, Tyler, La Porte, La Marque, Troy, Caney City, Jayton, Wixon Valley | 199/200 | 99.5% | 42 | 119/120 | 80/80 | 0 (+8 by audit, 1 UX) |
| 8 | Oct 5 | McKinney, Dallas, Grand Prairie, Southlake, Alamo, Celina, Thorntonville, Hudson, Wells Branch, Woodway | 198/200 | 99.0% | 33 | 118/120 | 80/80 | 2 |
| 9 | Oct 5 | Laredo, Fort Worth, Grand Prairie, Wylie, Farmers Branch, Mesquite, Lipan, Lakewood Village, La Grange, Winters | 197/200 | 98.5% | 42 | 118/120 | 79/80 | 3 |
| 10 | Oct 5 | Plano, Lubbock, Dallas, Dickinson, Kyle, Hurst, Meadow, Natalia, Lake Bridgeport, Abernathy | 198/200 | 99.0% | 59 | 119/120 | 79/80 | 2 |
| **All** | | **100 city queries across 79 Texas places, all 13 industries** | **1,968/2,000** | **98.4%** | 437 | 1,181/1,200 | 787/800 | |

### Iteration 1 (seed 1007)

| Category | Pass | Fail | Inconclusive |
|---|---|---|---|
| L-FID source fidelity | 40 | 0 | 0 |
| L-WIN time window | 15 | 0 | 0 |
| L-GEO vicinity | 19 | 1 | 1 |
| L-IND industry (judge) | 19 | 1 | 0 |
| L-MATH terms and math | 9 | 1 | 0 |
| L-REC recall | 15 | 0 | 4 |
| O-FID source fidelity | 40 | 2 | 0 |
| O-MER merchant link | 11 | 4 | 30 |
| O-CMP comparisons | 3 | 0 | 2 |
| O-IND industry (judge) | 8 | 2 | 0 |
| O-RANK ranking and quality | 10 | 0 | 0 |

Only 5 comparison listings existed to test, so 17 of O-CMP's 20 tests moved to O-FID (42 run).

**Failures and fixes**

| Test | What happened | Kind | Fix |
|---|---|---|---|
| L-MATH Dollar General drain gel | Shown "saves $2.04"; the record says $2.00. Slomp derived a regular price from the ad's rounded "28%" | Slomp bug | A headline percent alone is shown as a percent; no regular price is computed from it |
| O-FID dealnews LEGO Williams Racing | Shown $51; the post says $50.99. The feed's structured price is rounded | Slomp bug | Prefer an exact price in the post text within $1 of the title's |
| O-FID Slickdeals Bedsure dog bed | Shown $26.40 (title); the post says "= $26.39" | Slomp bug | Same fix |
| O-MER Pepsi Zero Sugar "3 for $15" | Shown as $15 for one 12-pack; Amazon sells one for $6.97 | Slomp bug | "N for $X" is read as a multi-buy and compared per unit ($5.00 each) |
| O-MER Fanttik X8 inflator | $72 needs "extra 10% off in checkout"; Amazon's page shows $79.99 | Slomp bug | Cart and checkout discounts are a stated condition |
| O-MER adidas Supernova $39 | Amazon's default size and color is $74.90 | Slomp bug | Apparel sold on Amazon, Walmart or eBay carries "price varies by size or color" |
| L-IND KT therapy tape (Walgreens) | Shown under Beauty from Google's "Personal Care"; judge: Health, Sports | Slomp bug | Personal Care items are split by their words; therapy and braces go to Health |
| O-IND VitaUp vitamins | Hip2Save's beauty feed put vitamins in Beauty; judge: Health | Slomp bug | Hip2Save's categories are hints; the title decides |
| O-IND Women's cat Christmas tees | "cat" put a T-shirt in Pets; judge: Fashion | Slomp bug | Pets needs a pet product; bare pet words count only when nothing else names the item |
| O-MER Faux fur dog bed | Shown $64.99; Amazon now $72.99 for the default size | Source drift | none: the post's price changed or applied to another size |
| L-GEO Cabela's near Rockwall | The Allen, TX store is real; AllThePlaces' Cabela's scrape had 36 stores nationwide | Test bug | AllThePlaces is used only when it has at least half the stores OSM maps for that chain in Texas, and is merged across 3 runs |

**Quality finding.** Only 4 of 119 online deals carried a model number, so cross-site comparisons were rare. Slomp now
reads the Amazon page a deal links to (from the post, its page, or dealnews' Buy Now link). That page gives brand,
model number and UPC, which identify the product for other-site lookups. It also gives Amazon's live price: deals
whose price has moved back up are flagged "the deal may have ended" and ranked far lower. Also fixed: LEGO sets are
identified by set number, not the model car's name; product-line names ("Ultimate365") and accessories ("case for
Switch 2") are no longer compared as products.


### Iteration 2 (seed 2007)

All categories passed except one merchant-link test. O-CMP had no subjects: none of the 122 online deals got a
matching listing on another site, so its 20 tests moved to O-FID (45 run, all passed). Vicinity tests were
inconclusive 12 times because AllThePlaces' scrapes for Walmart (164 Texas stores vs 584 in OSM) and Target (42 vs
162) are too partial to rule anything out, and restaurant chains and GameStop have no AllThePlaces data.

| Test | What happened | Kind | Fix |
|---|---|---|---|
| O-MER Faux fur dog bed (again) | Amazon $72.99 vs the post's $64.99. Slomp's new store check caught the change, but labelled it "out of stock" | Source drift + Slomp bug | See below; Slomp now shows "store price now $72.99 (the deal may have ended)" and ranks it low |

**Found by inspecting the run, not by a failing test:** 7 of the 8 Amazon deals Slomp store-checked were flagged "out of
stock" although their pages showed a buy-box price. Every Amazon product page carries "Currently unavailable" in a
script's message table. Availability is now read from the buy box's own availability line (regression test added).
The verification parser had the same flaw and got the same fix.

**Comparison coverage, measured.** 2 of 122 online deals had a model number or UPC usable for lookups. Slomp resolved
the Amazon page for 8 deals; most of those pages give a UPC but no model number, and no free source with prices
exposes UPCs. Half the deals come from Hip2Save, whose store links are drawn by JavaScript. Verified cross-site
comparisons are therefore limited to model-numbered goods (electronics, appliances, tools, LEGO). Elsewhere each deal
says what its discount is measured against: the store's own regular price, a deal editor's check of other stores, or
a list price.

### Iteration 3 (seed 3007)

| Test | What happened | Kind | Fix |
|---|---|---|---|
| O-FID dealnews Hudson Baby sleeping bag | The post now redirects to dealnews' Amazon store page: the deal ended. Slomp's store check saw Amazon at $16.99 vs $10.94, but "Prime members" let it pass as a possible Prime-only price | Slomp bug | Slomp now re-reads the posts of its leading candidates and drops any that were removed (redirected or 404) or are marked expired |
| L-IND "Apothic Red" at Walgreens | No keyword matched, so it fell back to Walgreens' health/beauty prior; judge: grocery (it's wine) | Slomp bug | Pharmacies no longer have a prior (they sell wine, snacks and toys); wine varietals and brands added |
| O-IND Walmart drawstring bags (Hip2Save kids feed) | No keyword matched, so Hip2Save's kids category put it in Baby & Kids; judge: fashion | Slomp bug | Bag types (drawstring, crossbody, tote, duffel) added to fashion |

**Test changes from iteration 4.** A new **retailer page** test (10, taken from local source fidelity's 40) reads
the retailer's own product page for weekly-ad items (PetSmart, Old Navy, Ulta, Office Depot, Costco, Sam's Club and
others that answer a script). It passes when the page shows the ad's price, or the regular price Slomp states (weekly-ad
prices can be in-store only), and fails when it shows neither. It puts the ads themselves to a real-world test, which
source fidelity alone can't. Each report now also records quality metrics: share of deals with a firm basis,
online identity and comparison coverage, store checks, and deals flagged as changed.

### Iteration 4 (seed 4007)

First run of the retailer-page test: 9 of 10 retailer pages showed the ad's price or the regular price Slomp states.
Quality: 1,838 local deals, 57% with a firm basis (the store's own regular price), 0.1% at unconfirmed stores; 121
online deals, 14 store-checked live on Amazon (1 flagged as changed), 5 with a product identity, none with 2+ other
sites.

| Test | What happened | Kind | Fix |
|---|---|---|---|
| L-RET Dollar General Febreze | Slomp's "store page" link was Dollar General's coupons landing page, not the product | Slomp bug | Only product pages are shown as the store page |
| L-IND "Diamond Mesh Gate" at Kroger | The bare word "diamond" (added for jewelry in iteration 1) made a safety gate Fashion; judge: Baby & Kids, Pets | Slomp bug | "diamond" counts only with a jewelry noun; safety, baby and pet gates added |
| L-IND PetSmart reptile terrarium | Flipp's taxonomy said Home > Decor; judge: Pets | Slomp bug | Single-category stores (PetSmart, Petco, Ulta, Bath & Body Works, AutoZone, O'Reilly) decide their items' industry |
| O-FID Slickdeals adidas Grand Court | The post wrote "= $ 18.60" (a space after the sign) | Test bug | Price matching allows that space |

### Iteration 5 (seed 5007)

Every automated test passed (170/170); the judge disagreed once.

| Test | What happened | Kind | Fix |
|---|---|---|---|
| L-IND Miracle-Gro floral gloves (Tractor Supply) | Flipp's taxonomy says Clothing Accessories, so Fashion; judge: Home (gardening gloves) | Slomp bug | Garden, work and cleaning gloves and protective gear are Home whatever the taxonomy says |

**Found by auditing, between iterations 4 and 5:** a review of 70 random items labelled by keywords or store priors
found five collisions no judge test had hit yet: a plush bath towel (Toys), a flannel sheet set (Fashion), an espresso
machine (Grocery), a body groomer named "The Lawn Mower" (Home), and "Watch Party" (Fashion). Fixed with an early
rule for home textiles and kitchen machines, narrower toy and watch terms, and grooming terms; each has a regression
test.

**Found by inspection:** searches on other sites used Slomp's normalized model key ("Apple AIRPODSPRO3") instead of the
words as written ("Apple AirPods Pro 3", "Sony WH-1000XM6"), so the weekly-ad search could never match named products.
Fixed. Also: console bundles no longer match the console alone, and Slickdeals posts that list several stores
("Amazon has it for $51.99… Target has it for $51.99") now show those prices as "per the post", kept out of the
median of Slomp's own checks. The comparison test re-reads the post for them.

### Iteration 6 (seed 6007)

| Test | What happened | Kind | Fix |
|---|---|---|---|
| L-RET Dollar General Pedigree dog food, Tidy Cats litter | Dollar General's product pages draw prices with JavaScript, so neither price is visible to a script; the test read that as a mismatch | Test bug | A page without a structured price, where the ad price isn't visible either, is inconclusive |
| L-IND Ring indoor security cam (Best Buy) | Taxonomy "Home Security" mapped to Home; judge: Tech | Slomp bug | Home-security items are Tech and Home |
| L-IND bROK pintle hook (Tractor Supply) | Taxonomy "Hardware" mapped to Home; judge: Automotive | Slomp bug | Towing gear (pintle hooks, hitches, ball mounts, winches) is Automotive |

**Found by auditing iteration 5's online labels:** toner pads were Health (from "pads", added for incontinence
products), a night light was Tech (a generic "battery" term), a kids' terrarium kit was Pets, and DJI camera drones
were Toys (dealnews files drones under RC vehicles). Fixed with regression tests. Every deal with a real model number
now gets other-site lookups, not only the top 10 per industry.

### Iteration 7 (seed 7007)

The judge agreed on all 30 industry tests. Cross-site comparisons appeared for the first time: both comparison
listings checked out, and one deal's discount was measured against other stores' median price.

| Test | What happened | Kind | Fix |
|---|---|---|---|
| L-REC PetSmart "Foldable Pet Gate - Dog Gate" | Flipp files it under Baby Safety, so the recall test expected it under Baby & Kids; Slomp (rightly) treats everything at PetSmart as Pets | Source error | The recall test no longer fails Slomp where it deliberately overrides the source's category; the blind judge arbitrates those |

**Found by auditing taxonomy-labelled items (iterations 4–6):** Flipp files Target's promo banners under "Signage"
(Slomp had them as Office), a bottle jack under Material Handling, a tire repair kit under Plumbing, Target throws under
Outdoor Recreation, school glue under Adhesives, and power-tool batteries under Electronics; CVS fine print ("Must be an
ExtraCare cardholder…") was read as an item; and items with both health and beauty words got only one. Each fixed
with a regression test.

**Empty results.** Jayton (Automotive + Office, 25 mi) correctly returned nothing: only a Dollar General is that close.
Results now list advertising stores just beyond the radius (Tractor Supply 41 mi, Walmart 43 mi), and the page offers
a one-click 50-mile search.

### Iteration 8 (seed 8007)

Every automated test passed (170/170), including both cross-site comparison checks; the judge disagreed twice.

| Test | What happened | Kind | Fix |
|---|---|---|---|
| L-IND Caress body wash "…with Hyaluronic Acid & Vitamin B3" (Walmart) | The ingredient "Vitamin" made it Health as well as Beauty (a side effect of iteration 7's rule giving items with both kinds of words both labels); judge: Beauty | Slomp bug | Industry is read from the product's head phrase, before "with …"; the full title is used only if the head says nothing |
| L-IND Funko Jurassic Park plush (GameStop) | Flipp files it under Baby Toys; judge: Toys | Slomp bug | Baby Toys counts as Baby & Kids only when the item names babies, ages in months, teethers, rattles and the like |

### Iteration 9 (seed 9007)

| Test | What happened | Kind | Fix |
|---|---|---|---|
| L-REC Funko plush at GameStop, $0.02 "100% off" $4.99 | Slomp refused to believe a 99.6% saving from the ad (likely an ad error) but recorded it as "no saving stated" | Slomp bug (wrong reason) | Rejected savings are named: "implausible saving (99.6% off a $4.99 price: likely an ad error)"; the recall test accepts that reason |
| L-IND Michaels "ALL Scrapbook & Photo Albums" | Taxonomy Household Supplies mapped wholesale to Grocery & Household; judge: Home, Toys | Slomp bug | Household Supplies goes to Grocery & Household only for cleaning, laundry, paper and bags; the rest is Home |
| O-IND Perler fuse-bead kit (Hip2Save kids feed) | No keyword matched, so the kids feed put it in Baby & Kids; judge: Toys | Slomp bug | Craft kits, fuse beads, scrapbooks and coloring and sticker books are Toys |

La Grange (Restaurants + Sports, 25 mi) returned nothing: no sporting-goods ad within 25 miles, and none of this week's
chain promotions has a branch there.

### Iteration 10 (seed 10007)

The judge agreed on all 30 industry tests.

| Test | What happened | Kind | Fix |
|---|---|---|---|
| O-FID dealnews Hudson Baby sleeping bag (again) | The feed now linked this ended deal straight to dealnews' Amazon store listing page, so no redirect was left for iteration 3's fix to catch | Slomp bug | A post whose link is a dealnews store page, or whose page no longer shows the deal's title, counts as removed. Spot-checked live: dropped, along with 3 other ended posts |
| L-FID ULTA La Roche-Posay cleanser (Lubbock) | The ad ran "through Oct 4". Flipp encodes that as 11:59 PM Eastern and pulled the item at 10:59 PM Central; Slomp showed it until 11:59 PM local | Slomp bug | Dates still display as the day the ad names, but an item is live only until the earlier of the two times. Spot-checked live: Lubbock's ended ULTA ad is gone |

### Iteration 11 (seed 11007): after the web page rework

Putting pictures on the page exposed data errors the tests had only sampled, because the ad's own picture now sits
next to what Slomp says about it. Fixed before this run, each with a regression test:

- **The source's category labels can be absurd.** Flipp filed JCPenney diamond rings and a Best Buy ice-cream maker
  under Food, and Lowe's razor blades under Beverages. Slomp now keeps labels to what each kind of store sells (a
  `sells` list for 26 chains): a label outside it is replaced by what the item's words say, or by the store's own
  line. Food labels at stores that sell no food count only when the words agree.
- **Buy-one-get-one wording.** "BUY ONE. GET ONE 50% OFF" (a period), "Buy 1 get 1 50%* off" (an asterisk), "Buy 1 get
  150% OFF" (a missing space) and "Buy 2 get 3rd FREE" were misread as 50% off, free, "get 150" and "get 3". Offers
  without a price were also ranked last; they now rank by their effective saving.
- **Fine print is read per industry.** Slomp reads the full record of the first 24 deals in each requested industry
  (it used to read the first 40 overall), so the deals a user sees first have their buy-one-get-one terms and store
  links.

Result: **196 of 200 (98.0%)**, 61 inconclusive. Laredo, Austin, Arlington, San Angelo, Fresno, Victoria, Wallis,
Briaroaks, Premont, Navasota.

| Test | What happened | Kind | Fix |
|---|---|---|---|
| O-MER LOVEVOOK laptop backpack; UGREEN charger | The test took the first Amazon link on the post page, which was a related product, or compared a headline-style title with the listing's | Test bug (×2) | A store link the test finds itself is inconclusive unless its title matches; only Slomp's own store check can fail this way |
| L-IND SheaMoisture hair cream (Walmart) | Only a top-level "Health & Beauty" label and no keyword hit, so it was shown under both; judge: Beauty | Slomp bug | Hair, face and body creams, masks, oils and serums are Beauty |
| L-IND Composure bladder control pads (Dollar General) | Taxonomy Personal Care mapped to Beauty; judge: Health | Slomp bug | Bladder-control and incontinence products are Health |

Every source-fidelity, date, vicinity, math, recall, retailer-page, comparison and ranking test passed (168 of 170
automated tests; the two misses were the test bugs above). The recall test now treats any deliberate departure from
the source's category as inconclusive (5 this run), since the blind judge is the arbiter there.

### Iteration 12 (seed 12007): after regular deals were added

Regular deals touch code the first two outputs share: the industry list (now 14), the HTTP client, the service and
the local result. So the standard plan ran once more on the changed code, with the two local-only industries in the
draw (Lindale got Movies & Entertainment, Knox City got Restaurants & Dining).

Result: **196 of 200 (98.0%)**, 53 inconclusive. Irving, Grand Prairie, Austin, Rosenberg, Forney, Kingsville,
Lindale, Buda, Knox City, Runge. All 170 automated tests passed. The four misses were industry labels the blind judge
disagreed with, each from v1's keyword rules and each fixed with a regression test:

| Test | What happened | Kind | Fix |
|---|---|---|---|
| L-IND Puffin can cooler (Cabela's) | Taxonomy Kitchen & Dining made it Home; judge: Sports | Slomp bug | At a sporting-goods store, coolers, can coolers and ice chests are Sports & Outdoors |
| L-IND Milani setting spray (Walmart) | Only a top-level "Health & Beauty" label and no keyword hit, so it was shown under both; judge: Beauty | Slomp bug | Setting sprays, primers, eyeshadow, bronzer and several makeup brands are Beauty |
| O-IND Halloween bubble wands (Hip2Save kids feed) | No keyword matched, so the kids feed put it in Baby & Kids; judge: Toys | Slomp bug | Bubble wands, machines and guns are Toys |
| O-IND Foldable storage totes (Hip2Save) | The word "tote" made it Fashion; judge: Home | Slomp bug | Storage totes, bins, boxes and baskets are Home, ahead of the fashion rule |

## Regular deals

Regular deals ([DESIGN-regular-deals.md](DESIGN-regular-deals.md)) make a different kind of claim from the rest of
Slomp: not "this item costs $X this week" but "this place does this every Wednesday". They have their own plan. Each
run searches twelve places: Austin, Houston and Dallas at 25 miles with every industry that has regular deals, and
three randomly drawn suburbs of each with Restaurants & Dining and Movies & Entertainment at 25, 10 and 50 miles.
Then it runs **200 live tests**:

| Test | Count | Passes when |
|---|---|---|
| R-SRC evidence fidelity | 45 | The evidence page, fetched fresh and read by the test's own reader, states this place, a day the deal runs on, and every amount, percent and buy-one-get-one the card shows |
| R-X other source | 25 | A source Slomp did not use for the deal (the other deal site's list for that day) states the same offer; the same item at a different price fails |
| R-DAY schedule | 30 | The dates shown are exactly the dates a separate calendar computes from the stated days, hours and end date, in the city's time zone |
| R-GEO vicinity | 30 | The distance shown is right and within the radius, and the branch shown is itself in the chain's own store locator (AllThePlaces, fetched fresh, and used only when it is complete enough to say); for a single place, the Census geocoder puts its address where Slomp does. In run 1 any locator branch within the radius was enough |
| R-IND industry | 20 | A blind judge, given only the place and the offer, picks an industry Slomp showed it under |
| R-TXT faithful summary | 20 | A blind judge, given Slomp's card and the text of every page it cites, finds no day, price or condition the pages do not support, and no missing condition that changes who can get the deal or when. In run 1 the judge saw one passage of one page |
| R-REC recall | 30 | A deal from an answer key, researched by a separate agent with no sight of Slomp's code or data, is in Slomp's results within 50 miles of that metro's main city (25 in run 1): the place, a shared day and something of the offer itself must match. Absent is a fail, whatever the reason |

**Results in short.** Two runs, 400 tests: **361 passed (90.3%)**.

| | Run 1 | Run 2 | Both |
|---|---|---|---|
| What Slomp shows (evidence, other source, dates, location, industry, summary) | 166 of 170 | 170 of 170 | 336 of 340 (98.8%) |
| Recall against an independent answer key | 19 of 30 | 6 of 30 | 25 of 60 |
| All tests | 185 of 200 | 176 of 200 | 361 of 400 |

- **What is shown is accurate.** Across both runs every amount, percent and day on 129 sampled cards was on the
  page Slomp cites, the dates were right on 60, the branch shown was within the radius on 60, and the industry was
  right on 40. The four misses were all in run 1: two cards that left out a condition, and two the judge was shown
  too little of. Between the runs every card and every branch was checked, not a sample, and what that found
  (27 cards missing a condition or a detail over two readings, and 1 mapped branch in 12 that its chain no longer
  lists) was fixed before run 2.
- **Coverage is the weak part, and it falls off quickly.** Of the best-known recurring deals in the three metros
  (the first key), Slomp had 19 of 30. Of the next tier (the second key, which excluded the first key's businesses), it
  had 6 of 30. Chains on the two deal-site lists are covered well. Museums' free days, local happy hours and local
  kids-eat-free days are covered only where someone added them: 33 were added from the two keys.
- **Some deals Slomp will not show.** A deal stated only on social media, on a page behind a bot check, or on a site
  that turns away AI assistants is left out unless you add it to your own file.

The rules are the same as above: a test that can't be made is inconclusive and replaced, a category that runs out
hands its tests to R-SRC, and every failure is triaged and fixed with a regression test. R-X is rarely conclusive,
because the two lists seldom carry the same offer for the same chain and day, so most of its 25 tests move to R-SRC.
Full evidence is in `docs/verification/regulars-NN.json`; `regulars-00.json` is the last trial run made while the
tests themselves were being built.

### Run 1 (seed 1011, Oct 5)

Austin, San Marcos, Kyle, Round Rock; Houston, The Woodlands, Katy, League City; Dallas, Arlington, Garland, McKinney.
Slomp knew 184 regular deals statewide (60 confirmed on a company's own page, 107 on a deal-site list, 16 reported by
a dated article, 1 added by the user) and showed 174 different ones across the twelve searches.

Result: **185 of 200 (92.5%)**, 188 inconclusive (168 of them R-X).

| Category | Pass | Fail | Inconclusive |
|---|---|---|---|
| R-SRC evidence fidelity | 64 | 0 | 0 |
| R-X other source | 6 | 0 | 168 |
| R-DAY schedule | 30 | 0 | 0 |
| R-GEO vicinity | 30 | 0 | 8 |
| R-IND industry (judge) | 20 | 0 | 0 |
| R-TXT faithful summary (judge) | 16 | 4 | 0 |
| R-REC recall | 19 | 11 | 12 |

What Slomp showed matched its evidence: every amount, percent and day on 64 cards was on the page, the dates were
right on 30, a branch was within the radius on 30, and the industry was right on 20. The two weak spots were
conditions left off cards, and deals Slomp did not have at all.

| Test | What happened | Kind | Fix |
|---|---|---|---|
| R-TXT Bonefish Grill, $7 Bang Bang Shrimp on Wednesdays | The list says "You can only get the special for dine-in orders". That sentence is 71 characters, and the list reader kept follow-on sentences only up to 70 | Slomp bug | A later sentence that restricts the offer is kept and read for conditions, up to the entry's next offer |
| R-TXT Marco's Pizza, buy one get one on Tuesdays | The list says you must be signed in to a Marco's account; the card had no conditions | Slomp bug | Same fix; "signed in to an account" is now a condition |
| R-TXT Cinemark Discount Tuesdays | The judge was shown one 520-character passage. The card's conditions (members' pricing, premium formats, holidays) are stated elsewhere on the page | Test bug | The judge is shown a short company page whole |
| R-TXT Quiznos, $7.45 sub on Mondays | The judge was shown the entry without its page's title, "Monday restaurant deals", so the day looked unsupported | Test bug | List entries are shown with the title of their page |
| R-REC Hopdoddy happy hour; Houston Zoo free first Tuesday; Quality Seafood happy hour (Austin); Uchi happy hour | Each is stated on the place's own page, and Slomp had no entry | Coverage gap (×4) | Added, each confirmed on the company's page. The zoo's Oct 6 date is sold out by its own page, so Slomp holds it back this week |
| R-REC la Madeleine, Café Brazil and Mama's Daughters' Diner kids-eat-free days (Dallas); Maroma happy hour (Dallas) | Stated in dated local guides (DFWChild, CultureMap); Slomp had no entry, and la Madeleine was not on its map | Coverage gap (×4) | Added as "reported"; three restaurant groups added to the map |
| R-REC Fort Worth Zoo half-price Wednesdays | Slomp had it, but the zoo is 33 miles from Dallas and the test searched 25 | Test bug | The recall test covers the metro, 50 miles. See the note below: the entry was then removed |
| R-REC Bullock Museum free first Sunday (Austin) | Slomp had it, but the first Sunday was Oct 4 and the next is Nov 1, outside the 7 days | Test bug | The recall test counts a deal Slomp is holding back for lack of a date this week. The entry was then removed, as below |
| R-REC La Condesa happy hour (Austin) | The only page that states the offer is on a site that turns away AI assistants; La Condesa's own page gives the hours but not the offer | Left out by rule | None |

**A rule that came out of this run.** Checking the pages behind the missed deals showed that some sites let ordinary
readers in but tell AI assistants, by name, to keep out: The Infatuation (whose guide was the answer key's source for
three Austin happy hours), the Fort Worth Zoo and the Bullock Museum. Slomp's registry is researched and kept up with
an AI assistant, so those pages are no longer used as evidence, although robots.txt would let Slomp's own reader in.
That removed two entries Slomp had (the zoo and the museum above) and ruled out one source. The design document
explains the reasoning (section 2.2).

**Rechecked after the fixes** (the same answer key, so this is a check of the fixes and not a fresh measurement):
27 of the 30 conclusive deals are found. The three still missing are the ones left out by that rule.

### Between the runs: everything, not a sample

Run 1's samples passed on evidence, dates and location. But 20 or 30 samples cannot say how often a card is wrong,
and the two summary failures suggested more of the same kind. So before a second run, every regular deal within 50
miles of the three cities went through the checks, not a sample of them.

**Every card read against its page.** A blind judge, with the same instructions as R-TXT, compared all 177 cards
that cite a page with the text of that page. It marked 21. Sixteen were real, and nearly all of one kind: the card
was right as far as it went and left out something the page says.

| What the judge found | Cards | Fix |
|---|---|---|
| A condition stated a sentence or two after the offer: an account and a $10 purchase (Shake Shack), "redeem online or in the app" (Sonic), a $6, $11.99 or $12 minimum purchase (Huddle House, Main Event, Dickey's), "in the bar" (The Cheesecake Factory), "dine-in on Wednesdays only" (Outback) | 7 | The list reader keeps a restricting sentence up to three sentences on, and a later sentence about the same thing is read for conditions; six more wordings are recognized |
| The section's opening sentence says who the deals are for ("IKEA Family members can enjoy …") | 2 | The opening sentence is read for conditions |
| Hours that differ by day shown as one set (Dave & Buster's happy hour: Monday to Thursday two windows, Friday one, Sunday the other) | 1 | No hours are shown, and the card says "hours differ by day" |
| One sentence for Monday and its twin for Tuesday merged into one card that read "on Mondays" and ran both days (Wingstop) | 1 | Sentences that name different days stay separate cards |
| "Every Wednesday … Offer valid on Sept. 30": shown on Oct 5 (Wayback Burgers) | 1 | A date an offer says it is valid on is its last day |
| A registry entry without the hours its article gives (Drinks Lounge, Austin: 4 pm to midnight) | 1 | Entry corrected |
| The museum's page says its galleries are closed until Oct 30 (The Modern, Fort Worth: free Fridays, half-price Sundays) | 2 | Both entries are held back until Oct 31 |
| A weekly coupon's page states an expiry, Oct 19 (Chuck E. Cheese) | 1 | The expiry on the page is read each day and shown as the deal's last day |

The other five marks were the test's doing, and the test was changed. Three cards rest on two pages and were judged
against one (Uchi's nine-course tasting is on its menu page and its hours on its location page; a condition on
Bruster's card comes from the second of two lists). Two were Fuzzy's, whose home page is served in two versions, one
without its promotions. The judge now sees every page a card cites, and Slomp's own reader re-reads a two-version page
before counting a miss.

**Read again after those fixes.** The judge then read all 173 cards a second time, now with every page each card
cites. It marked 13. Two were the test's (a passage that missed the line the card rests on). Ten were one more kind
that the first reading could not see, because it showed the judge one page per card: when two lists describe the same
deal, the card had kept the first list's conditions and dropped what only the second one says ("Dine-in only" on
Logan's, Red Lobster's and Buca di Beppo's cards, "online or with the KFC app" on four KFC cards, a lunch-only price
at Cracker Barrel). A restriction that either list states is now shown. Where the two lists disagree on how to
order, the card names the one that says it: Buffalo Wild Wings' Tuesday wings read "dine-in only, says
EatDrinkDeals", because the other list says online orders count too. The last was a registry entry (Perry's Sunday
supper) that lacked the hours and "dine-in or to-go" from Perry's own page.

**Every branch checked against its chain's own store locator.** The first pass failed 13 chain-and-city pairs. Most
were locator scrapes with gaps (Jack in the Box: 16 branches near Texas against 504 on the map). One was not: the map
still has a Buca di Beppo in Austin that the chain no longer lists. Comparing all 74 chains that have a locator
showed how common that is: 550 of 6,462 mapped branches (8.5%) are not in their chain's own list, among them 10 of
Red Lobster's 48 and 7 of Quiznos' 8. Slomp now skips those branches when it names the nearest one
(`branch_checks.json`, design 4.6), and the R-GEO test was tightened to match: the branch shown must itself be in the
chain's locator, where the locator is complete enough to say.

**Every list deal read through.** Reading all 108 list-sourced cards turned up six more:

| Card | What was wrong | Fix |
|---|---|---|
| Bar Louie, $8 martinis on Mondays | Shown as 3–6 pm: the hours of "plus Happy Hour specials from 3-6 pm" in the same sentence | Another offer's hours in the sentence are not borrowed |
| Grimaldi's, $10.99 pizza lunch | Shown with the hours of the Social Hour in the sentence before | An offer that states its own days does not borrow the sentence before it |
| Del Taco, "$1 on Tuesdays and Thursdays" | The $1 is the every-day menu's; the Tuesday and Thursday specials had no figure in that sentence | A sentence listing several offers gives each day only its own part |
| Red Lobster, all-you-can-eat shrimp on Saturdays, Sundays and Mondays | The sentence before says it is available every day | An offer introduced as every-day is treated as one |
| Dave & Buster's, half-price games "Sundays to Thursdays" | The company's own page says Wednesday and Sunday (and Slomp's entry said Wednesday only) | Entry corrected; a list cannot add days to an offer the company dates exactly |
| Whole Foods, "buy 1, get 1 for 50% off" | Read as a free second item (a v1 wording rule) | "for 50% off" and "at half price" are read as such |

**Coverage.** Four chains the lists carry were on the map under another spelling (Famous Dave's, Morton's, The
Melting Pot, Brio), and Whole Foods' Prime-member days were added, with grocery among the industries searched.

After these fixes the same checks were repeated over everything before the second run: the evidence test passed
for all 173 deals that cite a page, the schedule test for every card in the three cities, and the location test for
159 chain-and-city pairs with none failing (61 could not be judged: no locator, or an incomplete one). The audit is
now a command, `python -m slomp.verify.regulars_run --audit`.

### Run 2 (seed 2011, Oct 5): after the fixes, with a second answer key

Austin, Pflugerville, Kyle, Cedar Park; Houston, League City, Pasadena, Katy; Dallas, Frisco, Plano, McKinney, with
Grocery added to the main cities' industries. Slomp knew 195 regular deals statewide (64 confirmed, 110 listed, 20
reported, 1 added by the user) and showed 174 different ones.

Result: **176 of 200 (88.0%)**, 178 inconclusive (169 of them R-X).

| Category | Pass | Fail | Inconclusive |
|---|---|---|---|
| R-SRC evidence fidelity | 65 | 0 | 0 |
| R-X other source | 5 | 0 | 169 |
| R-DAY schedule | 30 | 0 | 0 |
| R-GEO vicinity | 30 | 0 | 9 |
| R-IND industry (judge) | 20 | 0 | 0 |
| R-TXT faithful summary (judge) | 20 | 0 | 0 |
| R-REC recall | 6 | 24 | 0 |

Every test of what Slomp shows passed, 170 of 170, including all 20 summaries (16 of 20 in run 1). All 24 failures
are recall, and recall fell because the answer key was made harder on purpose. Its researcher was given the 28
businesses of the first key and told to name 42 others, one deal each. So this key measures the next tier of deals,
past the best-known ones, and there Slomp had 6 of 30.

| What was missing | Deals | Where it is stated | What was done |
|---|---|---|---|
| Free days at museums: Texas Science & Natural History Museum and Mexic-Arte (Austin); Holocaust Museum, Children's Museum and The Health Museum (Houston); Meadows Museum and the Nasher (Dallas) | 7 | Each museum's own page | Added, each confirmed on that page |
| Kids' meal days at Dallas-Fort Worth restaurants: Black-Eyed Pea, Slim Chickens, Modern Market, Colter's, El Rincon, Central Market's café | 6 | DFWChild's dated guide | Added as "reported", with two more from the part of the key the run did not draw |
| Happy hours at four East Austin restaurants | 4 | A local guide that answers Slomp's reader with a bot check | Sour Duck Market states its happy hour on its own page and was added. Casa Bianca, Licha's Cantina and Suerte are still missing |
| Chain early-bird menus: Texas Roadhouse, Cracker Barrel, The Capital Grille | 3 | A dated article | Added as "reported"; two chains added to the map |
| Houston steak nights: Confessions, Johnny Ritas | 2 | An article Slomp already used for five others; it gives no street addresses | Confessions added, with the address from its opening story. Johnny Ritas left out: no address on a page Slomp read |
| Taco Bell's "Tuesday Drops" | 1 | A list Slomp reads | Left out on purpose: "a money-saving promo code" names no offer |
| Dollar General's Saturday coupon | 1 | A dated post about one Saturday | Left out: the page does not say it repeats |

**Rechecked after the additions** (a check of the additions, not a fresh measurement): 33 of the second key's 42
deals are found, and 27 of the first key's 30 conclusive ones. The nine and three still missing are the ones the
tables above leave out, plus three deals from the second key that the run did not draw (a steak night without an
address, a happy hour behind the same bot check, and a thrift store's rolling weekly sale that is tied to no day).

**The new and changed cards read once more.** The 37 cards that were new or had changed since the second reading
went to the judge again: 34 were faithful. Two of the three marked were the test showing the wrong passage of a long
guide (its pointer was a phrase the guide repeats twelve times; it now uses words the page has once). The third was
Buffalo Wild Wings' Thursday wings, where the two lists disagree on how to order; the card now says so: "takeout or
delivery, says The Krazy Coupon Lady (EatDrinkDeals differs)".

**One more rule from the final audit.** The audit after run 2 failed two cards on evidence: Fuzzy's two offers,
shown as "confirmed" while its home page had stopped stating them. Slomp had forgiven a single miss for a day, in case
the page was served in two versions. It now reads such a page three times instead, and a miss ends the deal at once.
With that, the last audit of all 195 regular deals near the three cities passed the evidence test for all 194 that
cite a page, the schedule test for all 411 cards, and the location test for 176 chain-and-city pairs, with none
failing (71 could not be judged).

## The published site

The published site ([DESIGN-static-site.md](DESIGN-static-site.md)) answers each search in the browser, from data
files a scheduled build writes, with `engine.js`: a second implementation of the per-search part of Slomp (which ads
a city gets, nearest store or branch, radius, the next 7 days in the city's own time zone, duplicates, order).
`python -m slomp.verify.site_check` checks it against the server. It builds the site, then answers 60 searches twice
from the same data at the same moment, once with the server and once with `engine.js` run in Node, and compares every
field of every deal: the deals in each list and their order, stores, distances, dates, terms, scores and kinds;
regular deals and their next dates; restaurant promotions; online deals.

Half the searches are in anchor cities, which read their own ZIP's ads on the site, so everything must match. The
other half are in other cities, where regular deals, promotions and online deals must match, and the weekly ads are
measured: the server reads the city's own ZIP, the page its nearest anchor's.

| Run | Searches | Match | Anchor cities | Other cities | Other cities' weekly ads: share of the server's deals the page shows |
|---|---|---|---|---|---|
| 1 (seed 7) | 60 | 38 | 0 of 22 | 38 of 38 | 95.1% |
| 3 (seed 7, after the fixes) | 60 | **60** | 22 of 22 | 38 of 38 | 97.9% |
| 4 (seed 11, a new sample) | 60 | **60** | 22 of 22 | 38 of 38 | 96.9% |

Run 2 was stopped partway, once it had shown the last of the problems below.

**What runs 1 and 2 found, and what changed.**

- **A build bug: ads from a retailer's own product feed.** Whether an ad's items come from the retailer's product feed
  changes what counts as a saving. The server learns it from the first search that shows the ad, then reads the ad's
  items knowing it. The build read every item before learning it, so some feed items with real savings were left out
  as "no saving stated" (a $0.02 clearance plush at Waco, among others). The build now reads those ads' items again
  once it knows (114 of 364 ads).
- **Weekly ads for the biggest cities.** Run 1's anchors were the largest city, then the largest not yet within
  20 mi of one. That left Plano, Irving, Denton, Odessa and Pearland using a smaller neighbour's ads. Every city of
  50,000 people or more is now an anchor and reads its own ZIP's ads (303 anchors instead of 269).
- **Flipp's item search returns at most ~150 items per merchant, and which ones differs by ZIP.** For example, Family
  Dollar's weekly ad has 137 items, and a search at a ZIP returns either 113 or 123 of them, with no pattern by
  region or time. An item with no search result often has no saving to show and is left out. That applies to the
  server too, from whatever its own ZIP's search returned. The build keeps every result from every search it makes,
  and searches again where items are still missing. Even so, about 20% of the items in Texas ads still have no search
  result after the build's searches (Walgreens' ads run to 420 items).
- **Two problems in the check itself, not the site.** The check's server was reading more fine print than the build
  had. Two deals tied on every sort key can come in either order. Since run 3, the server in the check reads exactly
  the fine print the build read and uses the item search results the build collected; what each of those costs is
  counted separately (below). Ties on every key are accepted in either order.

**What the site gives up, measured.** Two kinds of difference are not the engine's doing:

- **Fine print.** The build reads the leading deals' fine print for every anchor at each radius. Across run 4's
  60 searches, 10 deals in a search's lead had not been read.
- **Item search results.** A city's own search returned 1,669 items that the build's searches had not.

**Against the server as it is (run 5).** This is what a user would see differ. It reran run 4's 60 searches with the
server reading its own fine print and doing its own item searches, as `slomp serve` does:

| | Weekly-ad deals the server shows that the page also shows | Page's deals that the server also shows |
|---|---|---|
| Anchor cities (22 searches, 1,994 deals) | 99.9% | 99.9% |
| Other cities (38 searches, 5,730 deals) | 95.7% | 95.4% |

Regular deals, restaurant promotions and online deals matched in all 60 searches. The reports are
`docs/verification/site-NN.json`.

**On GitHub's servers.** The checks above ran on a home connection. The first build in GitHub Actions read every
anchor's ads, every deal feed and both deal lists, but 13 company sites answered GitHub's data centers with a bot check
(the build log names them), so the 18 regular deals only their pages confirm are missing from the published site: 200
regular deals instead of 217. Chuck E. Cheese's and Fuzzy's offers still show, as listed by the deal sites.


## Online stores' sales

Sales at online stores ([DESIGN-online-stores.md](DESIGN-online-stores.md)) make a third kind of claim: "this store
has this sale, with this code, until this date". They are the same for every city, so a run reads every source once
and searches by industry: each of the 12 online industries alone, then four mixes. Then it runs **200 live tests**
(`slomp verify --iteration N --plan sales`), each reading its source again by its own route:

| Test | Count | Passes when |
|---|---|---|
| S-SRC source fidelity | 50 | The post page, read now (only the post's own text, not the site's menus or the deals beside it), names the store and states every figure of the offer and the code, and is not taken down or marked expired |
| S-END dates | 30 | The sale is live now; the end Slomp shows is one the post states (a source's own end date may be a time zone off); a sale with no end shown has none stated. Half go to ends read from the post's words |
| S-STORE store | 25 | The post sends you to the store, names it as the seller ("Amazon is offering", "Shop Now at Kohl's"), or links to its site |
| S-SHIP ships | 20 | A blind judge, given only the post, says it is from a store you can order from and have shipped |
| S-MANY a sale | 20 | The judge says it is a sale on many products, not one product at one price |
| S-IND industry | 20 | The judge picks an industry the sale was shown under in that search |
| S-OFFER offer and code | 20 | Every figure on the badge and the offer line is in the post's title; a firm percent is not an "up to" one; the code is in the post as written. Half go to sales with a code |
| S-QUAL quality | 15 | Across a search's whole list: no duplicates, nothing ended or stale, best-first order |

The judge's prompt is in `backend/slomp/verify/JUDGE-SALES.md`. Full evidence is in `docs/verification/sales-NN.json`.

**Results in short.** Four runs, 800 tests: **780 passed (97.5%)**, none inconclusive.

| | Run 1 | Run 2 | Run 3 | Run 4 |
|---|---|---|---|---|
| All tests | 190 of 200 (95.0%) | 195 of 200 (97.5%) | 197 of 200 (98.5%) | 198 of 200 (99.0%) |
| Slomp's own errors | 8 (industry) | 3 (industry 2, one product) | 1 (store) | 0 |
| Judgment calls | 0 | 0 | 2 | 2 |
| Test bugs | 2 | 2 | 0 | 0 |

| Over the four runs | Passed |
|---|---|
| S-SRC: the post shows the store, every figure and the code, and is still up | 199 of 200 (the miss was a test bug) |
| S-END: the end shown is the one the post states, and the sale is live | 118 of 120 (both misses test bugs) |
| S-STORE: the post names or links the store shown | 98 of 100 (one Slomp bug, one test bug) |
| S-OFFER: badge, offer line and code agree with the post | 80 of 80 |
| S-QUAL: no duplicates, nothing ended or stale, best-first order | 60 of 60 |
| S-SHIP: a store that ships (judge) | 80 of 80 |
| S-MANY: a sale on many products (judge) | 78 of 80 |
| S-IND: the industry (judge) | 67 of 80 |

- **What a card says is accurate.** Across 200 post-fidelity, 120 date and 80 offer tests, every offer figure, code
  and end date checked was right (the three misses there were in the tests), and every list was free of duplicates
  and of ended or stale sales. The codes were also read one by one while building,
  which led to the rule that a code's own sentence decides (below).
- **Where to file a sale was the weak part, and it improved run by run** (12, 18, 19 and 18 of 20). The first version
  gave a store-wide event every industry its store sells; it now counts for the goods its post names. What remains are
  judgment calls: a store-wide event whose post mentions baby clothing or a desk in passing is also shown under Baby &
  Kids or Office, where the judge would not look for it.

### Run 1 (seed 1013, Oct 6)

Slomp held 208 sales that had not ended, at 49 stores: 150 from dealnews, 39 Hip2Save, 12 9to5Toys, 6 Slickdeals and
1 The Inventory; 49 with a code and 137 with an end date. Searches showed 11 (Pets) to 99 (Fashion, Grocery and Health)
sales. Result: **190 of 200**, none inconclusive.

| Category | Pass | Fail |
|---|---|---|
| S-SRC source fidelity | 49 | 1 |
| S-END dates | 30 | 0 |
| S-STORE store | 24 | 1 |
| S-SHIP ships (judge) | 20 | 0 |
| S-MANY a sale (judge) | 20 | 0 |
| S-IND industry (judge) | 12 | 8 |
| S-OFFER offer and code | 20 | 0 |
| S-QUAL quality | 15 | 0 |

Every store, offer, code and end date checked was right. Before this run, while building, the codes had been read one
by one against their posts, which found three wrong ones and led to the rule that a code's own sentence decides: J.Crew's
CARDLOVE is for its credit card's holders, a QVC code (JOLLYQ20) sat in a post about Birkenstocks at QVC, and Sephora's
DELIVERED buys free delivery, not the discount. What the run found was about industries:

| Test | What happened | Kind | Fix |
|---|---|---|---|
| S-IND AliExpress Halloween Deals (under Pets); Costco Member Appreciation and October Online Savings (under Auto); Amazon Prime Big Deal Days (under Grocery); Walgreens Halloween Weekly Deals (under Baby & Kids) | A store-wide event counted for everything its store sells, which for Amazon, Costco or AliExpress is every industry | Slomp bug (×5) | A store-wide event counts for the kinds of goods its post names (its category and its words), kept to what the store sells |
| S-IND Nutramax Cosequin supplements (under Health) | A dog joint supplement read as a vitamin | Slomp bug | "for dogs" and the brand name are pet words |
| S-IND ZURU My Mini Baby sets (under Baby & Kids) | A toy line whose name says "baby" | Slomp bug | A rule for toy lines with "baby" in the name, ahead of the baby words |
| S-IND Wayfair cardboard standups (under Office) | The post's category (party supplies) is outside what Wayfair sells, and the fallback was all three of Wayfair's lines | Slomp bug | The fallback is the store's own main line |
| S-SRC 9to5Toys Fanttik tools (store not named) | The test read only the page's cut-off summary; the article names Amazon and links to it | Test bug | The test reads 9to5Toys' article body |
| S-STORE Slickdeals grocery code (store not named) | The post opens "Amazon is offering…", a phrasing the test didn't accept | Test bug | The test accepts the seller named as the subject |

### Run 2 (seed 2013, Oct 6), after those fixes

The same 208 sales, now filed more narrowly: Pets went from 11 sales to 3 (Cosequin, Woot's pet sale, Native Pet) and
Auto from 13 to 2. Result: **195 of 200**, none inconclusive. S-SRC, S-STORE, S-SHIP, S-OFFER and S-QUAL passed in
full.

| Test | What happened | Kind | Fix |
|---|---|---|---|
| S-END Woot's Amazon Essentials apparel discount; Woot's tools and kitchen discount (both Slickdeals) | The test read only Slickdeals' summary, which leaves out "Offer valid through October 13, 2026"; the editors' notes on the page say it, and Slomp's dates were right | Test bug (×2) | The test reads the editors' notes, and passes on the date the post states rather than on its exact wording |
| S-MANY Nutramax Cosequin supplements | The title says "Supplements", but the post prices one bottle | Slomp bug | A post whose text prices one item, with no sale words, "up to" or "extra" in its title, is one product |
| S-IND Kohl's today-only deals; Gap Factory clearance (both under Baby & Kids) | Neither post names any goods, so each counted for every department its store has; the judge chose Fashion (and Home for Kohl's) | Slomp bug (×2) | An event that names no goods counts for the store's main line: a department store's first two departments, another store's first. Hip2Save's own category feeds no longer count as naming goods |

### Run 3 (seed 3013, Oct 6), after those fixes

206 sales at 49 stores. Searches showed 1 (Baby & Kids) to 91 (Auto, Fashion and Sports) sales. Result: **197 of
200**, none inconclusive. S-SRC, S-END, S-SHIP, S-OFFER and S-QUAL passed in full.

| Test | What happened | Kind | Fix |
|---|---|---|---|
| S-STORE Crocs, "Up to 60% off" (Hip2Save) | The post sends you to "the official Crocs eBay Store"; Slomp showed it as a sale at Crocs. Its reader didn't take "official" before a name, nor a name in lower-then-capital letters (eBay), so the brand in the title won | Slomp bug | A store phrase may start "the official"; names like eBay and iHerb are read; a phrase naming a brand and a marketplace means the marketplace; the post's own "at …" outranks a brand the title names. Of the 206 sales, only this one changed store |
| S-MANY Toniebox Prime Big Deals at Amazon | dealnews files it as a sale: bundles of one audio player and its figures. The judge saw one product | Judgment call | None |
| S-IND Woot Prime Exclusive Deals (under Office) | The post's words name office goods among others; the judge chose Tech, Fashion and Home | Judgment call | None |

The judge also noted, beside its answers, that one sale's store was "DealNews": dealnews names itself as the retailer
of its own roundups ("The Best Amazon Prime Big Deal Days Deals"). Deal sites are no longer taken for a store, so that
roundup is now Amazon's (by its sale event). Looking at every store outside the registry then found one more slip, a
single office chair ("Welax S3 Ergonomic Office Chair: $45 OFF") taken for a sale: a post whose offer is only dollars
off, with no sale words or kinds of goods in its subject, is now one product.

### Run 4 (seed 4013, Oct 6), after all the fixes

205 sales at 47 stores (148 dealnews, 38 Hip2Save, 12 9to5Toys, 6 Slickdeals, 1 The Inventory; 48 with a code, 135
with an end). Result: **198 of 200**, none inconclusive. Every test passed except two industry calls:

| Test | What happened | Kind | Fix |
|---|---|---|---|
| S-IND Kohl's Deal Days (under Baby & Kids) | The post names baby clothing (Jumping Beans) among its brands; the judge chose Fashion, Home and Beauty | Judgment call | None |
| S-IND Woot Prime Exclusive Deals (under Office) | As in run 3: the post names a desk among its goods | Judgment call | None |

**The published site.** `python -m slomp.verify.site_check` now compares the sales too: built from the same data at the
same moment, the server's and the page's lists of sales matched in every field of every sale, with the same counts,
left-out reasons and store list, in 24 of 24 searches (seed 7, during run 1) and 30 of 30 (seed 11, on the final code).

## Against a manual search (Oct 13)

The runs above check what Slomp shows. This one asks what it misses. For the week of Oct 13–20, 2026, four searches
by hand looked for: online stores' sales, single-product online deals, Austin's weekly ads and restaurant promotions,
and regular deals in Austin, Houston and Dallas. Each finding was cross-checked: the company's own page, or two
independent dated sources. Two limits shaped the comparison:

- **Slomp's sources were out of reach from the session that ran it** (its network allowed none of them, nor the
  published site). So Slomp's side is the published site's build logs and the live runs above. The posts the manual
  search found on Slomp's own sources were run through Slomp's own feed parsers and filters offline, before and after
  this change ("replay").
- **The search tool allowed 200 searches per session turn**, shared by the four searches, so each one stopped short
  of its target: 3 sales verified both ways and 18 more from one source, 12 fresh single-product deals, 14 Austin
  weekly ads with in-window dates, 5 regular deals missing from the curated list.

Everything is in `docs/verification/manual-01.json`.

**What Slomp fetched.** The site build of Oct 13, 21:53 UTC, read 421 live ads at all 303 anchors (52,578 items,
9,202 deals), 142 sales at 42 online stores, 206 regular deals and 29 restaurant promotions. Online, it listed 10 Tech,
6 Sports, 28 Fashion, 23 Home, 7 Beauty, 5 Health, 11 Grocery, 12 Toys, 8 Baby & Kids, 2 Pets, 2 Automotive and 7
Office deals. Twelve company sites could not be read from GitHub's servers (a bot check on ten; two pages no longer
state their deals). The builds of Oct 8, 10 and 12 were alike.

**Accuracy.** The seven dealnews sales whose titles the manual search captured all went through Slomp's filters with
the right store, offer, code and end date: Wayfair's Holiday Deal Week (to Oct 18), Best Buy's Open-Box Outlet Event,
adidas' Fall Favorites (code FALL, to Oct 19), Michael Kors Outlet (EXTRA10, to Oct 15), Target's hair color and
bedding deals, and Wayfair's outdoor furniture. So did Hip2Save's Kohl's clearance post, with its GET20 code. With the
earlier runs' pass rates (98.4% for local and online deals, 97.5% for sales), what Slomp shows holds up. What it
misses is the larger gap.

**What Slomp misses, and why.**

| Area | Found by hand, not by Slomp | Cause | Changed |
|---|---|---|---|
| Sales | Samsung's monitor sale (dealnews): "up to $150" in instant credits | Only "$X off" was read as dollars off; the post's title wasn't captured, so this is the wording Slomp was tested on | Yes: "$X in instant credits", "$X instant savings" and "save up to $X" count |
| Sales | A code after a capitalised cue: "w/ Code", "Promo Code", "Use Code:" | The cue was read only in lower case. Slickdeals' and Hip2Save's titles capitalise it ("$5.98 w/ Code") | Yes. Capitals deal sites use for emphasis ("TODAY", "HOT") are still not codes |
| Sales | Lands' End (HAYRIDE50), Anthropologie, Abercrombie, Skechers | Reported only by CNN Underscored, AOL or the store itself, not by the deal sites Slomp reads | No: by design (README, Limits) |
| Sales | Nomad's 15% off for 9to5Toys readers | Nomad is not one of the 122 stores Slomp knows | No |
| Online | 9to5Toys deals whose title states the saving ("$119 (40% off)", "$20 (Save 46%)", "$243 … ($107 off)") | The parser read only "(Reg. $X)"; with no reference price a deal is never ranked | Yes. The 9to5Toys wording for a usual price ("normally fetches $37", "down from the usual $70") is read too |
| Online | Wrong prices from savings and order sizes | "$199 off" was read as a $19 price, "$45 OFF" as $4, "$1,100 under the Pro model" and "free shipping w/ $39" as prices. Of 1,315 titles in the recorded runs, 43 got a price that way, most of them store-wide sales the online list leaves out anyway | Yes: none of the 43 has a price now. A price in cents ("Only 49¢") is read too; the "Reg. $5" after it was taken instead |
| Online | Car gear and other goods filed wrongly or nowhere | Of the products the search found, dash cams were Tech only, a car air freshener and contact-lens solution were Grocery, and a winch and a USB-C power strip had no industry, so they were dropped. Checking around them found the same for OBD2 scanners and garage door openers | Yes |
| Online | Pets 2, Automotive 2, Health 5 | Mostly the sources: a lull after Prime Big Deal Days (Oct 6–7), most of the pet and auto posts the search found were store-wide sales, and DealCatcher, which had the most fresh pet and health items, states no reference price in its titles | No |
| Weekly ads | Whole Foods' and Natural Grocers' weekly deals | Every other retailer the search found with an Austin ad this week, from H-E-B to Hobby Lobby, is in Slomp's merchant list; these two are not | No |
| Weekly ads | Deals whose saving is stated only in the item's search record | 18,732 of 48,378 items (39%) had no item-search result on Oct 13, against 18–24% earlier in the week. New ads overlap last week's from Tuesday, and a search returns at most ~150 items per merchant. An item with no search result usually has no saving to show and is left out | No: needs live testing against Flipp (below) |
| Restaurant promotions | National Dessert Day offers (McAlister's, Jason's Deli, Portillo's) | Found only in freebie roundups, unverified. Slomp reads three feeds (dealnews Restaurants, two Slickdeals searches) | No |
| Regular deals | Santikos Super Tuesday ($5.99), Movie Tavern Value Tuesday ($6, DFW), ShowBiz discount Tuesdays, Denny's kids eat free (Tuesday, per its press release), Alamo Drafthouse BFD Tuesdays | Not in the curated list. Alamo's site turns Slomp away with a bot check (README) | No: each needs the company page's exact wording |

None of the curated regular deals the search checked (AMC, Regal, Cinemark, Star Cinema Grill, Luby's) was
outdated.

**Quality: one thing Slomp showed that it should not.** Hip2Save's "WOW! Over $68 of Beauty Products Just $4.52 After
CVS Rewards" was in Online › Beauty in runs 10–12 (Oct 5). It is a plan for buying several products in a store, paid back in
rewards to spend there later, not one product's online price. Every test passed it because the post was up. Posts
priced "after" a drugstore's rewards, and "over $X of" bundles, are now left out of the online list.

**Replay of the manual search's posts.** 20 posts whose titles were captured word for word (9 sales, 11 online
deals): Slomp kept 9 before this change and 12 after. Nothing it kept before is lost. The online posts were run on
their titles alone, since their feed descriptions weren't seen, so the Slickdeals ones show no reference price here.

**What would close the remaining gaps.**

- **Weekly ads.** Read the full item record for items no search returned. It costs one request per item: about 19,000
  on Oct 13, or 80 minutes at Flipp's 4 requests a second. A cap per build, with item records kept for the life of
  their ad, would spread the cost over the week.
- **Restaurant promotions.** Add a third source of dated restaurant posts, and check it the way the regular deals'
  roundups are checked.
- **Regular deals.** Add the five deals above from the companies' own pages, with their Texas branches.

### Again on Oct 14, after those fixes

**What the fixes changed in what Slomp fetched.** The four site builds of Oct 14 ran on them. The five builds of Oct
8–13 listed 118–140 online deals; these listed 146–156: Sports 3–6 became 13–15, Office 4–7 became 11, Tech 10–15
became 16–18 and Automotive 2–6 became 6–9. Pets (1–6) and Health (5–6) barely moved, and sales (138–152 at 40–43
stores) were as before. The builds' logs give counts, not the deals, so whether each added deal is right is for the
next live run's tests.

**A new gap the builds showed.** Two builds with the same 292 ads lacked an item-search result for 11,884 items
(10:22 UTC, its searches mostly from the cache) and 7,377 (15:52 UTC, most of them read again): 530 more deals in the
second. A search returns at most ~150 items per merchant. One read the day before, while last week's ad and this
week's both ran, had given most of them to last week's ad, and it stayed in the cache for a day after that ad ended.
A cached search used to be read again only when it lacked one of the merchant's ads altogether. It is now also read
again when it holds items that have ended since it was read.

**The second search.** It found 21 more dealnews sales at stores not searched before, 11 restaurant promotions
honored in Texas (5 with a dealnews or Slickdeals post) and 7 more restaurant posts that should not be shown. It also
found 12 regular deals missing from the curated list, 6 of them on the companies' own pages. All of it is in
`docs/verification/manual-02.json`.

**What held up.** Of the 21 sales replayed, Old Navy, J.Crew Factory (TREAT50), Staples' printing sale (38170),
Lowe's, Target's outdoor furniture, Woot's apparel sale, AliExpress and adidas came through with the end their posts
state. Slomp kept Dairy Queen's free Mini Blizzard (to Oct 19) and Cicis' $2.99 buffet. It rejected White Castle's and
MilkShake Factory's offers, since neither chain has a Texas branch on the map. It also rejected offers that had ended
(Dave's Hot Chicken, Jimmy John's) or start after the week (Krispy Kreme's Oct 30–31).

| Found by hand, not by Slomp | Cause | Changed |
|---|---|---|
| Old Navy's code, written 'Code "EXTRA"' | EXTRA is one of the capitals titles shout, so it was never taken for a code, even in quotes | Yes: a quoted code is a code |
| New Balance, "25% off $125" | The order size was dropped | Yes: "25% off $125+", on orders of $125+ |
| Macy's Biggest Fall Sale Event; Woot's Markdown Mania Clearance, Home & Kitchen and Fall Gardening sales | No industry: "biggest" and "mania" were not event words, "home & kitchen" and "gardening" not goods (dealnews' own category, not seen here, may have placed some) | Yes |
| KFC's buy one, get one free Zinger combo (Slickdeals) | A chain name under four letters was never matched in a title, so KFC's 225 mapped Texas branches matched nothing | Yes: an acronym in capitals ("KFC") is matched |
| A sale ending "through Sunday", "ends Monday!", "through Sunday, 10/19", "ends at 11:59pm PT on 10/19" | No end was read, so the sale was shown for 7 days after its post | Yes; "Monday through Friday" is still no end |
| MFAH's free Thursdays; Cowboy Chicken's kids eat free on Mondays | Not in the curated list | Yes: added, with phrases that name the day, so each build's read of the page confirms it |
| Kohl's 15% off for shoppers 60+ on Wednesdays (and military on Mondays); Kimbell's half-price exhibitions; Buffalo Wild Wings' BOGO days; Bush's Tender Tuesday; Main Event's kids eat free | Not in the curated list | No: Kohl's site turns automated readers away, Kimbell's evidence is a PDF, the Buffalo Wild Wings sentence names no day and its Tuesday terms conflict, Bush's states no price, and Main Event's Tuesday comes only from other sites |
| LEGO's double points and free set with $180; Ulta's "5 for $10" | Neither states a discount Slomp's sales can show | No |
| Del Taco's free cheesecake bites (Oct 14), shown to Oct 31 | The post's "Thru October 31" is about its other offers; dealnews' own end date, when its editors set one, comes first | No |
| Sales announced only by the store or other outlets (Columbia, REI Outlet, Pottery Barn, West Elm, Banana Republic Factory, eBay's HOSTING25) | Not on the deal sites Slomp reads | No: by design |

Two curated entries the search took for outdated are not: Main Event's Kids Bowl Free already ends Oct 31, and Dave &
Buster's page still has the words its entry looks for (every build reads it, and none reported a change). Others have
stopped being shown because their company page no longer states them: P.F. Chang's happy hour and Bryan Street
Tavern's Monday pizza in every build checked since Oct 8, and Fuzzy's two deals in some of them. They need checking by
hand.

**Replay.** 33 posts (21 sales and 12 restaurant posts): Slomp on main kept 18, and with this change 23. Nothing it
kept before is lost.

### A third time on Oct 15, after the second round's fixes

**A build on the merged fixes.** A site build started by hand on `main` (with the workflow's assistant setting) read
302 ads (7,848 deals, against 7,507–7,749 in the day's three scheduled builds), 164 sales at 45 stores (against
144–153) and 209 regular deals (against 207–208). Of the five regular deals the second round added, Cowboy Chicken's
page was read and confirmed. The MFAH's site turns GitHub's servers away with a bot check, so its free Thursdays show
on `slomp serve` but not on the published site. The build listed 134 online deals, against 152–155 earlier that day.
It is the one build that ran with the assistant setting, which skips sites whose robots.txt turns AI assistants away,
so the next scheduled builds are the ones to compare.

**How accurately Slomp reads an online deal.** The third search collected 79 single-product posts from Slomp's sources
(Oct 12–15: 33 from 9to5Toys, 15 dealnews, 12 Hip2Save, 12 The Inventory, 5 Slickdeals, 2 Ben's Bargains) with the
price each states and the price it is measured against. It also collected 10 posts that are not deals (a product
launch, a preorder, a store-wide event). Replayed through Slomp:

| | On main | With this change |
|---|---|---|
| Price and discount as the post states them | 13 | 20 |
| Price right, no discount found (never ranked) | 33 | 34 |
| Left out: no price or no industry | 33 | 25 |
| **A wrong price, or a discount more than 5 points off** | **0** | **0** |
| Not-a-deal posts shown | 0 of 10 | 0 of 10 |

Slomp did not show a wrong figure for any of the 79. What it misses are deals it can't read whole. Some misses
belong to the replay rather than the feed: the search index removes Slickdeals' prices from their titles, and the
replay saw only search snippets of the posts' bodies, where most posts state their regular price.

| Found by hand, not by Slomp | Cause | Changed |
|---|---|---|
| 9to5Toys titles that give only the saving: "AirPods Pro 3 currently $50 off at Amazon" ($199), "Mac Studio still $200 off" ($2,299) | No price in the title | Yes: the price from the post's first sentence ("down at $199"), the saving from the title; an "up to" saving gives none |
| The Inventory's "Spyder Golf Polo Just $8 on Amazon (60% Off)", "Zesty Paws Salmon Oil … $13.57 (20% Off)" | The title's percent was not read | Yes |
| A snow shovel, a Bluetti power station, squishy and potion kits, a travel router, Mac Studio and Mac mini | No industry | Yes |
| Salmon oil for dogs (under Grocery), CAP Barbell dumbbells (also under Fashion, for "cap") | Keyword collisions | Yes |
| Under Armour's codes: 'The coupon "OCT40" cuts an extra 40% off' | A code was read only after the word "code" | Yes |
| Woot's "Up to 75% Off Skechers Shoes + Free Shipping for Amazon Prime Members" (Hip2Save), filed as Amazon's | The Prime shipping line named the store | Yes: the post's "Hop over to Woot.com" decides |
| "Target Halloween Decor Sale" under Toys | The toys rule listed "Halloween decor" ahead of Home's | Yes: Home |
| "CVS Photo Custom Canvas Deal: 70% off + same-day pickup" | Not read as pickup only (it was left out anyway, with no industry) | Yes |
| ShowBiz's discount Tuesdays, Santikos' $5.99 Super Tuesday, Movie Tavern's Value Tuesday | Not in the curated list | Yes: added, each with the company page's sentence that names Tuesday |
| Buffalo Wild Wings' BOGO Thursdays, Denny's kids eat free, Main Event's kids eat free, Kohl's 60+ Wednesdays | Not in the curated list | No: Buffalo Wild Wings' page is about 640 days old and its Tuesday terms conflict, Denny's own pages disagree on the day, Main Event's Texas pages don't state it, and Kohl's sentence doesn't name Wednesday (its site also turns automated readers away) |

What held up besides: Woot's plush sale ($10 off $30+, PLUSHTEN, to Oct 21) and clothing sale, both Kohl's posts
(10HOME, to Oct 18), Target's extra 25% off toys (to Nov 14), and every restaurant post: Taco Bell's $4 Usual (Oct
13–19), Krispy Kreme's Lab Dozen (to Oct 15) and Pizza Hut's Haunt Box (to Nov 2). P.F. Chang's happy hour and Bryan
Street Tavern's Monday pizza, which builds have left out since Oct 8, are still offered per their sites; their
entries' wording needs updating by hand. Evidence is in `docs/verification/manual-03.json`.

### A fourth time on Oct 17, on new ground

This round looked where the first three had not: sales across the deal sites, single-product posts in the four
thinnest industries (Pets, Health, Automotive, Baby & Kids), the week's restaurant promotions, regular deals in San
Antonio, El Paso, Corpus Christi, Lubbock and Fort Worth, and weekly-ad retailers. No page could be opened from the
session that ran it, so the search saw result titles and the search tool's summaries. Ends and codes it reported
without quoting the post were left out of the replay, which therefore tests store, offer, price and industry. The
replay is now part of Slomp: `slomp replay posts.json` reads each post the way its site's feed carries it, through
Slomp's own parsers and filters (`slomp/verify/replay.py` lists the fields). On round 3's 113 posts it gives the
verdicts of the harness it replaces. Evidence is in `docs/verification/manual-04.json`.

**What Slomp fetched.** Six scheduled builds ran on `main` (the second round) from Oct 15, 20:25 UTC, to Oct 17,
01:22 UTC.

| | These builds | Before |
|---|---|---|
| Online deals | 124–141 | 146–156 on Oct 14, 152–155 early on Oct 15 |
| Sales at online stores | 156–170, at 39–44 stores | 144–153 |
| Regular deals; promotions | 208–209; 28–29 | 207–209; 27–29 |
| Weekly ads | 298–302 ads, 7,828–8,465 deals | 421 ads on Oct 13, during an overlap of two weeks' ads |
| Ad items with no item-search result | 22–24% | 39% on Oct 13 |

The second round changed online deals only by adding three Home keywords, which can only add deals, so the fall in
online deals came from what the feeds posted, not from the code. The share of ad items without a search result is
back to its usual level: the second round's re-read of searches that held an ended ad's items holds.

**Regular deals the published site has never shown.** Every build logs the evidence pages it could not read. Nine
sites have answered GitHub's servers with a bot check on every build since that log began on Oct 6: Cinemark, Regal,
AMC, Star Cinema Grill, the Modern, Goodwill Central Texas, the Mexic-Arte, the Health Museum and the Nasher. So has the
MFAH since it was added on Oct 14, and Mile High on the Cheap, a roundup, since Oct 11. A curated deal whose only
evidence is on those sites has no successful read on record, so the published site leaves it out: 13 entries,
among them Cinemark's Discount Tuesdays, Regal's Value Days (until Oct 10 the roundup stood for it), Star Cinema
Grill's Tuesdays, the Modern's free Fridays and half-price Sundays, four Goodwill days and four museums' free days.
`slomp serve`, run where those sites answer, can confirm them. AMC is not among the 13: its entry also cites two dated
articles on sites that answer. The way to bring the 13 back without going around a bot check is the same, a second
source on a site that answers; this round's searches ran out before it.

**How accurately Slomp reads a post.** Of the 41 single-product posts replayed (dealnews, DealCatcher, The Inventory,
9to5Toys, Hip2Save, Slickdeals), Slomp read no price more than $0.50 off what the post states, and it left out all 8
that are not single-product deals: Woot's store-wide sales, a 9to5Toys roundup, a "Save $8 When You Buy 2" drugstore
offer and a toilet-paper price "After CVS Rewards". It ranked none of the 33 real deals, on `main` or with this
change. 26 have no reference price in the words the search showed; in the feed, the post's body usually states one.
5 are The Inventory's titles that give only the saving ("40% Off", "$50 Off"), with the price in a body the search did
not show. 2 were over 72 hours old. Of the 28 sales and 7 restaurant posts, Slomp kept 16 sales and 4 promotions on
`main`, and 24 sales with this change. Every store it named was the post's (Banana Republic Factory's sale under
Banana Republic, which the store list counts as one store).

| Found by hand, not by Slomp | Cause | Changed |
|---|---|---|
| The Inventory's titles that give only the saving: "12-in-1 Air Fryer Toaster Oven Combo $30 Off on Amazon" (round 3's evidence), "Extra Wide Inflatable SUP 40% Off", "98-Inch TCL Mini-LED 4K TV Deal: Save $1,802" | The parser took a price only from the title or from "is now $X (N% off)"; "The current Amazon price of $129.98 represents a $30 discount from the $159.99 regular price" was read as no price | Yes: two amounts in the post that agree with the title's saving are its price and the price it was cut from, and "the $159.99 regular price" is read as a regular price. The air fryer now reads $129.98 against $159.99. Amounts that don't agree give no price |
| Woot's workwear (Carhartt, Dickies), pest-prevention and wellness-aisle sales; Target's oral care deals; Apple Outlet deals at Best Buy | No industry: the words name no goods the rules knew, and the stores sell everything | Yes |
| PUMA's Stock Up sale (9to5Toys, code STOCKUP), Wilson's fall sale, Dearfoams' friends and family sale | Stores Slomp did not know | Yes: added as brands, so their names in a title alone don't place a sale |
| A cold-therapy knee ice machine; accounting software | No industry | Yes. An ice maker, and a cutter sold "with design software", still have none |
| Taco Bell's $4 Paris Hilton Usual (Oct 20–26) and $1 Usual drop (Oct 20), Olive Garden's pasta bowl, Wendy's Boo Books | No dealnews or Slickdeals post found; Taco Bell's previous Usual week had both | No: Slomp reads the deal sites |
| Shake Shack's free burger and Taco Bell's Kevin Hart Usual (dealnews) shown to Oct 24, past their Oct 18 and Oct 19 ends | The replay saw neither post's body nor dealnews' own end date | No: the feed carries both |
| 15 regular deals: the Witte, the San Antonio Museum of Art, the McNay (Thursday nights, first Sundays), the Briscoe and the DoSeum in San Antonio; the Fort Worth Zoo's Half-Price Wednesdays and the Kimbell's half-price exhibitions (Tuesdays, Friday evenings); the Art Museum of South Texas's four monthly free days (Corpus Christi); Chimy's happy hour in Lubbock | Not in the curated list. San Antonio had no regular deal of its own | Yes, each with its page's own words. Eight of those phrases came back from the search without quotation marks, so the next builds' logs will show whether the pages carry them word for word; a phrase not found hides the deal |
| P.F. Chang's happy hour, left out since Oct 8 | The page now reads "$6 Beer & Wine \| $9 Cocktails & Sake" and gives no national hours | Yes: the new prices; hours vary by location |
| Bryan Street Tavern's Monday half-price pizza, left out since Oct 8 | Its heading moved from the home page to the specials page | Yes: the specials page |
| Fuzzy's Taco Shop's taco Tuesday and happy hour, hidden since Oct 16 | The home page no longer says either. The only other wording is on a Katy store's page written before it opened and on out-of-state pages about 20 months old | No: checked again next time |
| Jim's kids eat free (San Antonio), Tiago's kids eat free | Jim's has many branches and the search gave no list of their addresses; Tiago's home page shows signs of being hijacked | No |

**H-E-B in Austin.** H-E-B's weekly-ad pages give a sale price ("$X each", with a price per pound or ounce) and
seldom a regular price (1 of the 11 items the search saw). Its savings are separate offers: digital coupons ("$1 off
Clorox Bleach, 77 - 81 oz."), Combo Loco ("buy this, get that free") and Meal Deals, which state no amount. Slomp
leaves out an ad price with no saving by design, so most H-E-B items are left out, which is why Austin shows few
H-E-B deals. The site build's per-merchant log, on this branch, will show how H-E-B's items fare once it runs on
`main`. The search found no other retailer with a Texas weekly ad missing from Slomp's merchant list beyond the
first round's Whole Foods and Natural Grocers.

**Next time.** After a merge: the next build's per-merchant lines for H-E-B, and the evidence lines for the 15 new
regular deals. A second, readable source for each regular deal whose only page turns GitHub's servers away. Fuzzy's
current wording.

### A fifth time on Oct 20

This round followed up the fourth's open items and went further: second sources, on sites that answer GitHub's
servers, for the regular deals whose own pages don't; regular deals in nine more cities; the week's restaurant
promotions; single-product posts in the six industries the fourth round left, after each site's wording for a
reference price; and sales, after the posts' own sentences for codes and end dates. Evidence is in
`docs/verification/manual-05.json`.

**What Slomp fetched.** Eleven scheduled builds ran on `main` (still the second round) from Oct 17, 09:30 UTC, to Oct
20, 01:56 UTC: 120–141 online deals, 138–160 sales at 35–44 stores, 208–210 regular deals, 25–29 promotions and
289–309 weekly ads with 7,594–8,517 deals. Ad items with no item-search result fell to 17–19% from Oct 18 (23–25%
before), the lowest yet. The evidence lines showed three changes:

- The MFAH's robots.txt has turned AI assistants away since Oct 18. The registry is kept up with an AI assistant's
  help, so Slomp no longer reads that page at all; the MFAH's free Thursdays need a source elsewhere.
- Fuzzy's Taco Shop's evidence comes and goes. Its home page serves two versions, and 5 of the 13 builds from Oct 16
  evening on found neither phrase. The fourth round called both deals hidden since Oct 16; they were hidden in those
  five builds.
- Bryan Street Tavern's home page carries its Monday heading again since Oct 19; this branch reads it from the
  specials page in any case.

**Accuracy.** Replayed on `main` and with this change:

| | Posts | Kept on `main` | With this change |
|---|---|---|---|
| Online, the titles alone | 46 | 2 ranked | 3 |
| Online, with the snippets the search gave as page text | 46 | 4 | 8 |
| Sales | 25 | 12 | 17 |
| Restaurant promotions | 10 | 9 | 9 |

Where the search caught a post's own sentence for a code or an end, Slomp read it: ASICS (FIT40, ends Oct 20), Hurley
at Woot (ends Oct 21), Under Armour (OCT40) and PUMA (STOCKUP). Every kept sale named the right store but one:
Hip2Save's "Up to 75% Off adidas Shoes" is at eBay, and with no body to read (the post says where) the title's brand
was taken. One online price was wrong: "Originally $2,000 Samsung 4K 3D Odyssey gaming monitor is down to $900 today"
read at $2,000. It had no reference price, so it was never shown. Every other price was within $0.52 of the post's
(a costume "Under $26" read at $26). Last year's posts carry dates with no year ("thru October 26"); Slomp reads such
a date in its post's year, so a 2025 post is over, not this week's. On every earlier round's posts, nothing Slomp kept
is lost and no kept price changes.

| Found by hand, not by Slomp | Cause | Changed |
|---|---|---|
| "Originally $2,000 … down to $900 today" (9to5Toys) | The title's first amount was taken | Yes: an amount after "originally", "regularly", "was", "reg." or "list" is not the deal's price |
| dealnews' "$12 under list price" | Not read | Yes, as a list price |
| The Inventory's "Now $229.99 on Amazon—$20 off" under a "$20 Off" title | The fourth round's reading needed two amounts | Yes: one amount beside the title's saving is the price |
| Woot's auto parts and accessories, auto deals, sports overstock, and gloves and safety wear sales | No industry | Yes |
| A ride-on car, an RC walker, a cracker tray, an ice-maker filter, a magnifier, pub mix | No industry | Yes |
| Free Saturday mornings at the Museum of South Texas History (Edinburg); the Tyler Museum of Art's first Fridays and Family Days; Casa do Brasil's happy hour and kids eat free (Waco); Twin Peaks' happy hours in McAllen, Beaumont and El Paso | Not in the curated list. The Rio Grande Valley, Tyler, Waco, Beaumont and El Paso had none | Yes: 8 entries, each with its page's own words (most came back unquoted, so the builds will show whether the pages carry them word for word) |
| Cinergy's Discount Tuesdays (Amarillo, Midland, Odessa, Copperas Cove); Alamo Drafthouse's BFD Tuesdays (Laredo); Jorge's, the TAMIU planetarium, Urban Air | No branch addresses found for Cinergy; Alamo's site turns Slomp's reader away; the rest not confirmed | No |
| Regal Value Days, off the published site since Oct 11 | Regal's page and the roundup that stood for it answer GitHub's servers with a bot check | Yes: Senior Daily's Regal page (updated Sep 28) as a second source |
| The other 12 regular deals behind bot checks (Cinemark, Star Cinema Grill, the Modern's two, Goodwill Central Texas's four, the Mexic-Arte, the Health Museum, the Nasher, the MFAH) | No readable, dated page states them with their day: KXAN's Goodwill story lists the sales without days, the Modern's mentions are too old, the Cinemark ones cover several chains at once | No |
| Taco Bell's $4 Paris Hilton Usual (Oct 20–26), Applebee's Hallowings Bucket (Oct 25–31) | No dealnews or Slickdeals post yet | No: Slomp reads the deal sites |

**Next time.** After a merge: H-E-B's lines in the build's per-merchant log, and the evidence lines for the 23
regular deals the fourth and fifth rounds added. A source for the 12 regular deals still behind bot checks.

### A sixth time on Oct 25: what holds for places no search has seen

This round asked a second question besides what Slomp misses: whether its fixes would hold for stores, brands and
places that no search has seen. Every fix of the five earlier rounds was looked at again. Those that named one store,
brand or place were taken out, and each was replaced by a rule that finds such things from what Slomp reads. Evidence
is in `docs/verification/manual-06.json`.

**What Slomp fetched.** Twenty scheduled builds ran on `main` (still the second round) from Oct 20, 10:12 UTC, to Oct
25, 01:20 UTC: 114–172 online deals (114–117 in the last two), 127–200 sales at 33–76 stores (the most on Oct 23),
207–213 regular deals, 24–28 promotions, and 314–410 weekly ads with 9,044–10,306 deals. Ad items with no item-search
result rose to 37–47% (17,482–21,438 of 45,801–47,493 items), from 17–19% the week before. The holiday ads came out
and the ads grew from about 33,000 items to 46,000. A merchant search returns at most about 150 items, so a bigger ad
keeps most of its items without a result however many ZIPs are tried. The evidence lines changed in four ways:

- Goodwill Central Texas's four pages, the Mexic-Arte and the Health Museum were read again from Oct 24 (regular
  deals 207 → 213).
- Uchi's five pages, Chuck E. Cheese's two, Ross and the Contemporary Austin have answered with a bot check since Oct
  22. Their deals stand on the last good read, for a week.
- Fuzzy's Taco Shop's home page has not carried one of its two deals' phrases since Oct 22.
- P.F. Chang's and Bryan Street Tavern's lines are `main`'s old wording and address; this branch has the new.

**What was taken out.**

| An earlier round added | Taken out because | What finds such things now |
|---|---|---|
| 28 regular deals at named places: the MFAH, the Witte, SAMA, the McNay (2), the Briscoe, the DoSeum, the Fort Worth Zoo, the Kimbell (2), the Art Museum of South Texas (4), the Museum of South Texas History, the Tyler Museum of Art (2), Chimy's in Lubbock (2), Casa do Brasil (2), Twin Peaks (3), Cowboy Chicken, Showbiz, Santikos, Movie Tavern | Each was one place a search found | The weekday roundups, for chains. For a place no roundup lists, nothing yet (below) |
| PUMA, Wilson and Dearfoams as stores | Three stores a search found | A store the post names (DESIGN-online-stores.md 4.3) |
| Brands in the industry rules: Zesty Paws, Bluetti, EcoFlow, Jackery, Carhartt, Dickies, Utz, Opti-Free, Biotrue | Brands, not kinds of goods | Words learned from labelled items and posts (DESIGN.md 4.4) |
| One sale's wording: Apple "Outlet", "sports overstock", "wellness aisle", "auto deals" | One post's words | A sale named after a department takes the department's industry from the industry list's own names; learned words, kept to what the store sells |

Kept: the kinds of goods the rules lacked (ice makers, dash cams, ride-ons, RC toys, serving trays, magnifiers, power
stations, lens solution, workwear), the readers of prices, codes and dates, and the updates to three entries whose
own pages changed (P.F. Chang's, Bryan Street Tavern, Regal). Merged, this takes Cowboy Chicken's Monday kids eat free
off the published site. The MFAH's free Thursdays have not been shown since Oct 18.

**What was added, all general.**

- **Learned words.** Every build keeps the words of the items and posts that carry their source's own label: Flipp's
  taxonomy on ad items, a specialty store's line, dealnews' category on its posts. A word in 8 or more such examples,
  90% of them one industry, files what no rule does. For a store, it is kept to what the store sells.
- **Department sales and several departments.** A sale named after a department takes that industry ("Protein &
  Wellness Stock-Up Sale at Woot" → Health). A sale that names several kinds of goods counts for each ("Up to 85% Off
  Apparel, Toys" at Kohl's was Toys only).
- **Unknown stores.** A store is named from the post itself ("PUMA's Stock Up sale", "Wilson Fall Sale", "at
  Dearfoams") when the post links to the store's own site or says it ships. Hip2Save's and 9to5Toys' links are now
  kept with each post.
- **Word searches for ad items.** Ad items that no merchant search returned are searched for by the words of their own
  names, up to 160 searches a build.
- **Roundup pages that moved.** When a weekday roundup page is stale, unreadable or nearly empty, the site's sitemaps
  (listed in its robots.txt) give the current page.
- **The build log.** It now shows what the learned words filed, the word searches, roundup pages that moved or went
  stale, and the posts left out by reason. For the reasons that can hide a real deal (no industry, no price, store not
  identified, no shipping stated) it names a few of the posts.
- **Two misfilings found by checking the rules against dealnews' own category table.** Air conditioners were filed
  under Beauty ("conditioner"); power stations went under Home, where dealnews files them under Tech.
- **One misreading found by giving dealnews titles their shipping clause.** "+ free shipping w/ Passport membership"
  made 1-800-Flowers' Friends & Family Event "a membership".

**Accuracy.** The sample was taken without targeting: 58 online posts on all seven sites (52 single products, 6 not
deals), 27 sales and 12 restaurant promotions for Halloween week. Search never showed a dealnews category, so the
replay has none, and dealnews titles carry the shipping clause their URL shows. Replayed on `main` and with this
change:

| | Posts | Kept on `main` | With this change |
|---|---|---|---|
| Online | 58 | 7 ranked | 8 |
| Sales | 27 | 19 | 21 |
| Restaurant promotions (9 posts; URL slugs and a site banner left out) | 9 | 6 | 6 |

The 6 posts that are not deals were all left out. No price was read more than $0.50 from the post's, and that one
was dealnews' own update ("The price has changed to $9.99"). Seven single products have no industry by any rule: a
storage shed, a kneeling pad, touch-screen gloves, a salt and pepper shaker, cooking spoons, a chef's knife and a
sweeper kit. Learned words are meant for exactly these, since Flipp labels such goods every week, but this session
can't read the builds' labelled items to show it. Against `main`, today's sample gains:

- 1-800-Flowers' Friends & Family Event.
- Woot's Protein & Wellness sale.
- The Inventory's toddler costume, priced from the percent in its title (the third round's reading).
- Kohl's clearance, now under Fashion as well as Toys.

On every earlier round's posts, against this branch before the change: sales 75 → 70, online 36 → 35, promotions
unchanged. Every post lost was one of the items taken out:

- dealnews' Wilson and Dearfoams sales: dealnews files them under its own categories, which the replay lacks.
- 9to5Toys' Bluetti station and Best Buy's Apple Outlet deals: these need learned words.
- 9to5Toys' PUMA sale (in two rounds): it needs the post's link to puma.com, which the search never showed.

Target's Halloween costumes and decor sale is now under Home as well as Toys.

**Regular deals.** Of 12 roundup offers checked against the chains' own pages, 6 match, 3 don't and 3 couldn't be
confirmed:

- Ruby Tuesday's $6.99 burger ended Oct 13 by the chain's page, and both roundups still list it.
- EatDrinkDeals gives Buffalo Wild Wings' second order free where the chain now says 50% off.

Slomp takes a roundup modified within 45 days at its word; only the verification harness checks the chains' pages.
EatDrinkDeals' Tuesday and Wednesday pages have moved, while the old addresses Slomp reads keep a 2017 page. That
leaves those two days to The Krazy Coupon Lady alone. The new sitemap lookup is meant for this.

The search also recorded 48 pages that list regular deals at local places by city: Houston's museum district pages,
6AM City's guides for Austin, Dallas, Fort Worth and San Antonio, DFWChild's kids eat free by day, and KERA's and 360
West's free museum days. They are what would find a new place's regular deal, but no reader for them exists yet. It
would need to place a local business on the map; the registry already geocodes a street address through the Census
geocoder.

**Next time.** After a merge, the build log's new lines:

- What the learned words filed: none on the first build, since it learns from nothing.
- The word searches and the share of ad items without a search result.
- Whether EatDrinkDeals' Tuesday and Wednesday pages are found.
- The posts left out, read in place of a blind search.

### A week of builds on Nov 9–16: what their own logs showed

This round had no manual search. The sixth round made every build say what it left out, so the week's twenty
scheduled builds (runs 128–147, all on `main` at `ca21382`) were read instead: four lines of each log, and the posts
and ad items they name. This session's environment still can't reach a deal source or the published site, so
nothing below was checked against a live page.

**What Slomp fetched.** On Nov 16 (run 147): 9 of 10 sources read; about 300 weekly ads; 182 sales at 74 online
stores; 199 regular deals; 22 promotions. Of 41,637 ad items, 7,792 (18.7%) had no item-search result, after 363
merchant searches and 160 word searches that found 4,384 items; the week before the word searches it was 37–47%.
The learned words stood at 1,061, from 16,864 labelled items and posts, and filed 442 ad deals, 2 online deals and
no sales.

**Stores' own websites never caught up.** The map gave 4,496–4,505 Texas shops with a website, on 2,325–2,335
sites. Every build spent all 600 of its reads, and the sites waiting went from 1,078 on the first scheduled build
to 352 and then 256 on the last build before Nov 16, never to none: most reads went to asking again the sites that had already failed (a bot check, robots.txt, a dead address,
a closed product listing) and to the shop platforms' daily product pages. On Nov 16 the first week's records, all
kept for seven days, expired together: sites known fell from 2,069 to 1,268 and their deals from 1,971 at 219 sites
to 1,386 at 149. The reads also held most of the build's connections, and builds took 7 to 21 minutes.
*Fixed:* what a site said is remembered, failures included; reads go to products first, then new sites, then
second looks; a store waiting its turn keeps its last deals; lifetimes are spread (DESIGN.md 13).

**Savings stated only in words: 2,661 ad items in one build.** The log names items left out as "no saving stated"
whose own words state one: H-E-B 466, Dollar General 419, CVS 407, Lowe's 306, Kroger 266, Brookshire's 198,
Walgreens 184. Across the week the logs printed 183 distinct samples. Read by their wording, never by the store:

| Kind of wording | From the logs | Now |
|---|---|---|
| A saving beside the price | "Save $250", "You save 25.00", "250.00 OFF REG. PRICE", "Sale! 50¢ OFF" | read |
| A ceiling | "SAVE up to $2 per lb.", "SAVE UP TO $7.00", "Save up to $30" | read as "up to" |
| A coupon's amount | "with $3 OFF Smart Coupon", "$4 DG DIGITAL COUPON", "$4.99-1.00 Digital Coupon", "Digital Coupon - $1.00" | read |
| The figure where the price goes | "INSTANTLY SAVE [$1] WHEN YOU BUY 2", "SAVE [$2] DG DIGITAL COUPON" | read as a saving |
| Another store's price | "Depart. store value 65.00", "THEIRS $8.99" | read (list basis) |
| A percent for a quantity | "10% OFF When You Buy 6 or More", "SAVE 10% WHEN YOU BUY SIX OR MORE" | read |
| For several items | "SAVE $60 When You Buy 6", "Buy 2 Get $12.00 Off", "$7 off 2 online coupon" | shared among them |
| Buy and get | "BUY ONE AND GET ONE FREE", "BUY TWO AND GET ONE FREE", "BUY 1 GET FREE 1" | read |

The old rule took a coupon off the printed price ("$8.95 with $1 OFF coupon" as $7.95). The same store's ad prints
"$1.25 with $3 OFF Smart Coupon", so the printed price is the price with the coupon, and the rule was turned round.
Left unread on purpose (about half the samples): a coupon with no amount ("FINAL PRICE WITH COUPON", "/EA With
Digital Coupon"), a saving on an order ("Save $10 when you spend $40"), rewards, a different item that comes free
(H-E-B's "Buy X get Y Free! with yellow coupon"), "BUY 2 GET FREE" with no count, and banner percents ("Up to 50% Off
Kitchen Appliances + Extra 10% Off* with coupon"). Replayed on the 183 samples as the log gives them (the words
joined, not the fields they came in), 66 now state a saving. Ten more are Dollar General's "SAVE ... DG DIGITAL
COUPON" with the figure where the price goes; they are read when "SAVE" is the text before the price, which the
log's joined words can't show.

**Sales with no store: 22 a build, 10 different titles in the week.** Nine lead with the offer and name the store
after it: "Up to 70% Off Comfrt Early Black Friday Sale", "Buy 1, Get 1 FREE Comfrt Hoodies & Sweatpants", "*Rare*
BOGO Free Charlotte Tilbury Makeup Sale + Free Shipping", "Today ONLY: Up to 80% Off 32 Degrees Clothes + Free
Shipping", Slickdeals' "Barnes & Noble Offer: ...". *Fixed* for a post that links to a website of that name or whose
words send the reader there (DESIGN-online-stores.md 4.3). The log gives only titles, so whether these posts carry
such a link or such words is not known; the log now says, for each post still left out, what it had to go on.

**Online posts with no industry: 21 different titles, all Slickdeals.** Charging cables, a mesh router, retro game
handhelds, home batteries, security software, tracker tags, a stair stepper, a grip strengthener, epoxy, a propane
gauge, a fuel pump. *Fixed* by kinds of goods and, where no rule names the goods, by the words of how a gadget
connects and what it holds (DESIGN.md 4.4): 20 of the 21 now have an industry. The one left is a streaming
subscription, which is no industry's goods.

**Not done.** A reader for the item that comes free with another (it needs a way to show two items as one offer).
The Inventory's posts with no price in the title or the text. The 48 pages that list regular deals by city.

**Next time.** After a merge, the build log's lines to read:

- Stores' own sites: "wait for a later build" should fall to none within a few builds and stay there.
- Ad items left out with a saving's words: fewer, and what kinds remain.
- "store not identified": the evidence each post had, to see whether links or the post's words would name it.
- "no industry": what the learned words know of each title.

### A seventh time on Nov 22: Black Friday week

Five days before Black Friday the question was whether Slomp finds the week's deals. A search by hand covered every
category; its findings were compared with the build published that morning and with the posts Slomp's own sources
carried that day; the filters were then changed by general rules and tested on the day's posts, live, and on the
page. Evidence is in `docs/verification/manual-07.json`.

**The search by hand.** Seven slices (big-box and department stores; tech, office and home; fashion, sports, beauty
and health; toys, baby, pets, auto and grocery; dining and entertainment; single products; Texas weekly ads), 2026
only, each finding from the store's own page or two dated sources where one could be had, deal-site titles word for
word. It returned 239 findings: 106 sales and events, 84 single products, 29 restaurant offers and 20 weekly ads; 49
on a store's own page, 63 on two sources, 127 on one. Three limits apply. The allowance of 200 web searches ran
out, so second-pass checks were cut short in every slice and **entertainment was not searched** (one finding). No
page could be opened (store and news sites are outside the session's network), so every quote is a search result's
wording. And findings are matched to Slomp by store and event, so one card counts for each wave of a store's event.

**What Slomp showed.** The build published at 06:41 UTC had 187 sales at 58 stores, 112 of them named for Black
Friday or Cyber Monday at 44 stores. It had no Black Friday card for Walmart, Target, Kohl's, JCPenney, Nordstrom,
Belk, Staples, CVS, Walgreens or HP, although its own sources carried a post for each. Of 225 posts naming Black
Friday or Cyber Monday on the feeds it reads, 135 were shown. Weekly ads were not the gap: Flipp listed 56 ads for
Austin and 78 for Houston, among them Target's week-long circular (Nov 22–29), Home Depot's "BLACK FRIDAY DEALS",
JCPenney's "Black Friday Deals", Academy's "Black Friday Preview" (Nov 26–28) and H-E-B's, Kroger's and Randalls'
Thanksgiving ads, and 17 of the 20 ads found by hand are read from there.

**Why posts were dropped, and the rule for each.** None of the rules names a store, a brand or a place.

| What happened | Rule now |
| --- | --- |
| The biggest events are announced with no percentage ("Kohl's Black Friday Sale Starts at 12am CT!", "Want a Peek at Walmart's Black Friday Deals? Get Ready to Shop on 11/23!"), and a sale had to state a discount | A store's own event named for a day of the calendar (`slomp/days.py`) is listed without one, marked "Sale event", after every sale that states a discount, and gives way to that store's sale for the same day that does state one |
| Hip2Save puts the offer after the sale's name ("Nordstrom Black Friday Sale is LIVE \| Up to 75% Off ...", "Target's Black Friday Deals Start 11/22 (50% Off Thousands of Gifts!)"), where Slomp dropped it as an aside | When the title names a sale and states no offer before the aside, the aside is read; when it states none at all, the post's own sentence sending the reader to the store is read and quoted. A plain percent found this way is shown as the most the sale gives |
| "Belk Black Friday Sale", posted Nov 14 with no end, was hidden after 7 days, on Nov 21 | A sale named for a day not yet past lasts through that day when no end is stated. A wave before it ("Early", "Pre-", "Preview", "Countdown") keeps the 7 days |
| "Samsung Black Friday Sale 2026: Up to 36% off + trade-in offers" was left out as a trade-in | Once the offer is stated, what follows a plus comes with the sale and is not what is on sale |
| "Deals Start 11/22", "Shop on 11/23", "Starts at 12am CT", "Deals End TONIGHT" and "Last Day!" were not read | Read from the title |
| Names kept the headline's status ("Black Friday Sale is Live: FREE Poinsettias, Offers, Trees & More") | The sale is named before the words that say how it stands |
| "FREE Poinsettias, BOGO Offers, 70% Off Trees & More" was shown as 70% off | In a list of highlights, a percent that is not the first item is one item's: "up to" |
| The Inventory's single products ("Glitzhome 18\" Frosty Santa: 60% Off Modern Holiday Decor") were shown as sales at a firm 60%, two of them among the home page's biggest deals | A post with no sale word that prices one thing ("now $38.80 at Belk") is one product |
| "Target's Black Friday Deals Start 11/22" was in none of the category feeds Slomp reads | Hip2Save's own front page is read too (two pages: one post in nine is in no category feed) |
| dealnews' robots.txt asks for `Crawl-delay: 2`; Slomp asked once a second | One request every 2 seconds |
| "Arby's Delivery: Free all month" ranked on the home page as a free item | Free delivery is not something free |

One thing the page check cannot do was measured: the pages of three dealnews sales that had ended by their own dates
(adidas, Target, Best Buy) were still up and unmarked, so reading a post's page again does not tell a live undated
sale from an ended one. That is why the wave before a day is not carried through it.

**On the day's posts.** The filters before and after, on the same 3,171 posts: 203 → 249 sales (before duplicates
are merged), 50 newly kept and 4 no longer kept (the three single products and a sale whose last day was Nov 21).
Posts naming Black Friday or Cyber Monday that are shown: 135 → 174 of 225; the rest ended (14), are waves before
the day with no end (9), state no discount and are no store's event (7), name no store Slomp can tell (6), are
subscriptions, gift cards and digital goods (10), or fall to five other rules (one product, a roundup, over 30 days
old, no word that the store ships).

**Live.** The real pipeline, through Slomp's own client with the assistant setting on: 140 feeds (9to5Toys skipped,
its robots.txt turns AI assistants away; Ben's Bargains answered 403), every kept sale's page read again, 196
requests to dealnews at one every 2 seconds, 390 seconds for the first full read (two shorter runs followed as the
rules were finished; the figures are the last one's). It kept **211 sales at 72 stores** (187 at 58 that
morning), 139 of them named for Black Friday or Cyber Monday at 63 stores (112 at 44). Nineteen stores gained a
Black Friday card and none lost one: Walmart, Target, Kohl's, JCPenney, Nordstrom, Belk, Staples, CVS, Walgreens, HP,
Academy, Bath & Body Works, Crocs, Under Armour, Northern Tool, Herman Miller, Michael Kors, Spanx and Comfrt. Six
are events with no discount stated (Walmart from Nov 23, Kohl's and CVS from Nov 22, Bath & Body Works, Northern
Tool, Spanx); six took their offer from the post's own sentence; 44 undated sales are shown through Black Friday.

**On the page.** The site's files were built from that run and opened in a browser: a search for Austin shows 210
sales at 72 stores on the Sales tab (2,621 deals near the city, 112 regular deals, 109 online deals), with no page
error; an event's card reads "Sale event, no discount stated", and its details "No end date given. It is named for
Black Friday, so Slomp shows it through Fri, Nov 27." engine.js and the server pick the same sales in the same order
at five moments from Nov 22 to Dec 2 (207, 176, 139, 98 and 26 sales).

**Earlier rounds.** The 421 posts recorded in rounds 1–6, replayed before and after: 156 kept before, 157 after,
none lost. The new one is "Lowe's Halloween Clearance" of round 3, a store's event named for a day. 286 unit tests
pass (274 before).

**The 106 sales and events found by hand.** 35 were shown that morning and 9 more are found now. 29 were on none of
Slomp's sources that day (Five Below, Dollar General, Sonos, Crate & Barrel, PlayStation Direct, Discount Tire, tire
rebates, baby-gear brands). 9 are on its sources and still not shown: Costco (its one post is 25 days old and its
title puts no store's name before "Black Friday Savings"), Ulta (its early wave ended and the main event had no
post), Cabela's and Bass Pro (a title naming two stores names neither to Slomp), the early waves of DSW and Carter's,
and digital game sales, which the Sales tab leaves out by design. 8 are later waves with no post yet (Cyber Monday),
8 are giveaways and doorbusters at the store's door, and 8 are memberships, store cards, gift cards and rebates.

**Still missed.**

- **Restaurants.** None of the ten Black Friday week offers found by hand (Chipotle's buy-one-get-one on Nov 25,
  Moe's on Nov 27–29, Whataburger's on Nov 25–30, 7-Eleven's pizza, Arby's fries) was on the three feeds promotions
  are read from, and Hip2Save has no readable restaurant feed. Twelve of the 29 dining findings are gift-card bonuses
  ("$15 bonus card with $50 in gift cards") and seven are priced holiday meals; Slomp leaves both out by design.
- **Single products.** 4 of 84 are shown, 22 are on Slomp's sources with no price to compare (so never ranked), and
  58 are on none: most were posted by 9to5Toys, which Slomp does not read when run by an AI assistant.
- **Entertainment** was not searched, and the search by hand should be run again with pages it can open.

**The second pass, the same day.** The first pass's 200 searches ran out, so entertainment and the second checks of
every slice were searched again with a fixed share of the allowance each: 191 searches, 164 findings (30
entertainment, 55 sales, 72 single products, 7 restaurant and store offers; 23 on a store's own page, 23 on two
sources, 118 on one). Again no page could be opened. Its findings were compared with the build published at 08:21
UTC, which already had the rules above, and with a fresh read of the feeds. They are in the same file, under
`second_pass`.

- **Entertainment.** Of 30 offers, 15 are subscriptions (Paramount+ at $2.99 a month, Prime Video channels "up to
  79% off", Apple TV, STARZ, PlayStation Plus, Audible), 5 are gift cards and one is digital games: Slomp leaves all
  21 out by design, and reads none of dealnews' streaming, movie-ticket or gift-card categories. Eight are passes,
  tickets and memberships at venues (Six Flags' 2027 Silver Pass at $69, SeaWorld San Antonio "up to 55% off", the
  San Antonio and Fort Worth zoos, Meow Wolf), which no deal site Slomp reads had posted. One is a dated offer at a
  chain Slomp lists regular deals for (Cinemark's $5 Holiday Movie Clubhouse tickets on Saturdays and Mondays, Nov
  28 to Dec 14). Nothing here is a miss of the filters; whether Slomp should list subscriptions and passes is its
  owner's decision.
- **Restaurants.** 7-Eleven's Black Friday pizza was confirmed by a second dated source, with a Cyber Monday code
  beside it. The Black Friday offers recorded for Moe's, Arby's and Whataburger each rest on one 2026 roundup, not
  two sources as first counted, and the Torchy's card may be the 2025 release's. No 2026 offer was found for 13
  other chains.
- **Sales.** 27 of 55 were shown that morning. Ulta's main event was posted after that build and is kept now.
  Fifteen were on none of Slomp's sources (Sephora, Microsoft Store, Google Store, West Elm, Peloton).
- **Single products.** 4 of 72 are shown, 16 are on Slomp's sources with no price to compare, 52 on none.

One thing the comparison showed was wrong, and it is general:

| What happened | Rule now |
| --- | --- |
| "Costco Black Friday Appliances Deals: Up to $1,100 off" was on dealnews and not among the posts Slomp read: it was on the second page of Costco's feed. Measured: Macy's 20 posts on dealnews spanned 1.9 days and the 19 behind them held ten Black Friday sales still running; Hip2Save's 100 posts for women spanned 2.5 days. A sale that leaves a feed's first page vanished from Slomp at the next build, still running (Michael Kors' did between two reads that day) | Every dealnews and Hip2Save feed is read on while a page comes back full and still holds a post from the last 30 days, at most two pages further (DESIGN-online-stores.md 2.2) |

The pass also met five live sales left out as "store not identified" though the post said where to go ("Stanley 1913
Black Friday Sale", Gerber Childrenswear, Minky Couture, Nutrafol, Filter King). The build's own log had shown the
same that morning and the rules for it were already on `main` (the section below), so nothing more was added: this
pass's own rule for it was dropped in favour of those. A rule for sitewide sales that Slickdeals titles lead with a
store's name for was written and taken out again: every post it would have found that day was from 2023 or 2024.

**The second pass, tested.** On the day's posts, the same rules reading first pages only and reading on: 3,182 →
6,102 posts; 259 → 372 sales at 77 → 101 stores, 178 → 251 of them named for Black Friday or Cyber Monday at 65 →
83 stores; 282 → 398 online deals ranked; 12 → 16 restaurant promotions (Wingstop's and three of KFC's were on the
restaurant feed's second page). No store was lost. Of the 225 deal-site posts both passes recorded by title, 39
were among the posts read before and 54 are now; 47 of the rest are on 9to5Toys, and most others are earlier waves
that had ended. Live at 20:50 UTC, through Slomp's own client: **328 sales at 96 stores** (222 at 75 in the build
published at 13:28 UTC), 196 named for Black Friday or Cyber Monday at 80 stores (140 at 65). Twenty-five stores
gained a card, among them Costco, IKEA, Kate Spade, Microsoft Store, GameStop, PUMA and Verizon. Four are not in
this run for reasons of their own: one sale had ended, and three posts were on 9to5Toys, which a run started by an
assistant does not read. A first full read took 83 more requests to dealnews and 17 to Hip2Save. On the page, a
search for Austin shows 327 sales with no page error. A replay reads no feeds, so rounds 1–6 are unchanged; 295 unit
tests pass, four of them new.

### The first build with the Nov 16 changes (run 161, Nov 22), and what its log led to

The changes of "A week of builds" were merged on Nov 22 and build 161 ran on them. Its log against the build before
it (run 160, the old code, three hours earlier):

| | Run 160 | Run 161 |
|---|---|---|
| Ad items left out as "no saving stated" whose words state one | 2,793 | 1,377 |
| Stores' own sites waiting for a read | 567 | 334 |
| Deals from stores' own sites | 2,017 at 221 sites | 2,077 at 227 sites |
| Sale posts with no store | 30 | 23 |
| Online posts with no industry | 27 | 25 |

Where both builds read the same ads, the deals rose: H-E-B 563 to 731, Albertsons 30 to 60, Tom Thumb 14 to 30.
Online deals were 115 (129 to 137 in the three builds before) and the build took 1,088 s (518 to 700 s); nothing in
the change removes online deals, and it was the first build after Sunday's new ads, but neither is explained. The
published deals themselves could not be read from this session, only the log.

The log's new lines said what to do next:

- **Savings.** What is still left out is as intended (a different item that comes free, a coupon with no amount,
  rewards), but for three wordings: "INSTANTLY SAVE [$1] *", "SAVE ADDITIONAL $8 WHEN YOU BUY 2" and "UP TO $50 OFF
  MSRP". All three are read now (DESIGN.md 4.3).
- **Stores.** Eight unnamed posts were printed with what they had to go on, all from Hip2Save, and none carries a
  link. Three name the store in a way no rule connected (a website in the title, a site whose name holds the
  title's, a store named only in the post), and one is a sale named for the store's own event after the offer.
  All four are read now (DESIGN-online-stores.md 4.3). Four have nothing Slomp can use: a title naming goods only,
  "32 Degrees" and "Barefoot Dreams" with no word of where, and a code "gave" to readers. The log now also prints
  how each unnamed post begins.
- **Industries.** The week's unfiled products were filed, and other kinds took their place: a blouse, trousers, a
  jumpsuit, a smart ring, a docking station. Those kinds are named now, and a learned word is no longer silenced
  by one stray label (DESIGN.md 4.4). DVDs and gift cards belong to no industry Slomp shows online.

Checked offline on what the records keep: the 421 posts of rounds 1 to 6 read the same before and after as sales
(108 kept, the same stores); of 1,242 titles and item names, three are filed differently, each rightly ("Cat
Footwear ... Chukka Boot" from Pets to Fashion, a blouse and "Woot Docking Stations Sale" from nothing). 292 unit
tests pass (286 before).

### The build on those (run 164, Nov 22): how each unnamed post begins

Merged the same day, and build 164 ran on them. Its log against the build before it (run 163, on the seventh
comparison's changes, which also read Hip2Save's front page: more posts, and more of them without a store than run
161's 23):

| | Run 163 | Run 164 |
|---|---|---|
| Ad items left out as "no saving stated" whose words state one | 1,394 | 1,362 |
| Sale posts with no store | 28 | 17 |
| Online posts with no industry | 23 | 15 |
| Store sales shown | 209 at 73 stores | 214 at 76 stores |

Dollar General rose from 422 to 438 deals on the same ads, Tom Thumb from 30 to 32. The build took 640 s (644 s).

The log now prints how each post without a store begins, and that was enough to see what was missing. Of the
eight it printed, all from Hip2Save and none with a link:

| The post | Its first words | Now |
|---|---|---|
| "Up to 75% Off Electric Bikes + FREE Shipping" | "make your way over to AliExpress.com where ..." | AliExpress |
| "Up to 70% Off Barefoot Dreams Throws, Clothes, Gift Sets & More" | "click over to BarefootDreams.com for ..." | Barefoot Dreams |
| "Today ONLY: Up to 80% Off 32 Degrees Clothes + Free Shipping" | "hurry over to 32 Degrees where ..." | 32 Degrees |
| "Corkcicle Gave Hip2Save Readers an EXCLUSIVE 30% OFF Code!" | "hurry over Corkcicle where ..." | Corkcicle |
| "lululelmon Black Friday Sale + Free Shipping = Popular Styles from $29 Shipped" | "... during the Lululemon Black Friday Sale!" | lululemon |
| "Cabela's & Bass Pro Shops Black Friday Ad Preview \| ..." | "Check out the Cabela's Black Friday latest sale info ..." | none: two stores, and an ad preview |
| "The Clean Skincare Brand Collin Loves Is Having Its BEST Black Friday Sale" | "... Collin has been using Verli Skincare ..." | none: no words send the reader there |
| "Best Publix BOGO Deals \| ..." | "We've rounded up the best Publix BOGO deals ..." | none: a roundup of a grocer's weekly ad |

None of the five needed a store's name written anywhere: each is a wording (any verb before "over to", the "to"
left out, a name that starts with a number, a sale the post names as the title does), described in
DESIGN-online-stores.md 4.3.

Naming a store is not the end of it, so each of the five was followed through the rest of the reader, and three
came out wrong once named:

- "Barefoot Dreams Throws ..." was filed under Grocery and "32 Degrees Clothes" under Beauty: a store's own name was
  read as the goods ("Barefoot" is a wine, "Degree" a deodorant). An unlisted store's title is now read without its
  name first, and "clothes", "throws" and more kinds of clothing ("loungewear", "knitwear") are known as goods (they
  were not). Not every word that ends in "-wear": the logs have "longwear", which is makeup.
- The 32 Degrees sale was called "Today ONLY", and the Corkcicle one "Gave Hip2Save Readers an EXCLUSIVE Code". Now
  "Clothes" and "Sale".
- The Lululemon post states no discount; it is kept as the store's event because its sale is the one the post names,
  and shows the price its title gives ("From $29").

They now read: AliExpress, "Electric Bikes", up to 75% off, Sports; Barefoot Dreams, "Throws, Clothes, Gift Sets &
More", up to 70% off, Fashion and Home; 32 Degrees, "Clothes", up to 80% off, today only, Fashion; Corkcicle, "Sale",
30% off, Home (the department Hip2Save files it under); lululemon, "Black Friday Sale", from $29, Fashion. These are
the posts as the log printed them, with only the first 110 characters of each text; the next build's log is the
check on the whole posts.

Two readings that were already on main turned out too wide while trying look-alikes, and are fixed: "Hurry over to
the Stuffed Animals page" under "Up to 50% Off Stuffed Animals" named a store called "Stuffed", and "Head over to Air
Fryers" one called "Air". The verification's own store check learned the same wordings, or it would have failed the
new sales for not saying their store.

Checked offline on what the records keep: the 421 posts of rounds 1 to 6 read the same before and after (108 kept,
the same stores, sale names and offers); of 1,242 titles and item names one is filed differently, rightly
("Everyday Deals on Clothes and Accessories for Women and Men", from nothing to Fashion). 296 unit tests pass (292
before).

### The build on those (run 169, Nov 23): the posts were named, and most of them were old

Merged on Nov 23 with the change that reads feeds past their first page, and build 169 ran at 05:18 UTC with the
assistant setting. The builds before it on the same day's posts: run 166 (21:03 UTC, the assistant setting) and run
168 (03:50 UTC, scheduled, without it), both on the code before this round's.

| | Run 166 | Run 168 | Run 169 |
|---|---|---|---|
| Sale posts with no store | 34 | 40 | 27 |
| Sale posts left out as ended | 132 | 132 | 137 |
| Sale posts left out as posted over 30 days ago | 539 | 535 | 538 |
| Store sales shown | 328 at 95 stores | 326 at 95 | 318 at 91 |
| Restaurant promotions | 55 | 55 | 42 |

**The posts.** Of the eight posts run 168 printed without a store, five are named in run 169 and gone from the
list: four of this round's five (Lululemon, AliExpress, 32 Degrees, Barefoot Dreams; the Corkcicle post was not
among the eight either build printed, so the log says nothing of it) and one no rule was written for, "Up to 90%
Off Otterbox Phone Cases", whose post begins "hustle over to Woot.com where ...": a verb on no list, read because
any verb before "over to" is. Three remain, as expected (two stores in one title, a store the post never sends the
reader to, and "Life in Lilac", below).

**Most of them were old.** The posts say so themselves: "Today, October 25th only" (32 Degrees), "Through October
31st" (Otterbox), "Today, November 20th only" (Barefoot Dreams). Once named they are left out as ended, which is why
that count rose as the unnamed count fell. A post's store is looked for before its dates, so the log's list of
unnamed posts shows posts of any age, and since feeds are read past their first page most of what it shows is old.
The count of 27 overstates what is missing, and the eight posts printed are not the eight that matter. The dates
should be checked first.

**The totals cannot be read as this round's effect.** Sales fell by 8 and promotions by 13 between runs 168 and 169,
an hour and a half apart. Promotions come from code that shares nothing with this round's change. Counts the change
cannot touch moved as much: posts left out as subscriptions were 18, 13 and 11 in the three builds, online posts
with no price 78, 86 and 65. Run 168 read 9to5Toys and run 169, started with the assistant setting, did not. And a
feed's later page that fails is dropped without a word, so two builds need not have read the same posts. The log
does not say how many posts a build read, nor which stores its sales are at; both would have settled this.

**What the list showed next**, each a wording and none a store's name:

- "Our Place Black Friday Sale Gets Even Better ..." and "head to Our Place": a sale the title names for the store,
  which the post's sending words confirm. Today that needs a link or shipping.
- "browse OOFOS.com and score ...", "Novilla.com is offering ...": the post writes the website of the title's name.
- "Life in Lilac Black Friday Sale", "Dr. Martens Boots": a name with a small word or an abbreviation inside it.
- "Ruggable's Pre-Black Friday Sale" in a post about a coupon: the sale is online, though nothing says it ships.

One reading narrowed in this round was narrowed too far and was put back after the build: words that go on after
the title's name confirm it ("Hop on over to Minky Couture" for "Minky") unless they are goods only together.

### What followed (Nov 24): the log made to answer, and four more wordings

**The totals, settled by the next builds.** Two scheduled builds ran on the same code after run 169:

| | Run 168 | Run 169 | Run 170 | Run 171 |
|---|---|---|---|---|
| Built (UTC) | Nov 23, 03:50 | Nov 23, 05:18 | Nov 23, 16:14 | Nov 24, 03:23 |
| Code | before the round | the round | the round | the round |
| Store sales shown | 326 at 95 stores | 318 at 91 | 357 at 99 | 410 at 109 |
| Restaurant promotions | 55 | 42 | 55 | 56 |
| Sale posts with no store | 40 | 27 | 32 | 35 |

Run 169's lower counts were that build's, not the change's: the promotions came back on the same code. What that
build failed to read cannot be told from its log, which is the point of the first change below.

**The log, made to answer.** Three changes, none of which alters what is shown:

- A post's dates are checked before its store, so the posts left out for want of a store are all posts that would
  otherwise be shown.
- The log says how each sale's store was decided, and prints every sale at a store Slomp keeps no entry for that
  the post's own words named.
- The log says how many posts each deal site's feeds gave, how many pages were read past a first page, and which
  feeds or later pages could not be read. A later page that failed used to be dropped without a word.

**Four wordings**, from the posts runs 169 to 171 printed (DESIGN-online-stores.md 4.3):

| The post | Its words | Now |
|---|---|---|
| "Our Place Black Friday Sale Gets Even Better with an EXTRA Promo Code!" | "... head to Our Place to ..." | Our Place: the title names the sale's store and the post sends the reader there |
| "Over 55% Off OOFOS Sandals & Shoes + Free Shipping" | "... browse OOFOS.com and score ..." | OOFOS: the post writes the website of the title's name |
| "Up to 55% Off Novilla Mattresses? Now That's Dreamy!" | "... Novilla.com is offering ..." | Novilla, the same way |
| "Life in Lilac Black Friday Sale: Up to 50% Off EVERYTHING ..." | "... Life in Lilac! Life in Lilac is ..." | the name is read whole; a store once the post sends the reader there, names its site, ships or gives a code |
| "Last Day to Score Up to 55% Off Dr. Martens Boots & Shoes" | "Lace up for the latest deal on Dr. Martens boots ..." | the name is read whole ("Dr" before); a store on the same terms |
| "Ruggable's Pre-Black Friday Sale = Up to 40% Off ..." | "This Ruggable Rug coupon doesn't come around often ..." | Ruggable once the post gives a code: a code shows a sale is online as shipping does |

The log prints the first 110 characters of a post, so for the last three the rest of the post decides, and the tests
write an ending for each. The next build's log will show which were named, and how.

A post of the fifth round that never had a store has one now, from its saved text: "PUMA's Stock Up sale slashes
extra 40% off: ...", whose post says "Just apply code STOCKUP during checkout".

**Found by probing, not in any log.** Before a code was let stand in for shipping, titles that name a sale and no
store were tried, and the first word of the sale's own name was being read as a store whenever the post shipped:
"Buy More, Save More Sale" as "Buy", "Stock Up Sale" as "Stock", "Spend & Save Event" as "Spend", "Pink Friday Sale"
as "Pink", "Travel Tuesday Sale" as "Travel Tuesday". Whether any reached the page is not known (the published
page cannot be read from this session, and the log did not list stores until now). They are turned away now; "Mix
& Match Sale" and "Lightning Deals" are not, and would show in the log's new list.

**Sale names.** Following the newly named posts through, three names were not names: "Black Friday Sale Gets Even
Better with an EXTRA Promo Code", "Mattresses? Now That's Dreamy", "Stock Up sale slashes : Shoes, bags, hoodies,
jackets, more". Now "Black Friday Sale", "Mattresses" and "Stock Up sale" (DESIGN-online-stores.md 4.4). Two saved
sales at Woot are named shorter by the same rule ("latest monitor sale", "audio sale").

Checked offline on what the records keep: of the 421 posts of rounds 1 to 6, three read differently, all above
(PUMA's sale kept, two Woot names); of 1,559 titles and item names none is filed differently. 306 unit tests pass
(299 before).

### Entertainment bought online (Nov 24): what the second pass's 30 findings led to

The second pass found 30 entertainment offers and Slomp showed none: 21 were subscriptions, gift cards and digital
games, left out by design, and 9 were tickets, passes and memberships no source carried. The owner decided that
subscriptions and tickets belong under Movies & Entertainment, and they are listed now (`slomp/entertainment.py`;
DESIGN-online-stores.md 4.6): on the Sales tab, marked "Subscription" or "Tickets & passes", read from dealnews'
Streaming Services, Movie Tickets and Things to Do, and from any post whose title says in plain words that it is
one. Gift cards stay out.

**On the day's posts** (read Nov 24, 08:20 UTC, with the three feeds: 61, 13 and 6 posts): 35 offers before duplicates
are merged and pages read again. Left out, each with its reason: 4 for one group of people (students, teachers, the
military), 4 with no seller named, 2 gift cards, 2 goods that ship under the ticket categories (a roll of paper
tickets, a board game), 2 that are no subscription (a series to buy, films that are always free), 2 with no price or
discount; and by the same times as any sale, the plans posted months ago.

**Live**, through Slomp's own client: 330 sales at 87 stores, 26 of them entertainment offers from 10 sellers: 20
subscriptions (Paramount+ at $2.99 a month for 2 months, regularly $13.99; eleven Prime Video channels and bundles;
Peacock from $2.99 a month; HBO Max at $5.49 a month for 12 months, regularly $10.99; MasterClass 50% off; YouTube
TV) and 6 tickets and passes (two AMC ticket packages, one at $36 where the post gives $98; two Fandango ticket
offers; Groupon's sale; free photos with Santa). Eight offers whose posts dealnews had taken down were dropped by
the page re-read, as any sale's would be. None is among the home page's biggest deals. A first run kept 14: a
store's Black Friday sale was taking its subscriptions as duplicates of itself, and two channels at one price were
merged; both rules now leave them alone.

**On the page**, with only Movies & Entertainment chosen: Near you, Regulars, Sales (26) and Stores (10), no Online
tab, the chip "Bought online", and a card's details quote the sentence that gives the regular price. With Tech
beside it the Sales tab has both, each under its own category; with only Restaurants & Dining there is no Sales tab.
No page error. engine.js and the server pick the same sales in the same order at four moments from Nov 24 to Dec 3,
with Movies & Entertainment alone (25, 21, 8, 3) and with every industry that has sales (327, 266, 69, 27).

**Against the 30 findings.** Eight are shown now, all subscriptions: Paramount+ (monthly and annual), Prime Video's
channel sale, Apple TV, STARZ, Crunchyroll and Peacock. Not shown: the nine at venues (Six Flags' 2027 pass,
SeaWorld San Antonio, Texas Tides, the San Antonio and Fort Worth zoos, Meow Wolf, Moody Gardens, AMC's popcorn
pass) and Cinemark's $5 tickets, which no deal site posted, so reading two more of dealnews' categories did not
bring them; the five gift cards and the digital games, by design; and six subscriptions that were not among the
day's posts in those categories. The tickets Slomp does show are the ones deal sites post.

**What was not tested live.** Hip2Save's robots.txt turns AI assistants away by name as of Nov 24 (it did not on Nov 22), so a run an
assistant starts no longer reads it (scheduled builds do). The rule for a site that gives no category was therefore
tested on Slickdeals' posts and in unit tests only. 314 unit tests pass, eight of them new.

### Places' own ticket pages (Nov 24): the venue offers no deal site carried

Ten of the second pass's entertainment findings were at places to go: the nine at venues (Six Flags' 2027 pass,
SeaWorld San Antonio, Texas Tides, the San Antonio and Fort Worth zoos, Meow Wolf's two, Moody Gardens, AMC's popcorn
pass) and Cinemark's $5 tickets. No deal site posted them. The owner asked for them to be read from the places' own
pages, and allowed this session to reach those sites. They are read now (`slomp/entertainment.py`, "a venue's own
page"; DESIGN-online-stores.md 4.6): `slomp/data/venue_pages.json` lists 15 places in Texas and where each sells its
tickets, and what is on sale comes from the page on every build, in the page's words.

**The pages were read first**, 30 of them on 14 sites, through Slomp's own client with the assistant setting on: 27
read, one address guessed wrong (404), and two not read: the Fort Worth Zoo's robots.txt turns AI assistants away by
name, and cinemark.com answers from a host this session may not reach.

**A first version read each page as one run of words, and it took perks for sales.** On those 27 pages it showed
"20% off" for Moody Gardens (a member's "20% Off at concessions and restaurants", then "15% Off any attraction ticket
purchase", also a member's benefit), "20% off" for LEGOLAND Discovery Center ("20% off admission for friends and
family who visit with you", then "10% off in our Cafe" read up against the next tile's "New Pass"), and it dropped
SeaWorld's headline because a menu's "Military Offers" sat 46 characters before it. Its quotes ran on into the next
tile. The reader now takes a page block by block, as it is laid out, and settles what a percent is off from its own
line and the lines touching it. On the same 27 pages: 17 state a saving on tickets and 10 state none, and each of
the 10 is right: Moody Gardens' three (its Black Friday offer is hotel rooms; its ticket discounts are a member's and
the military's), LEGOLAND's two ticket pages (perks, and "40% off ends September 10, 2026", which is over), the San
Antonio Zoo's membership and ticket pages, the Dallas Zoo's home page (its saving is on a plush toy that comes with
tickets) and membership page, and a Six Flags page that says nothing itself.

**Live**, through Slomp's client: 33 pages read, the 18 listed that could be and 15 sale pages found from them
("black-friday-deal", "special-offers", "promotions", "discount-offers"). 12 of the 15 places state a sale:

| Place | Shown | The page's words |
|---|---|---|
| Six Flags Over Texas, Six Flags Fiesta Texas, Schlitterbahn New Braunfels | 2027 Silver Pass for $69, ends Nov 27 | "Get a 2027 Silver Pass for $69. Ends 11/27." |
| SeaWorld San Antonio | Up to 50% off, through Black Friday | "Black Friday: Save Up to 50% on Tickets!" |
| Texas Tides (Galveston) | Up to 55% off, ends Nov 30 | "Save up to 55% on Tickets, Passes and More! Offer Ends Nov 30th" |
| San Antonio Zoo | Membership for $39.99, through Black Friday | "For a limited time, get a San Antonio Zoo Membership for just $39.99, SAVE $15, and receive TWO FREE bonuses!" |
| Houston Zoo | 10% off memberships, code MERRY26 | "Get 10% off Membership GC with code MERRY26" |
| Dallas Zoo | 10% off memberships, ends Nov 30 | "Now through Nov. 30, save 10% on membership!" |
| Meow Wolf (Houston and Grapevine) | 20% off a Portal Pass | "20% off + 2 free months Portal Pass Supremium" |
| SEA LIFE Grapevine, SEA LIFE San Antonio | 50% off the Texas Annual Pass, through Black Friday | "Black Friday Sale: 50% Off Texas Annual Pass" |
| LEGOLAND Discovery Center Dallas/Fort Worth | 25% off an Annual Pass, ends Dec 1 | "Black Friday Annual Pass Sale: 25% off a Whole Year of Fun" |

No card: Moody Gardens and LEGOLAND Discovery Center San Antonio (read; no sale on tickets stated), and the Fort Worth
Zoo (not read). Four things the live read showed, each fixed:

- My list had Texas Tides in Houston, and its own page gives Galveston. The six places whose pages give an address
  were then checked against it. The others' cities are in their names or, for Six Flags Over Texas, Fiesta Texas,
  Meow Wolf and LEGOLAND Dallas/Fort Worth, from what I know of them and not from a page.
- The San Antonio Zoo states its sale on its home page and not where it sells memberships, so its home page is
  listed.
- LEGOLAND's sale names the pass before the percent. That is read when the line names the ticket's own sale, and
  not otherwise.
- Meow Wolf's card first read "Up to 50% off", from its headline "up to 50% off tickets". The next lines of that
  page say what it is: "Buy One, Get One 50% Off ... save 50% on a second General Admission ticket". Half off the
  second is not half off, so a percent the page says is off the second of two is no longer shown under the page's
  looser name for it, and the card is the pass's 20%.

**The whole build, live**: 355 sales at 103 stores. Movies & Entertainment has 38 offers from 22 sellers: 20
subscriptions and 18 tickets and passes, 6 of them from deal sites' posts and 12 from places' own pages. None is among
the home page's biggest deals.

**Each card checked against its page.** The harness's four checks (`slomp/verify/sales_checks.py`, which now reads a
place's own page for the words Slomp quotes, the end it shows and the code): each of the 12 pages read again, not
from the cache: 48 of 48 pass.

**On the page**, with only Movies & Entertainment chosen: Sales (38) and Stores (22). A place's card gives its name in
full and its city ("Six Flags Fiesta Texas · San Antonio"; three parks sell the same pass, and which park is the
point), its details quote the page, say "Read less than an hour ago on sixflags.com" and "This is Six Flags Over
Texas's own page, not a deal site's post", and the button reads "See it on sixflags.com". The tab's notes name the
place that could not be read (Fort Worth Zoo), under Movies & Entertainment only; the notice over the list counts
the 142 deal-site feeds and not the 15 places. No page error, and nothing scrolls sideways at a phone's width.
engine.js and the server pick the same sales in the same order at six moments from Nov 24 to Dec 2, with Movies &
Entertainment alone (37, 33, 30, 27, 7, 3) and with every industry that has sales (351, 293, 246, 126, 63, 55).

**Against the ten findings.** Shown: Six Flags' pass, SeaWorld San Antonio, Texas Tides, the San Antonio Zoo, and
Meow Wolf's 20% off a Portal Pass Supremium. Two differ from what the hand search wrote down, and Slomp shows the
page: Six Flags' pass ends 11/27 by its page, not Nov 30, and SeaWorld's headline on Nov 24 is up to 50%, not 55%.
Not shown: Meow Wolf's buy-one-get-one on tickets, which is not a percent off; the Fort Worth Zoo (robots.txt);
Moody Gardens, whose offer is hotel rooms; AMC's popcorn pass, which is a snack plan and on no listed page; and
Cinemark's $5 tickets, whose site this session could not reach, so it is not listed. Six cards are for places the
hand search did not name: Schlitterbahn New Braunfels, the Houston and Dallas zoos, the two SEA LIFE aquariums and
LEGOLAND Dallas/Fort Worth.

**What was not tested.** A scheduled build: whether these sites answer GitHub's runners as they answered here is not
known, and one that answers with a bot check will be reported as not read. The Fort Worth Zoo in a run no assistant
starts. Any week but this one: the rules were shaped on Black Friday week's pages; a page left up, an end that has
passed and an old year are covered by unit tests only. 326 unit tests pass, 12 of them new (`tests/test_venues.py`).

### The first published build with Entertainment (run 173, Nov 24): two rough edges

The scheduled build of 16:01 UTC was the first on the Entertainment listing, and the first of it no assistant
started, so Hip2Save was read: 442 sales at 132 stores, 82 of them from Hip2Save's 3,600 posts, one feed failing
(Ben's Bargains, HTTP 403). Movies & Entertainment had 29 offers from 13 sellers, 23 subscriptions and 6 tickets.
Read through, the list had two rough edges, and both are fixed.

**One offer as three cards.** Amazon Music Unlimited's three free months stood three times, from three dealnews
posts: "Amazon Music Unlimited 3-Month Trial: Free" (Nov 12), "... 3-Month Subscription: free" (Nov 13) and "...
Black Friday Offer: 3 months for free" (Nov 24), all Amazon's, all ending Jan 11. A subscription's posts were one
card only when their names were the same words, a rule made so that two channels at one price stay two; "Trial",
"Subscription" and "Black Friday Offer" are three wordings of one thing. Names are now compared by what they are
for and for how long: the words for the kind of offer and the day it is named for are set aside, and the term is
compared on its own (`sales.offer_words`). That also closes a hole the old rule had: it dropped the figures, so a
3-month and a 6-month trial at one seller would have been one card.

**A seller shown as a web address.** A Slickdeals post's card read "disneyplus.com" beside dealnews' "Disney+" cards.
Slickdeals gives a store Slomp's registry doesn't know as its address, and the listing showed what it was given. The
post writes the name itself, beside the address or at the head of the sentence ("Disney Plus is offering 1-Year
Disney+ w/ Hulu ..."), and that name is shown when its letters spell the address (`feeds.written_name`). Then a
seller has one spelling across a build (`sales.name_sellers`): "Disney+", "Disney Plus" and "disneyplus.com" are the
same letters once "+" is read as "plus", and the best-ranked source's spelling is used for all.

**On that build's own 442 sales**, with both rules: one seller's name changes ("disneyplus.com" to "Disney+") and
two cards are merged (the two later Amazon Music posts into the first), 440 sales. Nothing else changes: no store's
sale is merged or renamed, and "Prime Video Black Friday STARZ Subscription Deal" and "... Paramount+ ..." at $2.99 a
month are still two. On the morning's live build of 343 sales, nothing changes.

**On Slickdeals' posts of the day** (687, read Nov 24 17:20 UTC): 23 give a web address for a seller, 17 different
addresses. The post writes a name that spells the address for 11 (Shokz, 32 Degrees, PlayStation Store,
ThatDailyDeal, ShopSimon, Urban Outfitters, Fanatical, Steam, Cat Footwear, SideDeal, DiscountMugs) and none for 6,
rightly: beside lg.com stands a television's name, beside homeandcooksales.com the word "deal", and four give the
address only inside a link. These names are used for Entertainment's sellers only. Product deals on the Online tab
keep the address, because the price comparison uses it to leave the store's own site out.

**Live**, through Slomp's client (Nov 24, 17:25 UTC, started by an assistant, so without Hip2Save): 373 sales at 112
stores, 38 under Movies & Entertainment from 24 sellers: 20 subscriptions and 18 tickets and passes, 12 of those from
places' own pages. Amazon Music Unlimited is one card, "3-Month Trial", with the other two posts listed under it. No
card's seller is a web address. The Disney+ post from Slickdeals was no longer among the day's posts, so its seller
was not seen renamed live. engine.js and the server pick the same sales in the same order at six moments, with
Movies & Entertainment alone and with every industry that has sales.

**The checks.** The harness's duplicates check compared a subscription's names by shared words and called STARZ and
Paramount+ at one price a duplicate; it compares them as the pipeline does now, and on the published list it reports
the three Amazon Music cards and not the two channels. It also reports two pairs of store sales the pipeline keeps
apart on purpose, an early Black Friday sale and the day's own at Foot Locker and at Target; that disagreement is
older than this change and is left as it is.

**What was not tested.** The Disney+ post as its feed gave it: it had left Slickdeals' feeds when this was written,
and its page reads "Disney Plus is offering ...". Both wordings, with the address in brackets and without, are in
the unit tests. 329 unit tests pass, three of them new.

### The build with places' own pages (run 174, Nov 25): what it settled, and two more rough edges

The scheduled build of 01:29 UTC was the first on the venue pages and on the two fixes above: 488 sales at 157
stores, every one of the 142 feeds read. Movies & Entertainment had 39 offers from 26 sellers: 20 subscriptions and
19 tickets and passes, 13 of them from places' own pages.

**What had not been tested, and now is.** All 15 places' sites answered GitHub's runners; none sent a bot check. 13
state a sale. The Fort Worth Zoo, which a run an assistant starts does not read, was read: "Our Black Friday Sale is
live! Enjoy 15% off gift memberships.", the offer the hand search had found there. Moody Gardens and LEGOLAND
Discovery Center San Antonio were read and state no sale on tickets, as in the live run. The other 12 cards are the
live run's, word for word.

**The two fixes held.** Amazon Music Unlimited's three free months is one card, with the two other posts listed
under it, and no seller under Movies & Entertainment is shown as a web address.

**A store's sale listed as a subscription.** "Musician's Friend Black Friday Deals: Up to 60% off + free shipping"
stood under Movies & Entertainment, marked Subscription: dealnews filed it under Streaming Services, and Slomp takes
dealnews' category for what a post is. Of the day's 81 posts under dealnews' three categories (read Nov 25, 04:20
UTC), 62 are under the subscription ones. Shipping cannot tell them apart: dealnews ends 14 of the other 61 titles
with a shipping note too ("Disney+ NFL+ Premium & RedZone Bundle Streaming Plan for $45.99/mo + free shipping").
What can: a subscription's post names one. Six of the 62 titles name none. Three state one price, "free" or no
offer and were already left out, one is for teachers, and of the two sales left, MasterClass's words say "50% off
the first year of a membership" and Musician's Friend's speak of guitars, basses and amps. So a post under a
subscription category that states a percent or dollars off and no price, and names no subscription in its title or
its own words, is judged as any store's sale is (`entertainment.a_stores_sale`). On the 81 posts that changes one,
and it leaves Movies & Entertainment: Slomp's registry does not know the store, so it is left out as a sale with no
industry.

**One bundle as two cards.** Prime Video's AMC+, MGM+ and STARZ bundle stood twice: dealnews' "Prime Video Black
Friday AMC+, MGM+ & STARZ Bundle Deals", $5.49 a month for 2 months, ending Nov 30, and Slickdeals' "Amazon Prime
Video Bundle Offers: 2-Month MGM+, Starz & AMC+ Streaming $5.50/Month & More", with no end. The price is a cent
apart, one post gives no end, and the names differ by the seller's own name, "Streaming" and "& More". Two posts
whose names say the same thing for the same term are now one offer when the price is the same or a cent apart and
the end is the same or given by only one (`sales.same_price`, `sales.offer_said`); the term is read from the name
or the offer line. In run 174's list four pairs of offers at one seller are priced within a cent: this one, and
three that stay apart because they are for other things (STARZ and Paramount+ at $2.99, and HBO Max beside each of
the bundle's two posts). A store's sale is held to the same badge and the same end as before.

**On the published builds' own sales.** Run 174's 475 sales from posts: one pair merged, the bundle, and nothing
else. Run 173's 442: the same pair, beside that round's two.

**Live**, through Slomp's client (Nov 25, 04:25 UTC, started by an assistant, so without Hip2Save and the Fort Worth
Zoo): 394 sales at 122 stores, 36 under Movies & Entertainment from 24 sellers: 18 subscriptions and 18 tickets and
passes, 12 of those from places' own pages. Musician's Friend's sale is not listed, under Movies & Entertainment or
anywhere. The bundle is one card, dealnews' at $5.49 a month ending Nov 30, with the Slickdeals post listed under
it. Amazon Music Unlimited is still one card and no seller is a web address. engine.js and the server pick the same
sales in the same order at six moments, with Movies & Entertainment alone and with every industry that has sales.

**What was not tested.** A store's sale filed under a ticket category: none was among the day's posts, and those
categories are not second-guessed. 331 unit tests pass, two of them new.

### Keyword search (Nov 26): what it finds on real deals, and what that changed

A search can be narrowed to the deals that say the words typed (`slomp/search.py`, DESIGN.md 14). It adds no source
and no rule about what a deal is, so what was to be verified is the matching itself, that the server and the
published site match alike, and that the page handles it.

**The rule, in both places.** The published site matches in the browser, so the rule is in engine.js too. One test
runs the two on the same seven deals, of every kind, with 83 searches, and on odd text (accents, full-width
letters, ligatures, an apostrophe of each kind, 300 characters): the same words read, the same folding, the same
deals found. Another builds a small site and checks that the engine's answer to a search with words is what
`search.py` makes of the engine's own answer without them: the same deals in the same order in every part, the
same counts, online deals narrowed before the best two are taken.

**On real deals** (a copy of the published site's files for Austin, 25 miles, every industry, with the sales of the
Nov 25 live run), a first version let any word asked for start a word of the deal. Three things showed, and the
rule changed for each:

- "zoo" found a camera with "16X Zoom", and "wi-fi" found 51 ads, one a wreath "with" a "fir" bow: one, two and
  three letters start too many words. A word under four letters must now be the whole word, or its plural or
  singular. "zoo" finds the three zoos' sales and no ad; "wi-fi" finds 23.
- "tshirt" found nothing and "t-shirt" found 34. Words written joined or apart are now the same word. Both find the
  same 26; the eight gone were ads with a word starting with "t" and a shirt.
- "buses" did not find "bus": a plural in -es is now read both ways.

With the rule as it is, on the same deals:

| Typed | Near you | Regulars | Online | Sales |
|---|---|---|---|---|
| lego | 1 | 0 | 1 | 7 |
| nike shoes | 15 | 0 | 2 | 0 |
| air fryer, airfryer | 17 | 0 | 3 | 0 |
| tv, tvs | 39 | 0 | 2 | 6 |
| 65 tv | 6 | 0 | 0 | 0 |
| kohls | 77 | 0 | 6 | 5 |
| happy hour | 0 | 20 | 0 | 0 |
| dog food | 10 | 0 | 0 | 0 |
| earbuds, ear buds | 6 | 0 | 2 | 0 |
| smartwatch, smart watch | 1 | 0 | 2 | 0 |

The first deals of each were read and say what was asked: "65 tv" is six 65-inch televisions, "happy hour" twenty
restaurants' happy hours, "kohls" Kohl's own ads and sales, "lego" Target's LEGO ad, a LEGO set at Amazon, five
stores' LEGO sales and LEGOLAND's pass. "nike shoes" finds a "Nike Air Max 270" whose title has no "shoes": its ad
files it under Shoes, and the category is searched.

**In a browser**, on the same files: a link with words and no category (`?city=austin&q=lego`) fills the box,
leaves every category unchosen, searches them all and says so over the tabs; words typed and sent with Enter or the
button go into the address; each tab opens on all its matches, with the categories that have some as chips ("All
15, Sports 11, Fashion 15"); words that nothing says give each tab its own "No ... say" with a button that takes
the words away; that button returns to the start when no category is chosen, and to the same search without the
words when some are. A search without words is as it was. No page error, and nothing scrolls sideways at a phone's
width.

**Live, through the server's code** (the CLI, Nov 26 to 27, started by an assistant, so without Hip2Save):
`slomp sales -q lego` gave 6 sales at 5 stores across every industry with sales; `slomp local austin -q "nike
shoes" -r 10` gave 5 deals and 9 promotions, each a Nike shoe; `slomp sales -i fashion -q zzyzx` gave none; and
`slomp sales` with neither words nor an industry is refused, as before.

**What was not tested.** The page against a running server: in a browser it was tried on the published site's
engine only, and the server's answers through the API with stand-ins for its sources and through the CLI live.
Spelling: "leggo" finds nothing. A published build with it.

338 unit tests pass, seven of them new (`tests/test_search.py`).

### Runs 179 and 180 (Nov 27): keyword search published, an offer shown twice, and what stores' sales lose

**Keyword search on the published site** was the part not tested before. Run 179 published it, and in a browser on
https://homiejhan.github.io/slomp/ a link with words and no category, words typed, words nothing says and the words
taken away all behave as on the test copy: "lego" for Austin gave 1 ad nearby, 3 online deals and 6 sales; "nike
shoes" 16 nearby and 7 online. No page error, nothing scrolls sideways at a phone's width. The two fixes of run 174
held: no Musician's Friend sale under Movies & Entertainment, and the Prime Video bundle is one card with the
Slickdeals post under it. Run 179 was started by an assistant, so it skipped Hip2Save and the Fort Worth Zoo; the
scheduled run 180 read them again: 595 sales at 165 stores, all 142 feeds read, 102 sales from Hip2Save, 13 cards
from places' own pages.

**One offer as two cards, again, for a new reason.** Run 180 showed "Prime Video Black Friday Apple TV Subscription
Deal" twice and "Prime Video Black Friday Subscription Deals: Up to 79% off" twice. dealnews posted each twice, and
gave the end as 11:59 PM Eastern on Nov 30 in one post and 3 AM Eastern on Dec 1 in the other, which is midnight
Pacific that same night. End days were compared by calendar day. For subscriptions and tickets they are now the day
a shopper would say (`sales.end_day`): an end in the small hours in Texas belongs to the day before, as the page
already shows ends. On run 180's own 582 sales from posts that merges those two pairs and nothing else.

**Why not for stores' sales too.** Tried on the same 582, the rule for every sale merged 13: those two, one real
duplicate (Target's Christmas lights, from dealnews and Hip2Save), and ten sales of different things, among them
Macy's Nike sale into its Cole Haan sale, and Walmart's LEGO sale into its sports sale. They were being kept apart
only because their ends were written in different time zones. A store's sales are one sale when the store, the
badge and the end day are the same and their names share 60% of their words, and in this week "Black" and "Friday"
are two of the three words in most names.

**What that rule already costs, measured and not fixed here.** Of run 180's 555 cards for stores' sales, 72 have
other posts under them, 180 posts in all. Reading each against the card it is under, with the day it is named for
set aside:

| The post under the card is | Posts |
|---|---|
| the same sale | 11 |
| a sale whose name shares most of its other words (Best Buy's half-price appliance and phone deals) | 5 |
| a sale of something else, joined by the day's name (Gillette, Vitamix, Ninja, Yeti and Dyson under "GearWrench Black Friday Deals at Amazon"; 16 of Fanatics' sales under its storewide one) | 103 |
| a post with no discount stated, for something else ("Lowe's Black Friday Hand Tools Deals for From $15" under its appliance sale) | 61 |

So about 160 sales that are not the card they are under are listed only as "also posted" on it. The second kind
comes from the rule that an event's headline with no discount yields to a sale of the same store and day that
states one, which was made for "Amazon's Black Friday Sale Is Live". Changing either decides how many cards a store
shows in such a week, and that is the owner's call; the measure is here for it.

339 unit tests pass, one of them new.
