# Verification log

Slomp is checked against the real sources, not against itself. Each iteration samples 10 Texas cities (3 with 200k+
people, 3 with 20k–200k, 4 under 20k) and spreads all 13 industries across them. It runs Slomp the way a user would,
then runs **200 live tests** that re-read each result from the source by a different route than the pipeline used.
Regular deals, added on Oct 5, have their own plan and results in [their own section](#regular-deals) below, and so
do online stores' sales, added on Oct 6 ([Online stores' sales](#online-stores-sales)).

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

