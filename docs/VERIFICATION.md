# Verification log

Plum is checked against the real sources, not against itself. Each iteration samples 10 Texas cities (3 with 200k+
people, 3 with 20k–200k, 4 under 20k) and spreads all 13 industries across them. It runs Plum the way a user would,
then runs **200 live tests** that re-read each result from the source by a different route than the pipeline used.

| Group | Test | Count | Passes when |
|---|---|---|---|
| Local | Source fidelity | 40 | The item's own Flipp record, fetched fresh, has the merchant, title, price and dates Plum shows (restaurant promotions: the post page still shows the offer) |
| Local | Time window | 15 | The source's dates overlap the next 7 days in the city's time zone, and "ends"/"starts" labels are right |
| Local | Vicinity | 20 | The chain's own store locator (AllThePlaces, independent of the OpenStreetMap data Plum uses) has a store within the radius |
| Local | Industry | 20 | A blind judge, shown only the title and store, puts the item in the industry Plum showed it under |
| Local | Terms and math | 10 | Percent and savings follow from the prices shown, and agree with the fresh record's own % off, $ off and original price; buy-X-get-Y offers are read as such |
| Local | Recall | 15 | A random item with a stated saving, which the source itself files under the industry, is in Plum's output or was left out for a valid reason (no store nearby, ended, duplicate) |
| Online | Source fidelity | 25 | The deal's post page shows the price and product, and isn't marked expired |
| Online | Merchant link | 15 | The deal's store link (followed like a browser would) lands on the store Plum names; an Amazon page's buy-box price matches, allowing for stated codes and coupons |
| Online | Comparisons | 20 | Each "same product elsewhere" listing, re-fetched, is the same product at the price shown (±2% or $1) |
| Online | Industry | 10 | Blind judge agrees |
| Online | Ranking and quality | 10 | Discounts recompute from the prices shown; order follows score; no duplicates, storewide sales or stale posts |

**Rules.** A test that can't be made (the source is down, blocks automated reading, or doesn't cover the subject) is
recorded as *inconclusive* and replaced by another subject of the same kind. A category that runs out of subjects
hands its remaining tests to its side's source-fidelity tests. Pass rates are over conclusive tests, and inconclusive
counts are reported alongside. Every failure is triaged as a **Plum bug**, a **source error** (the source itself is
wrong or changed) or a **test bug**, fixed with a regression unit test where it is a Plum bug, and the next iteration
runs on a fresh sample. Full per-test evidence is in `docs/verification/iteration-NN.json`.

## Summary

**1,968 of 2,000 live tests passed (98.4%)** over ten iterations: 100 city queries across 79 Texas places, from Corral City (population 41) to San
Antonio (1.5 million), including 20 places under 1,000 people, and all 13 industries (each queried 12–19 times). Another 437 attempts were inconclusive (a source
was down, blocked automated reading, or didn't cover the subject) and were replaced. The first iteration passed 94.5%;
the next nine passed 98.0–99.5%.

The 32 failures broke down into 26 **Plum bugs**, all fixed with a regression test; 3 **source errors or drift** (an ad
mislabelled by its source, a post whose price changed); and 4 **test bugs**, fixed in the harness. One dog-bed failure
was both drift and a Plum bug. Reviewing runs and auditing labels between iterations found about 20 more Plum issues
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
  330 times. The one miss was an ad Flipp pulled at 11:59 PM Eastern while Plum still showed it until local midnight
  (fixed). The retailer's own product page confirmed the ad price or Plum's stated regular price 67 of 70 times.
- **Industry labels are the weakest part:** 95% agreement with a blind judge for local deals, 96% online. Each miss
  was a keyword or a source label that read an item wrongly (a wine at a pharmacy, gardening gloves filed as apparel,
  a body wash "with vitamin B3"); each got a targeted fix. Expect a long tail of such cases.
- **"Near you" holds up.** 199 of 200 vicinity tests passed against the chains' own store locators, which are
  independent of the map data Plum uses. 84 more couldn't be checked: AllThePlaces' Walmart and Target scrapes are
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

| Iter | Date | Cities (industries) | Passed | Rate | Inconclusive | Local | Online | Plum bugs found |
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
| L-MATH Dollar General drain gel | Shown "saves $2.04"; the record says $2.00. Plum derived a regular price from the ad's rounded "28%" | Plum bug | A headline percent alone is shown as a percent; no regular price is computed from it |
| O-FID dealnews LEGO Williams Racing | Shown $51; the post says $50.99. The feed's structured price is rounded | Plum bug | Prefer an exact price in the post text within $1 of the title's |
| O-FID Slickdeals Bedsure dog bed | Shown $26.40 (title); the post says "= $26.39" | Plum bug | Same fix |
| O-MER Pepsi Zero Sugar "3 for $15" | Shown as $15 for one 12-pack; Amazon sells one for $6.97 | Plum bug | "N for $X" is read as a multi-buy and compared per unit ($5.00 each) |
| O-MER Fanttik X8 inflator | $72 needs "extra 10% off in checkout"; Amazon's page shows $79.99 | Plum bug | Cart and checkout discounts are a stated condition |
| O-MER adidas Supernova $39 | Amazon's default size and color is $74.90 | Plum bug | Apparel sold on Amazon, Walmart or eBay carries "price varies by size or color" |
| L-IND KT therapy tape (Walgreens) | Shown under Beauty from Google's "Personal Care"; judge: Health, Sports | Plum bug | Personal Care items are split by their words; therapy and braces go to Health |
| O-IND VitaUp vitamins | Hip2Save's beauty feed put vitamins in Beauty; judge: Health | Plum bug | Hip2Save's categories are hints; the title decides |
| O-IND Women's cat Christmas tees | "cat" put a T-shirt in Pets; judge: Fashion | Plum bug | Pets needs a pet product; bare pet words count only when nothing else names the item |
| O-MER Faux fur dog bed | Shown $64.99; Amazon now $72.99 for the default size | Source drift | none: the post's price changed or applied to another size |
| L-GEO Cabela's near Rockwall | The Allen, TX store is real; AllThePlaces' Cabela's scrape had 36 stores nationwide | Test bug | AllThePlaces is used only when it has at least half the stores OSM maps for that chain in Texas, and is merged across 3 runs |

**Quality finding.** Only 4 of 119 online deals carried a model number, so cross-site comparisons were rare. Plum now
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
| O-MER Faux fur dog bed (again) | Amazon $72.99 vs the post's $64.99. Plum's new store check caught the change, but labelled it "out of stock" | Source drift + Plum bug | See below; Plum now shows "store price now $72.99 (the deal may have ended)" and ranks it low |

**Found by inspecting the run, not by a failing test:** 7 of the 8 Amazon deals Plum store-checked were flagged "out of
stock" although their pages showed a buy-box price. Every Amazon product page carries "Currently unavailable" in a
script's message table. Availability is now read from the buy box's own availability line (regression test added).
The verification parser had the same flaw and got the same fix.

**Comparison coverage, measured.** 2 of 122 online deals had a model number or UPC usable for lookups. Plum resolved
the Amazon page for 8 deals; most of those pages give a UPC but no model number, and no free source with prices
exposes UPCs. Half the deals come from Hip2Save, whose store links are drawn by JavaScript. Verified cross-site
comparisons are therefore limited to model-numbered goods (electronics, appliances, tools, LEGO). Elsewhere each deal
says what its discount is measured against: the store's own regular price, a deal editor's check of other stores, or
a list price.

### Iteration 3 (seed 3007)

| Test | What happened | Kind | Fix |
|---|---|---|---|
| O-FID dealnews Hudson Baby sleeping bag | The post now redirects to dealnews' Amazon store page: the deal ended. Plum's store check saw Amazon at $16.99 vs $10.94, but "Prime members" let it pass as a possible Prime-only price | Plum bug | Plum now re-reads the posts of its leading candidates and drops any that were removed (redirected or 404) or are marked expired |
| L-IND "Apothic Red" at Walgreens | No keyword matched, so it fell back to Walgreens' health/beauty prior; judge: grocery (it's wine) | Plum bug | Pharmacies no longer have a prior (they sell wine, snacks and toys); wine varietals and brands added |
| O-IND Walmart drawstring bags (Hip2Save kids feed) | No keyword matched, so Hip2Save's kids category put it in Baby & Kids; judge: fashion | Plum bug | Bag types (drawstring, crossbody, tote, duffel) added to fashion |

**Test changes from iteration 4.** A new **retailer page** test (10, taken from local source fidelity's 40) reads
the retailer's own product page for weekly-ad items (PetSmart, Old Navy, Ulta, Office Depot, Costco, Sam's Club and
others that answer a script). It passes when the page shows the ad's price, or the regular price Plum states (weekly-ad
prices can be in-store only), and fails when it shows neither. It puts the ads themselves to a real-world test, which
source fidelity alone can't. Each report now also records quality metrics: share of deals with a firm basis,
online identity and comparison coverage, store checks, and deals flagged as changed.

### Iteration 4 (seed 4007)

First run of the retailer-page test: 9 of 10 retailer pages showed the ad's price or the regular price Plum states.
Quality: 1,838 local deals, 57% with a firm basis (the store's own regular price), 0.1% at unconfirmed stores; 121
online deals, 14 store-checked live on Amazon (1 flagged as changed), 5 with a product identity, none with 2+ other
sites.

| Test | What happened | Kind | Fix |
|---|---|---|---|
| L-RET Dollar General Febreze | Plum's "store page" link was Dollar General's coupons landing page, not the product | Plum bug | Only product pages are shown as the store page |
| L-IND "Diamond Mesh Gate" at Kroger | The bare word "diamond" (added for jewelry in iteration 1) made a safety gate Fashion; judge: Baby & Kids, Pets | Plum bug | "diamond" counts only with a jewelry noun; safety, baby and pet gates added |
| L-IND PetSmart reptile terrarium | Flipp's taxonomy said Home > Decor; judge: Pets | Plum bug | Single-category stores (PetSmart, Petco, Ulta, Bath & Body Works, AutoZone, O'Reilly) decide their items' industry |
| O-FID Slickdeals adidas Grand Court | The post wrote "= $ 18.60" (a space after the sign) | Test bug | Price matching allows that space |

### Iteration 5 (seed 5007)

Every automated test passed (170/170); the judge disagreed once.

| Test | What happened | Kind | Fix |
|---|---|---|---|
| L-IND Miracle-Gro floral gloves (Tractor Supply) | Flipp's taxonomy says Clothing Accessories, so Fashion; judge: Home (gardening gloves) | Plum bug | Garden, work and cleaning gloves and protective gear are Home whatever the taxonomy says |

**Found by auditing, between iterations 4 and 5:** a review of 70 random items labelled by keywords or store priors
found five collisions no judge test had hit yet: a plush bath towel (Toys), a flannel sheet set (Fashion), an espresso
machine (Grocery), a body groomer named "The Lawn Mower" (Home), and "Watch Party" (Fashion). Fixed with an early
rule for home textiles and kitchen machines, narrower toy and watch terms, and grooming terms; each has a regression
test.

**Found by inspection:** searches on other sites used Plum's normalized model key ("Apple AIRPODSPRO3") instead of the
words as written ("Apple AirPods Pro 3", "Sony WH-1000XM6"), so the weekly-ad search could never match named products.
Fixed. Also: console bundles no longer match the console alone, and Slickdeals posts that list several stores
("Amazon has it for $51.99… Target has it for $51.99") now show those prices as "per the post", kept out of the
median of Plum's own checks. The comparison test re-reads the post for them.

### Iteration 6 (seed 6007)

| Test | What happened | Kind | Fix |
|---|---|---|---|
| L-RET Dollar General Pedigree dog food, Tidy Cats litter | Dollar General's product pages draw prices with JavaScript, so neither price is visible to a script; the test read that as a mismatch | Test bug | A page without a structured price, where the ad price isn't visible either, is inconclusive |
| L-IND Ring indoor security cam (Best Buy) | Taxonomy "Home Security" mapped to Home; judge: Tech | Plum bug | Home-security items are Tech and Home |
| L-IND bROK pintle hook (Tractor Supply) | Taxonomy "Hardware" mapped to Home; judge: Automotive | Plum bug | Towing gear (pintle hooks, hitches, ball mounts, winches) is Automotive |

**Found by auditing iteration 5's online labels:** toner pads were Health (from "pads", added for incontinence
products), a night light was Tech (a generic "battery" term), a kids' terrarium kit was Pets, and DJI camera drones
were Toys (dealnews files drones under RC vehicles). Fixed with regression tests. Every deal with a real model number
now gets other-site lookups, not only the top 10 per industry.

### Iteration 7 (seed 7007)

The judge agreed on all 30 industry tests. Cross-site comparisons appeared for the first time: both comparison
listings checked out, and one deal's discount was measured against other stores' median price.

| Test | What happened | Kind | Fix |
|---|---|---|---|
| L-REC PetSmart "Foldable Pet Gate - Dog Gate" | Flipp files it under Baby Safety, so the recall test expected it under Baby & Kids; Plum (rightly) treats everything at PetSmart as Pets | Source error | The recall test no longer fails Plum where it deliberately overrides the source's category; the blind judge arbitrates those |

**Found by auditing taxonomy-labelled items (iterations 4–6):** Flipp files Target's promo banners under "Signage"
(Plum had them as Office), a bottle jack under Material Handling, a tire repair kit under Plumbing, Target throws under
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
| L-IND Caress body wash "…with Hyaluronic Acid & Vitamin B3" (Walmart) | The ingredient "Vitamin" made it Health as well as Beauty (a side effect of iteration 7's rule giving items with both kinds of words both labels); judge: Beauty | Plum bug | Industry is read from the product's head phrase, before "with …"; the full title is used only if the head says nothing |
| L-IND Funko Jurassic Park plush (GameStop) | Flipp files it under Baby Toys; judge: Toys | Plum bug | Baby Toys counts as Baby & Kids only when the item names babies, ages in months, teethers, rattles and the like |

### Iteration 9 (seed 9007)

| Test | What happened | Kind | Fix |
|---|---|---|---|
| L-REC Funko plush at GameStop, $0.02 "100% off" $4.99 | Plum refused to believe a 99.6% saving from the ad (likely an ad error) but recorded it as "no saving stated" | Plum bug (wrong reason) | Rejected savings are named: "implausible saving (99.6% off a $4.99 price: likely an ad error)"; the recall test accepts that reason |
| L-IND Michaels "ALL Scrapbook & Photo Albums" | Taxonomy Household Supplies mapped wholesale to Grocery & Household; judge: Home, Toys | Plum bug | Household Supplies goes to Grocery & Household only for cleaning, laundry, paper and bags; the rest is Home |
| O-IND Perler fuse-bead kit (Hip2Save kids feed) | No keyword matched, so the kids feed put it in Baby & Kids; judge: Toys | Plum bug | Craft kits, fuse beads, scrapbooks and coloring and sticker books are Toys |

La Grange (Restaurants + Sports, 25 mi) returned nothing: no sporting-goods ad within 25 miles, and none of this week's
chain promotions has a branch there.

### Iteration 10 (seed 10007)

The judge agreed on all 30 industry tests.

| Test | What happened | Kind | Fix |
|---|---|---|---|
| O-FID dealnews Hudson Baby sleeping bag (again) | The feed now linked this ended deal straight to dealnews' Amazon store listing page, so no redirect was left for iteration 3's fix to catch | Plum bug | A post whose link is a dealnews store page, or whose page no longer shows the deal's title, counts as removed. Spot-checked live: dropped, along with 3 other ended posts |
| L-FID ULTA La Roche-Posay cleanser (Lubbock) | The ad ran "through Oct 4". Flipp encodes that as 11:59 PM Eastern and pulled the item at 10:59 PM Central; Plum showed it until 11:59 PM local | Plum bug | Dates still display as the day the ad names, but an item is live only until the earlier of the two times. Spot-checked live: Lubbock's ended ULTA ad is gone |

### Iteration 11 (seed 11007): after the web page rework

Putting pictures on the page exposed data errors the tests had only sampled, because the ad's own picture now sits
next to what Plum says about it. Fixed before this run, each with a regression test:

- **The source's category labels can be absurd.** Flipp filed JCPenney diamond rings and a Best Buy ice-cream maker
  under Food, and Lowe's razor blades under Beverages. Plum now keeps labels to what each kind of store sells (a
  `sells` list for 26 chains): a label outside it is replaced by what the item's words say, or by the store's own
  line. Food labels at stores that sell no food count only when the words agree.
- **Buy-one-get-one wording.** "BUY ONE. GET ONE 50% OFF" (a period), "Buy 1 get 1 50%* off" (an asterisk), "Buy 1 get
  150% OFF" (a missing space) and "Buy 2 get 3rd FREE" were misread as 50% off, free, "get 150" and "get 3". Offers
  without a price were also ranked last; they now rank by their effective saving.
- **Fine print is read per industry.** Plum reads the full record of the first 24 deals in each requested industry
  (it used to read the first 40 overall), so the deals a user sees first have their buy-one-get-one terms and store
  links.

Result: **196 of 200 (98.0%)**, 61 inconclusive. Laredo, Austin, Arlington, San Angelo, Fresno, Victoria, Wallis,
Briaroaks, Premont, Navasota.

| Test | What happened | Kind | Fix |
|---|---|---|---|
| O-MER LOVEVOOK laptop backpack; UGREEN charger | The test took the first Amazon link on the post page, which was a related product, or compared a headline-style title with the listing's | Test bug (×2) | A store link the test finds itself is inconclusive unless its title matches; only Plum's own store check can fail this way |
| L-IND SheaMoisture hair cream (Walmart) | Only a top-level "Health & Beauty" label and no keyword hit, so it was shown under both; judge: Beauty | Plum bug | Hair, face and body creams, masks, oils and serums are Beauty |
| L-IND Composure bladder control pads (Dollar General) | Taxonomy Personal Care mapped to Beauty; judge: Health | Plum bug | Bladder-control and incontinence products are Health |

Every source-fidelity, date, vicinity, math, recall, retailer-page, comparison and ranking test passed (168 of 170
automated tests; the two misses were the test bugs above). The recall test now treats any deliberate departure from
the source's category as inconclusive (5 this run), since the blind judge is the arbiter there.