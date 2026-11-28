# Online stores and their sales: design

**Request (Oct 6, 2026):** a feature and tab for online stores (Amazon, eBay, and retailers that ship), which belong to
no one city but often run good deals, and a tab for those deals.

**Short answer.** Two new tabs in the results, the same for every Texas city:

- **Sales:** store-wide and category-wide sales, promo codes and sale events at online stores that ship ("Kohl's
  Deal Days: up to 60% off + extra 25%", "Ulta: extra 20% off sitewide with a code", "Target Circle Deal Days: 40%
  off women's shoes"). One card per sale, with the store's logo, the offer, the code, when it ends, its conditions,
  and the post it came from.
- **Stores:** every online store with something on right now in your categories, as logo tiles. A tile opens the
  store: its sales, its product deals from the Online tab, and a link to its site.

The existing **Online** tab is unchanged. It holds single products (one product, one price); the new tabs hold sales on
many products, which the Online pipeline reads today and throws away ("storewide sale or many products"). Every finding
below was checked live on **Oct 6, 2026** with Slomp's own reader (honest User-Agent, robots.txt honored, bot checks
treated as a refusal, and `SLOMP_ASSISTANT=1`, so sites that turn AI assistants away by name are not read at all).

---

## 1. Requirements

| # | Requirement |
|---|---|
| S1 | A **Sales** tab lists every live sale, code or sale event at an online store that ships, in the chosen industries. |
| S2 | Each sale shows the store, the offer in a few words, the promo code when there is one, when it ends (or that no end was given and when it was posted), its conditions (members only, minimum order, select items, in the app), and a link to its source. |
| S3 | A **Stores** tab lists the online stores with a live sale or product deal in the chosen industries; a store opens to its sales, its product deals and its own site. |
| S4 | Nothing is shown past its end date, and nothing undated is shown more than 7 days after it was posted, unless it is named for a day still ahead ("Black Friday Sale"): then through that day. |
| S5 | Sales sort like every other tab: best deal first, ending soonest, A–Z, Z–A. "Up to" percentages count as ceilings, not promises. |
| S6 | The web page, the API, the CLI and the published site show the same sales. |
| S8 | Movies & Entertainment, a local industry, has sales too: subscriptions, and tickets, passes and memberships, bought online and marked for what they are (4.6). |
| S7 | 200 live tests check accuracy and quality, as for the rest of Slomp. |

| Property | Target | Why |
|---|---|---|
| Fidelity | ≥ 98% of shown sales have the store, offer, code and end date their source states | A wrong code or a dead sale wastes a checkout |
| Freshness | 0 shown past a stated end; 0 evergreen coupon posts (section 2.3) | Deal sites keep old coupon posts in their feeds for months |
| Is a store sale | ≥ 95% are sales on many products at a store you can order from and have shipped (blind judge) | Single products belong in Online; local services, digital stores and gift cards belong nowhere here |
| Cost | Adds about 50 feed requests per 30 minutes, shared by every city | Same politeness rules as v1 |

## 2. What the research found

### 2.1 The feeds Slomp already reads carry store sales

Reading every online industry's feeds (65 feeds, 2,248 posts) found **259 posts about sales on many products** that the
Online pipeline drops: dealnews 116, Hip2Save 109, 9to5Toys 20, Slickdeals 11, The Inventory 3. Examples, all live
that day: *Target Circle Deal Days Women's Shoes Deals: 40% off*, *Kohl's Deal Days Sale: Up to 60% off + extra 25%
off*, *Macy's Star Deals Week: Up to 80% off*, *Best Buy Techtober Headphones Deals: Up to 68% off*, *Woot Wootober
Promo Code: Extra 22% off daily deals*, *Ulta Beauty Sitewide Promo Code: Extra 20% off*, *J.Crew Friends & Family
Sale*, and dozens of brand sales inside Amazon's Prime Big Deal Days.

dealnews marks these posts `dealType = sale` and names the retailer in a field of its own. Its descriptions usually
state the end ("This sale ends October 7") and the code ("Apply promo code "WOOTOBER""). Hip2Save names the store in
the title and the end in the text ("Through October 8th, Kohl's Deal Days..."). Slickdeals names the store's domain.

### 2.2 dealnews has a feed per store

dealnews lists 86 stores in its directory, and each has a feed (`/s{id}/{name}/?rss=1`, 20–50 posts). Of 39 store feeds
read, the ones with the most sales posted in the last 7 days were Target (15), Best Buy (11), Woot (11), Macy's (9),
lululemon (9), Newegg (7) and Costco (7). These feeds catch sales that fall off the busy category feeds. Two other
dealnews listings looked promising and are not used: "Store Events" (`c40`) turned out to be seasonal products
(Halloween decorations), and "Coupons" (`t2`) held 40 posts, 38 of them evergreen coupon posts from May and June.

**A feed's first page is not the feed.** A dealnews feed gives 20 to 25 posts and `&start=N` gives the next ones;
a Hip2Save feed gives 100 and `?paged=2` the next. In a quiet week the first page of a store's feed covers weeks. On
Nov 22, 2026, five days before Black Friday, Macy's 20 posts on dealnews spanned 1.9 days and the 19 behind them
held ten Black Friday sales still running; Costco's Black Friday posts were all on its second page; Hip2Save's 100
posts for women spanned 2.5 days. A sale that leaves the first page is gone from Slomp at the next build, although
it has not ended. So every dealnews and Hip2Save feed (stores, categories, latest, restaurants) is read on while a
page comes back full and still holds a post from the last 30 days, at most two pages further. That day it brought
6,102 posts where the first pages gave 3,182, for about 100 more requests at each site's own pace.

### 2.3 Old coupon posts stay in the feeds

Store feeds keep evergreen coupon posts for months: DSW's feed held 14 "Sitewide Promo Code" posts from May and June,
all "ending" Dec 31; JCPenney's, J.Crew's and Overstock's held promo-code posts 229 to 293 days old. A sale must
therefore be **recent** as well as unexpired: posted within 30 days, and within 7 days when no end is stated.

### 2.4 dealnews end dates: most stated ends are being missed today

Each dealnews post carries an `expires` time. Of 1,127 posts read, **695 had a placeholder**: exactly 90 days after
posting (a few 30 or 7 days), at the posting's own time of day. The other 432 were set by an editor, and only 146 of
those end at 23:59:00, which is the only time `parse_dealnews` treats as stated today. The rest end at 23:59:59, 03:00
or 02:59 Eastern (midnight or 11:59 PM Pacific), 01:00 (midnight Central) and so on. So a real end date is missed
about two times in three, which lets a product deal whose stated end has passed stay in the Online tab for up to 72
hours after posting. The fix is the reverse test: an expiry is stated unless it is a placeholder (posted + 7, 30 or 90
days, within two minutes, allowing for a clock change). It applies to both tabs.

### 2.5 Coupon sites

| Site | Slomp's reader | Verdict |
|---|---|---|
| RetailMeNot, Offers.com, Dealspotr, Knoji, DealCatcher coupons, TechBargains | Bot check | No |
| Slickdeals coupon pages | Bot check (HTTP 410) | No |
| WSJ coupons | Disallowed by robots.txt | No |
| Groupon coupons | Turns away AI assistants by name | No |
| Coupons.com, Savings.com, CouponFollow, Capital One Shopping, TopCashback | Readable | **No.** Codes carry no dates and the pages are written for search ("55% OFF Amazon Promo Codes"); stale codes are exactly the failure the user cares about |
| The Krazy Coupon Lady store pages and RSS | Readable | **No for now.** The RSS dates updated articles by first publication (a "Kohl's Deal Days Oct. 5–8" article is dated June 16), so fresh can't be told from old |

Slomp takes sales from **dated posts written by editors** (dealnews, Hip2Save, Slickdeals, 9to5Toys) and shows a code
only when the post states it.

### 2.6 The stores' own sites

Slomp's reader requested the home page of 102 online stores: **75 readable**, 20 bot checks (Walmart, Kohl's, Macy's,
Wayfair, Etsy, Dick's, adidas, Levi's and others), 3 errors (Chewy and Crocs rate-limited, lululemon 400), and **4 that
turn AI assistants away by name: Amazon, eBay, Advance Auto Parts and RockAuto**. So:

- A store's **logos** come from two places (`scripts/build_logos.py --stores`): its own site's icon where the site can
  be read (a square app icon, for the corner of a sale's picture) and its Wikidata logo on Wikimedia Commons (usually
  a wordmark, for its tile on the Stores tab). Amazon's and eBay's come from Wikidata only. The Wikidata item of each
  store came from Slomp's merchant registry, OpenStreetMap's brand index or the company's own Wikipedia article.
- Confirming each sale on the store's own page is **not** part of this version: a fifth of stores can't be read, and
  the sale's landing page sits behind affiliate redirects. The post's own page is re-read instead (section 4.5).

## 3. What the user sees

```
 Near you 24   Regulars 6   Online 48   Sales 37   Stores 19
 ─────────────────────────────────────────────────────────────
 [All 37] [👕 Fashion 21] [🏡 Home 12] [💻 Tech 9]        Sort ▾
 Store-wide sales, codes and sale events at online stores that ship. The same for every city.
 ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
 │  (picture)   │ │  (picture)   │ │   (logo)     │
 │ ◉ Up to 60%  │ │ ◉ 40% off    │ │ ◉ Extra 20%  │
 │ Kohl's · Ends Thu   │ Target · Ends Wed │ Ulta · Ends Wed │
 │ Deal Days Sale      │ Circle Deal Days  │ Sitewide code   │
 │ Up to 60% off       │ Women's Shoes     │ Extra 20% off   │
 │  + extra 25%        │ 40% off           │ [Code FALL20]   │
 └──────────────┘ └──────────────┘ └──────────────┘
```

- **Sales tab.** Category pills (All, then each chosen industry with sales), a sort menu, and one card per sale: the
  post's picture (the store's logo when there is none) with the store's logo in a corner, the store and when it ends,
  the sale's name, the offer, and up to two tags (the code first). The details view adds the whole offer, the code with
  a **Copy** button, the end date and where it comes from, conditions, shipping, when and where it was posted, and two
  buttons: **Open the deal post** and **Go to <store's site>**.
- **Stores tab.** One tile per store: logo, name, "6 sales · 3 product deals", its best offer, and its soonest end.
  A tile opens the store in place: its logo and a link to its site, then its sales, then its product deals (the same
  cards as the Online tab), with **All stores** to go back.
- **Your card.** A sale can go on the card like any deal: its offer is the price line and its code the note.
- Both tabs appear whenever the search includes an industry with online deals, and say they are the same for every
  city.

## 4. How it works

### 4.1 Components

```
 feeds already read for Online ─┐
 dealnews store feeds (~45) ────┼─► sale posts ─► store ─► offer, code ─► dates ─► industries ─► dedupe
 dealnews latest + popular ─────┤                 (registry)                (live?)                   │
 Slickdeals "sitewide" search ──┘                                                                     ▼
                                    post pages re-read (not expired) ◄────────────────────────── rank, cache
```

- `slomp/data/online_stores.json`: the registry of 122 online stores: name, the spellings deal sites use, the sale
  events only it runs ("Prime Big Deal Days"), domains, dealnews store id (70 have one), the industries it sells,
  whether it is also a brand other stores sell (Nike, Apple), its site and its Wikidata item. `slomp/stores_online.py`
  finds stores by name; the Online tab's product deals carry their store's key too. Logos join it from `logos.json`
  (`o:<store>` the site's icon, `ow:<store>` the Wikidata logo).
- `slomp/sales.py`: the pipeline (`StoreSales`). `models.StoreSale` is one sale.
- `service.sales()`: computed once for the whole state, cached 30 minutes, warmed at start; each request filters by
  industry and by the time of the request. `/api/v1/sales`, and `sales` in `/api/v1/search`.
- The published site: `slomp site build` writes `data/sales.json`; `engine.js` filters it in the browser exactly as
  the server does.

### 4.2 Which posts are sales

A post is a **sale** when dealnews types it `sale` or its title has an offer on many products (a percent or dollars
off, "up to", "extra", BOGO, "sitewide", "everything") together with a sale word (sale, deals, event, promo, code,
coupon, clearance, savings, specials, outlet). It is left out, with a counted reason, when it is:

- **one product at one price** ("Trident Gum 14-Pack: 41 cents"): that is the Online tab's job;
- a **gift card, membership, subscription, credit card, trade-in, sign-up or group discount** (students, teachers,
  military), or travel;
- **not shipped**: in-store only, pickup only, a digital store (PlayStation Store, Nintendo eShop), software, or a local
  service (Great Clips). A registry store ships by definition; another store counts only when its post says it ships.

Those words are looked for in what is on sale, not in what comes with it: once the offer is stated, what follows a
plus is an extra ("Up to 36% off + trade-in offers", "Up to 50% Off + FREE Gift Card Giveaway!").

**A store's event named for a day needs no stated discount.** The largest events of the year are announced without
one ("Kohl's Black Friday Sale Starts at 12am CT!", "Want a Peek at Walmart's Black Friday Deals? Get Ready to Shop
on 11/23!"), and the seventh manual comparison (Nov 22, 2026) found Slomp showing nothing for Walmart, Kohl's or
JCPenney in Black Friday week because of it. A post is such an event when its title names a day of the calendar in
`slomp/days.py` (Black Friday, Cyber Monday, Memorial Day, ...) and a sale (sale, deals, event, savings, specials,
doorbusters, clearance), and either the sale's name is nothing but the event ("Black Friday Sale"), or the store's own
name stands right before the event's ("Walmart's Black Friday Deals"), or the title gives a price in place of a
discount ("... Deals for From $15", "... for Under $50"). The card says "Sale event, no discount stated", or the
price ("From $15"); it ranks after every sale that states a discount, never reaches the home page's biggest deals,
and gives way to a sale of the same store, named for the same day, that does state one: the store's own sale for
that day when there is one, the one whose name names nothing but the day. A day's name on anything else
("FREE Lowe's Black Friday Buckets", a single product's "Black Friday Deal") still states no discount.

Such headlines are often filed under no category Slomp reads ("Target's Black Friday Deals Start 11/22" was on
Hip2Save's front page only), so the sales pipeline also reads Hip2Save's own front-page feed, read on like every
feed (2.2): one post in nine there is in no category feed.

### 4.3 Which store

Strongest evidence first: the source's own retailer field (dealnews), the store's domain in the post (Slickdeals'
`[target.com]`), where the post sends you ("head over to Kohl's"), then a registry store named in the title ("at
Macy's", "on Target.com", "Prime Day" for Amazon). Matching uses the registry's spellings, longest first, as whole
words (Gap Factory before Gap). A store not in the registry is kept under the name the source gives, with a generic
icon, if its post says it ships. A post from a site with no retailer field names such a store itself (Oct 25, 2026):
the title's first capitalized words before a possessive or before event words and a sale word ("PUMA's Stock Up
sale", "Wilson Fall Sale"), or "at X" ("Extra 30% off at Dearfoams"). The name counts only when something is left of
it once event, department and goods words are taken out ("Fall Sale", "Kids' Sale" and "Costume Sale" name no store),
and only when the post links to the name's own website (through affiliate redirects) or, for a name the title starts
with, says it ships. What such a store sells comes from the post: its category, its words, a department its name
gives, or the words learned from its labelled goods (DESIGN.md 4.4).

Many titles lead with the offer and name the store after it (Nov 16, 2026): "Up to 70% Off Comfrt Early Black Friday
Sale", "Buy 1, Get 1 FREE Comfrt Hoodies & Sweatpants", "Up to 80% Off 32 Degrees Clothes". The capitalized words
after the offer name a store when the post links to a website of that very name (whatever the words also mean:
"Mattress Firm", "32 Degrees") or its own words send the reader there ("Hop on over to Comfrt where ..."). That the
post ships is not enough for these: the words after an offer are as often the goods ("Up to 50% Off Stuffed Animals
Sale + Free Shipping"). Words that are goods only together ("Stuffed Animals", "Christmas Tree") name no store
anywhere, and "Offer" is a sale word ("Barnes & Noble Offer: ..."). For each post still left without a store, the
build log says what it had to go on: the name its title could mean, the sites it links to, where it sends readers,
whether it says it ships, and how it begins.

The first build to print that (run 161, Nov 22, 2026) showed that Hip2Save's posts carry no links at all, so there
the post's words are all there is. Four more ways a post names its store, strongest first:

- **A website the title names**: "Extra 20% Off Any Size on FilterKing.com" is at Filter King, spelled as the post
  spells it. A site named for what it sells keeps its ".com": "Blinds.com" is a store, "Blinds" is not.
- **The site the post sends the reader to holds the title's name**: "Hurry over to GiveHugz.co" for the title's
  "Hugz", "Hop on over to Comfrt's Black Friday Sale" for "Comfrt". A site that merely contains a short word of the
  title does not count: the name must begin or end the site's name and be at least half of it.
- **The title names no one**: the store the post sends the reader to ("Hop on over to Minky Couture where ..."),
  when the post says it ships. Not a registry store (those are read first), a deal site, or words of events and
  goods ("head over to the Black Friday Sale").
- **A sale named for the store's own event after the offer**: "Up to 75% Off Laura Geller Early Black Friday Sale ...
  Just $39 Shipped", when the post ships and sends the reader nowhere else. Event words must stand between the name
  and the sale word: goods are seldom given an event of their own, and "Up to 80% Off Soma Sale" alone still needs a
  link or the post's words. A phrase of goods no rule knows could still pass here; the log's "begins" line is how
  that would be seen.

The build on those (run 164, Nov 22, 2026) printed how each post still without a store begins, and five of the
eight named their store in the first sentence, in words Slomp did not read:

- **Any verb before "over to"**: "make your way over to AliExpress.com where ...", "click over to BarefootDreams.com
  for ...". No list of verbs ("head", "hop", "hurry", ...) is ever complete, so any "... over to" counts when what
  follows shows a store is meant: a website, or a name and then "where" and what is there. "Savings carry over to
  January" sends no one anywhere. A name the title also writes is spelled as the title spells it ("Barefoot
  Dreams").
- **The "to" left out**: "hurry over Corkcicle where you can save 30%", after one of the verbs and before "where".
- **A name that starts with a number**: "hurry over to 32 Degrees". The word after the number is the name's
  whatever else it means ("degrees" is otherwise a word of goods). A count of days or of stores is no name ("12
  Days of Deals", "5 Stores").
- **A registry store the title leaves out or misspells**: "lululelmon Black Friday Sale + Free Shipping", whose
  post begins "You don't want to miss the prices during the Lululemon Black Friday Sale!". Last of all, when
  nothing above names a store: the one registry store whose sale the post's first words name by the name the title
  gives the sale. The sale must have a name of its own (event words between the store and the sale word: "the
  Amazon sale" names none), the title must name no store, and a second store's sale leaves it open. The sale is
  then called what the post calls it ("Black Friday Sale").

One reading of the round before was too wide and is narrower now: words that go on after the title's name confirm
it ("Hop on over to Comfrt's Black Friday Sale" for "Comfrt", "... to Minky Couture" for "Minky"), but not when they
are goods only together. "Hurry over to the Stuffed Animals page" had confirmed a store called "Stuffed".

The builds on those (runs 169 to 171, Nov 23 and 24, 2026) left a list of posts that were still running, and four
more wordings:

- **A sale the title names for its store, and the post sends the reader there**: "Our Place Black Friday Sale Gets
  Even Better with an EXTRA Promo Code!", whose post says "head to Our Place". A sale named for its store used to
  need a link or shipping.
- **The website of the title's name, written in the post**: "browse OOFOS.com and score ..." under "Over 55% Off
  OOFOS Sandals", "Novilla.com is offering ..." under "Up to 55% Off Novilla Mattresses". A website of that very
  name is as good as a link to it, and so is an address written into the text (Slickdeals' posts do that). A site
  named for what it sells keeps its ".com", as in a title.
- **A small word or an abbreviation inside a name**: "Life in Lilac", "House of Harlow", "Made by Mary" (in, of, by,
  the, and, de, la, du, between two capitalized words), and "Dr. Martens", "St. John", whose full stop is not the
  name's end. The post's sending words are read to the name's end for these ("Head over to Life in Lilac").
- **A code or "sitewide" instead of shipping**: "Ruggable's Pre-Black Friday Sale" in a post about its promo code
  says nothing of shipping, and a code to enter shows a sale is online as well as shipping does. It counts where the
  title says whose sale it is (a possessive, or an event of the store's own), and for the store a post sends the
  reader to. A bare "Zyntrix Sale" with a code still needs a link or the post's words.

Letting a code stand in for shipping called for a look at what else leads a title, and words of a sale's own name
were being read as stores whenever the post shipped: "Buy More, Save More Sale" as a store called "Buy", "Stock Up
Sale" as "Stock", "Pink Friday Sale" as "Pink". A name is no store's when the sale's name goes on after it: before
a small word ("Stock Up", "Buy More", "Fill a Bag", "Spend & Save") or a weekday ("Pink Friday", "Travel Tuesday").
A possessive is exempt ("PUMA's Stock Up sale"), and so is an offer ("Wilson Up to 50% Off Sale"). "Mix & Match Sale"
and "Lightning Deals" in a post that ships are still read as stores: nothing in their shape tells them from "Barnes &
Noble Offer". The build log now prints every store named this way, which is where one would be seen.

**When, before where.** A post that has ended or is too old is left out before its store is looked for. The posts
left out for want of a store are then all posts that would otherwise be shown: run 169 printed eight of them and
five were from October and August.

### 4.4 The offer, the code and the dates

- **Offer**, read from the title (below: when the title names a sale and leaves the offer out): a firm percent ("40% off everything", "30% to 40% off"), a ceiling ("up to 60%"),
  an extra percent on sale prices ("extra 25%"), dollars off with a threshold ("$10 off $30"), BOGO ("buy 1, get 1 50%
  off", "buy 2, get 1 free"). The card's offer line is written from these parts, so it always agrees with the badge.
- **An offer beside the sale's name.** Hip2Save names the sale and then tells the offer after " | " or " = ", or in a
  parenthesis ("Nordstrom Black Friday Sale is LIVE | Up to 75% Off Baublebar, LEGO, UGG & More", "Target's Black
  Friday Deals Start 11/22 (50% Off Thousands of Gifts!)"); that part used to be dropped as an aside, which it is
  when the offer leads ("40% Off Target Handbags = Styles from $9"). When the title names a sale or a day and states
  no offer before the aside, the aside is read. When the title states none at all, the post's own sentence that sends
  the reader to the store is read ("Through November 29th, head over to Crocs.com where you can score up to 60% off
  select styles during their Black Friday sale"), and the card's details quote it. Either way the offer is one of
  the sale's highlights, so a plain percent is shown as the most the sale gives ("up to"), unless the words say it is
  on everything. The same holds for a list of highlights after a colon ("FREE Poinsettias, BOGO Offers, 70% Off
  Trees & More"): a percent that is not the list's first item is one item's.
- **The sale's name** is the title without the store, the offer and shipping ("Deal Days Shoe Sale"). What stands
  before a colon is the name only when it names something: "Today ONLY: Up to 80% Off 32 Degrees Clothes" is
  "Clothes", not "Today ONLY" (a day is a name: "Black Friday: ..."). A headline about the deal site's own post
  ("Corkcicle Gave Hip2Save Readers an EXCLUSIVE 30% OFF Code!") names no sale, and the card says "Sale". An event
  that states no discount shows the one price its title gives beside its name ("... = Popular Styles from $29
  Shipped": "From $29"). A title that is more than one sentence is read without the writer's comment ("Up to 55%
  Off Novilla Mattresses? Now That's Dreamy!" is "Mattresses"); a sentence stays when it states an offer or a price
  or names a sale, the store or any goods. A headline that goes on after the sale it names ends there: "Black
  Friday Sale Gets Even Better with an EXTRA Promo Code" is the Black Friday Sale, and "PUMA's Stock Up sale slashes
  extra 40% off: Shoes, bags, ..." the Stock Up sale. What goes on stays when it says what is on sale or which wave
  this is ("Black Friday Deals on Toys", "Black Friday Sale Preview").
- **Code**: only a code the post states: after "promo code", "coupon code", "use code" or "with code", quoted, or in
  capitals and digits ("TAKE25"). "No promo code needed" is not a code. The code's own sentence decides whether it is
  this sale's: a code for cardholders ("J.Crew Credit Card holders can stack an extra 20% off with code CARDLOVE"), for
  another store, or for a day that has passed ("today, October 3rd only") is not shown; one that only buys delivery
  says so ("for free delivery"); one for new customers adds that condition.
- **Conditions**: members only (Prime, Target Circle, rewards), minimum order, select items, exclusions, new
  customers, in the app, online only. **Shipping**: "free shipping w/ $35" becomes "Free shipping on $35+".
- **End**: the dealnews expiry when it is not the placeholder (2.4); else the post's words ("ends October 7",
  "through October 8th", "today only", "Deals End TONIGHT", "Last Day!", "10/6–10/7"), read as the end of that day in
  Central time; else none. **Start**: "starts November 23", and from the title "Deals Start 11/22", "Get Ready to
  Shop on 11/23", "Starts Monday", "Starts at 12am CT" (the midnight after the post).
- **The day a sale is named for** (`slomp/days.py`: the United States' shopping days and when each falls). A sale
  named for a day that had not passed when it was posted ("Belk Black Friday Sale", posted November 14) and stating
  no end lasts through that day at least: its name says so. A sale named as the wave before a day ("Early Black
  Friday Sale", "Pre-", "Preview", "Countdown to", "Warm-Up") says only that it ends before it, so the 7 days stand.
  A stated end always wins. Reading the post's page again cannot settle this: on November 22, 2026 the pages of
  three dealnews sales that had ended by their own dates were still up, unmarked.
- **Live**, at the moment of the search: not past its end; posted within 30 days; posted within 7 days if it has no
  end, or not past the day it is named for; starting within the next 7 days.

### 4.5 Industries, duplicates, checks and order

- **Industries** come from the post (dealnews' category, the feed, keywords), as in the Online tab, kept to what the
  store sells. A store-wide sale or event (a name made only of event words, such as "Deal Days Sale", or "sitewide")
  counts for the kinds of goods its post names, kept to what the store sells; for the store's whole line when the post
  names none. "Everything" makes a sale store-wide only when the sale names nothing narrower: "LEGO Deal Days Event: 40%
  off everything" is everything LEGO. (The first version gave a store-wide event every industry the store sells, which
  put an AliExpress Halloween sale under Pets; the first live run caught it.) A store the registry doesn't list has
  no line to keep its sale to, and its own name is not what it sells: once named, "Barefoot Dreams Throws" was filed
  under Grocery for the wine and "32 Degrees Clothes" under Beauty for the deodorant. Such a store's title is read
  without its name first, and with it only when nothing else places the sale ("Up to 60% Off at Mattress Firm").
  When neither the title, the feed nor the category's words say, the department the source files the post under
  does ("Home Deals & Tips").
- **Duplicates**: the same sale posted twice (dealnews and Hip2Save both cover Kohl's Deal Days) is one card; the
  dealnews post leads and the others are listed. Two posts are the same sale when the store, the badge and the end
  day are the same, they are named for the same day, and their names say the same thing once that day is set aside
  (`sales.sale_said`). The day a sale is named for is when, not what. Names used to be the same when they shared
  60% of their words, the day's among them, and in Black Friday week most names are "<something> Black Friday
  Deals": Gillette's, Vitamix's, Ninja's and Dyson's sales at Amazon were listed under GearWrench's, and 16 of
  Fanatics' under its storewide one. Of the 180 posts under another sale's card on Nov 27, 103 were sales of
  something else (VERIFICATION.md, run 180). So what is left of a name must be the same words: without the day,
  the store's own name, a word that sets a sale before its day ("Early"), the year, and "sale", "deals" or
  "event"; a plural is its singular. "Black Friday Sale" and "Kohl's Black Friday Deals 2026" are one sale; the store's own
  sale and its sale on jackets are two, and so are its Black Friday and Cyber Monday sales. The end day is the one
  a shopper would say (4.6). The cost: the same sale under two unlike names ("Christmas String Lights Sale",
  "Christmas Lights") is two cards, each linked to its own post, where it used to be one. A subscription or a
  ticket is compared in its own way (4.6): two channels at one price are two offers.
- **Checks**: each sale's post page is re-read (cached an hour) and the sale is dropped when the page is gone,
  redirects elsewhere, or is marked expired.
- **Order**: best deal first ranks by what a shopper can count on: a firm percent counts in full, an "up to" ceiling
  at half its distance above the firm part, BOGO as its per-item saving, "$10 off $30" as half of a third. Members-only
  and select-items sales rank a little lower.

### 4.6 Entertainment bought online: subscriptions, tickets and passes

Movies & Entertainment was discount days at places near you and nothing else, and sales were at stores that ship, so
a subscription or a ticket was left out twice over ("a subscription", "digital, not shipped", "a local service"). In
Black Friday week of 2026 a search by hand found 30 entertainment offers, 15 of them subscriptions and 9 tickets,
passes and memberships, and Slomp showed none (VERIFICATION.md, "The second pass"). They are listed now
(`slomp/entertainment.py`), on the Sales tab under Movies & Entertainment, each marked **Subscription** or **Tickets
& passes**.

- **Which posts.** The source says what a post is, not a list of services. dealnews files them under Streaming
  Services (and the two categories beneath it), Movie Tickets and Things to Do, and Slomp reads those three feeds; a
  post of any feed under one of those categories is one. A post from a site that gives no category (Slickdeals,
  Hip2Save) is one only when its title says so in plain words: a streaming service priced by the month or called a
  subscription ("... Streaming Service Plan $1/Month"), or tickets, admission or a season pass ("Movie Ticket
  Offer"). "Paramount+ Only $2.99/Month" from such a site says neither and is not read; that is the cost of naming
  no service.
- **What stays out.** Gift cards, as everywhere in Slomp. An offer for one group of people (students, teachers, the
  military). Under the ticket categories, goods that ship (a roll of paper tickets, a board game). Under Streaming
  Services, one price or "free" with no term in the title: a film to buy, a channel that is always free. A post that
  states no price, no discount and nothing free ("Sign Up Now"), and one whose seller is not named.
- **A store's sale filed under a subscription category** is not a subscription. dealnews put "Musician's Friend
  Black Friday Deals: Up to 60% off + free shipping" under Streaming Services, and the second build listed it as
  one. A post there that states a percent or dollars off and no price is a subscription when its title or its own
  words name one (a subscription, a membership, a plan, a trial, a term): "MasterClass Pre-Black Friday Sale: 50%
  off" says "50% off the first year of a membership". One that names none is judged as any store's sale is.
  Shipping settles nothing: dealnews ends a streaming plan's title with "+ free shipping" too.
- **The offer** is read from the title: a price by the month or year with its term ("$5.49 a month for 12 months",
  badge "$5.49/mo"; "From $2.99/mo"), one price ("$36", "$45 for 6 months"), a percent or dollars off as for any sale,
  or "Free". When the post gives the regular price ("down from $10.99", "versus the regular $8.99 monthly price") the
  offer says so and the saving ranks the card; failing that, a percent the post states ("takes 75% off STARZ
  subscriptions"). The card's details quote the sentence. A price with nothing to compare it to ranks last, as a
  store's event with no discount does.
- **The seller** is the source's own (dealnews' store field): the service, or who sells it (Amazon for a Prime Video
  channel, Giftory for an AMC ticket package). The name keeps the title's words, without the price. Slickdeals gives a
  store it does not know as its web address, and the first build showed a card sold by "disneyplus.com". The post
  writes the name beside the address ("Disney Plus [disneyplus.com] is offering ..."), and that name is shown when its
  letters spell the address; a product's name beside a link to it does not. Then one spelling for a seller across a
  build: names that are the same letters, with "+" read as "plus" ("Disney+", "Disney Plus", "disneyplus.com"), are
  one seller, written as the best-ranked source writes it, a name before an address.
- **The same offer posted more than once** is one card when the seller, the badge and the end day are the same and
  the names say the same thing for the same term. What the post calls the offer ("Trial", "Subscription", "Offer",
  "Plan", "Streaming") and the day it is named for are set aside, and so is the seller's own name; the service, the
  tier and the term are not. The term is read from the name or the offer line, in months. dealnews posted Amazon
  Music Unlimited's three free months as a "3-Month Trial", a "3-Month Subscription" and a "Black Friday Offer: 3
  months", and the first build showed three cards. "... STARZ ..." and "... Paramount+ ..." at one price stay two,
  and so do three months and six.
- **Two sources, one offer.** Compared that closely, two posts are the same offer though their sources put it a
  little differently: a price a cent apart is one source rounding the other's ($5.49 a month at dealnews is
  "$5.50/Month" at Slickdeals), and an end only one of them gives is that offer's end. The second build showed
  Prime Video's AMC+, MGM+ and STARZ bundle twice for want of this. The end day is the one a shopper would say: an
  end in the small hours in Texas belongs to the day before, as the page shows it. dealnews gave one offer's end as
  11:59 PM Eastern on November 30 in one post and as 3 AM Eastern on December 1, midnight Pacific that night, in
  another, and the offer stood twice. A store's sale is held to the same badge and to the same end day, read the
  same way (4.5).
- **When**: as for any sale (4.4). A plan priced "through December 31" and posted in August is past the 30 days and
  not shown: it is the standing price by then, not a deal.
- **Where it shows.** An industry now says two things: `online` (product deals and sales at stores that ship) and
  whether it has sales at all (`sales`: the online industries and Movies & Entertainment). The API, the engine and
  the page ask the second for the Sales and Stores tabs, so choosing only Movies & Entertainment gives Near you,
  Regulars, Sales and Stores, and no Online tab. These offers are not among the home page's biggest deals.

**A place's own sale, read from its own page.** A place's sale on its own tickets is on no deal site: in Black Friday
week of 2026 Six Flags' 2027 pass, SeaWorld San Antonio's sale, Texas Tides' and two zoos' membership offers were on
their own pages only. Slomp reads those pages itself, on every build (`slomp/entertainment.py`, "a venue's own page").

- **Where to look** is a list, `slomp/data/venue_pages.json`: a place in Texas, its city, and the page where it sells
  its tickets, passes or memberships. The list never says what an offer is. A sale's own page that one of those pages
  links to is read too (same site, same section of it, a path that names a sale: "black-friday-deal",
  "special-offers", "promotions"; not one for groups, the military, events or hotel packages), three at most.
- **The page is read block by block**, as it is laid out: a heading, a tile's label and a paragraph are each a line.
  Read as one run of words, a perk sits right beside the next pass's name ("10% off in our Cafe New Pass $59"), and
  a menu's "Military Offers" sits beside the headline. What a percent is off is settled by its own line and the
  lines touching it.
- **What is a sale.** A saving whose own line says it is on a ticket, a pass or a membership ("Save up to 55% on
  Tickets, Passes and More!", "50% Off Texas Annual Pass", "save 10% on membership"). A line that states a percent
  and nothing more, beside the tile's label that names the ticket ("Single-Day Ticket" over "Black Friday: Save up to
  50%"; "20% off + 2 free months" over "Portal Pass Supremium"; a was and a now, or the same badge, may sit between).
  A line that names the ticket's own sale ("Black Friday Annual Pass Sale: 25% off a Whole Year of Fun"). And a
  price for a named pass where its line or the heading over it speaks of a sale ("Get a 2027 Silver Pass for $69.
  Ends 11/27."); a price by the month is a payment plan and is not read.
- **What is a perk.** The same pages list what a pass holder gets, and none of that is a sale: a percent off anything
  else (food, the shop, parking, "Quick Queue"); a ticket for whoever comes along, or the second of two ("for friends
  and family who visit with you", "Bring-A-Friend", "a second General Admission ticket"); a saving on tickets that
  sits in a list of perks (the line beside it is a perk, or the heading over it says benefits, perks or includes: a
  member's "15% off any attraction ticket purchase"); a table of what each tier gets (two percents side by side);
  and an offer for one group of people (the military, seniors, students), as everywhere in Entertainment. Half off
  the second of two tickets is not half off either: when a page says a percent is off "a second" ticket, its
  headline's looser "up to 50% off tickets" is not shown.
- **The card.** One for a place: the biggest saving its pages state that is still on, quoted in the page's words and
  linked to that page, with the place's name in full and its city (`StoreSale.own_site`, `.city`). It says "Up to"
  when the page does, or when the pages state several savings and the biggest names no ticket; a saving on a named
  pass keeps its figure. Of two statements of the same saving, the one that gives an end date or names its day
  leads, then the one higher on the page. A place that could not be read is not counted among the deal sites that
  could not be reached; under Movies & Entertainment the tab's notes name it.
- **When.** The end the page states, on the offer's line, the heading over it or the line under it ("deal ends
  December 1st!"). With no end, a sale named for a day lasts through it (4.4). Not shown: an offer whose stated end
  has passed, one that names a year gone by, and one named for a day that is not in the coming week with no end
  stated, which is a page left up. An offer with no end and no day is shown while the page states it: the page is
  read again on every build, so there is no post to go stale.
- **What can't be read is reported**, never worked around: robots.txt (the Fort Worth Zoo turns AI assistants away
  by name, so a run an assistant starts does not read it), a bot check, an error. The build's sources list has a
  line for each place.

What this still does not reach: a place that is not on the list, a sale a place announces only by email or on
social media, and one its page words in a way these rules do not read (SeaWorld's "Save Over 35%" on a pass is
passed over; its "Save Up to 50% on Tickets" is read).

## 5. Trade-offs

| Decision | Chosen | Alternative | Why |
|---|---|---|---|
| Where sales come from | Dated editor posts (dealnews, Hip2Save, Slickdeals, 9to5Toys) | Coupon aggregators | Aggregator codes carry no dates; accuracy first |
| Two tabs | Sales and Stores | One tab with a store strip | The request names both; each stays simple |
| Same for every city | Yes, and the tabs say so | Ask for a city first | Online stores ship anywhere in Texas |
| Store confirmation | The post page, re-read | The store's own sale page | A fifth of stores block readers; landing pages sit behind affiliate redirects |
| Undated sales | Shown for 7 days after posting | Dropped | Many real sales give no end ("while supplies last"); the card says when it was posted |
| "Up to" | Ranked at half its distance above the firm part | Ranked at face value | A ceiling on a few items is not 80% off |

## 6. Verification

`slomp verify --iteration N --plan sales`: 200 live tests per run, re-checked against the sources themselves.

| Test | Count | Passes when |
|---|---|---|
| S-SRC source fidelity | 50 | The post page, read now, shows the same store, offer and code, and is not marked expired |
| S-END dates | 30 | The end Slomp shows is the one the post or dealnews states; the sale is live now |
| S-STORE store | 25 | The source's retailer field, domain or text names the store Slomp shows |
| S-SHIP ships (blind judge) | 20 | A store you can order from and have shipped, not a local service, digital store or gift card |
| S-MANY a sale (blind judge) | 20 | A sale on many products, not one product |
| S-IND industry (blind judge) | 20 | The judge's industry is one Slomp assigned |
| S-OFFER offer and code | 20 | The badge, offer line and code, recomputed from the post's title and text, match |
| S-QUAL quality | 15 | No duplicates, nothing stale or ended, order follows the score, store counts add up |

A test that can't be made is inconclusive and replaced, as in the other plans.

Results: [VERIFICATION.md, Online stores' sales](VERIFICATION.md#online-stores-sales).

**What a build's log says of the sales**, so that a build can be checked from its log alone:

- how many sales at how many stores, and how the stores were decided (the source's store field, the title, the
  post's words), counted;
- every sale at a store Slomp keeps no entry for that the post's own words named: the store, the title, how it was
  decided and its industries. These are the readings that can go wrong, so each one is printed (up to 40);
- the posts left out, by reason, and for the reasons that may hide a real sale (no store, no industry, no word of
  shipping) eight of the posts, each with what it had to go on;
- for all the deal feeds together: how many posts each site gave from how many feeds, how many pages were read past
  a first page, and the feeds or later pages that could not be read. Two builds' counts can be compared only when
  they read the same posts: run 169 showed 13 fewer promotions than the build before it and nothing said why.

## 7. What was built

| Part | Where |
|---|---|
| The store registry and finding stores by name | `backend/slomp/data/online_stores.json`, `backend/slomp/stores_online.py` |
| The pipeline: posts to sales, the offer, code, dates, industries, duplicates, page checks, order | `backend/slomp/sales.py`, `models.StoreSale` |
| dealnews end dates read correctly (both tabs) | `sources/feeds.dealnews_stated` |
| API, CLI, warm-up | `/api/v1/sales`, `sales` in `/api/v1/search`; `slomp sales -i …`; `SlompService.sales` |
| The page: Sales and Stores tabs, store pages, a sale's details with Copy code, Your card | `backend/slomp/static/index.html` |
| The published site | `data/sales.json` from `slomp site build`; `engine.js` filters it per search |
| Logos | `python scripts/build_logos.py --stores` (`o:` site icons, `ow:` Wikidata logos in `logos.json`) |
| Tests | `backend/tests/test_sales.py` (offline); `slomp verify --plan sales` (live); `site_check` compares sales |

Smaller changes made along the way: Slomp's HTTP client now treats a site that redirects in a loop as unreadable
instead of crashing, Wikimedia is read at most one picture every two seconds (faster gets HTTP 429), and a few
keyword rules were added (pet supplements, toy lines whose names say "baby").

