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
| S4 | Nothing is shown past its end date, and nothing undated is shown more than 7 days after it was posted. |
| S5 | Sales sort like every other tab: best deal first, ending soonest, A–Z, Z–A. "Up to" percentages count as ceilings, not promises. |
| S6 | The web page, the API, the CLI and the published site show the same sales. |
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

### 4.3 Which store

Strongest evidence first: the source's own retailer field (dealnews), the store's domain in the post (Slickdeals'
`[target.com]`), where the post sends you ("head over to Kohl's"), then a registry store named in the title ("at
Macy's", "on Target.com", "Prime Day" for Amazon). Matching uses the registry's spellings, longest first, as whole
words (Gap Factory before Gap). A store not in the registry is kept under the name the source gives, with a generic
icon, if its post says it ships.

### 4.4 The offer, the code and the dates

- **Offer**, read from the title: a firm percent ("40% off everything", "30% to 40% off"), a ceiling ("up to 60%"),
  an extra percent on sale prices ("extra 25%"), dollars off with a threshold ("$10 off $30"), BOGO ("buy 1, get 1 50%
  off", "buy 2, get 1 free"). The card's offer line is written from these parts, so it always agrees with the badge.
- **Code**: only a code the post states: after "promo code", "coupon code", "use code" or "with code", quoted, or in
  capitals and digits ("TAKE25"). "No promo code needed" is not a code. The code's own sentence decides whether it is
  this sale's: a code for cardholders ("J.Crew Credit Card holders can stack an extra 20% off with code CARDLOVE"), for
  another store, or for a day that has passed ("today, October 3rd only") is not shown; one that only buys delivery
  says so ("for free delivery"); one for new customers adds that condition.
- **Conditions**: members only (Prime, Target Circle, rewards), minimum order, select items, exclusions, new
  customers, in the app, online only. **Shipping**: "free shipping w/ $35" becomes "Free shipping on $35+".
- **End**: the dealnews expiry when it is not the placeholder (2.4); else the post's words ("ends October 7",
  "through October 8th", "today only", "10/6–10/7"), read as the end of that day in Central time; else none.
- **Live**, at the moment of the search: not past its end; posted within 30 days; posted within 7 days if it has no
  end; starting within the next 7 days.

### 4.5 Industries, duplicates, checks and order

- **Industries** come from the post (dealnews' category, the feed, keywords), as in the Online tab, kept to what the
  store sells. A store-wide sale or event (a name made only of event words, such as "Deal Days Sale", or "sitewide")
  counts for the kinds of goods its post names, kept to what the store sells; for the store's whole line when the post
  names none. "Everything" makes a sale store-wide only when the sale names nothing narrower: "LEGO Deal Days Event: 40%
  off everything" is everything LEGO. (The first version gave a store-wide event every industry the store sells, which
  put an AliExpress Halloween sale under Pets; the first live run caught it.)
- **Duplicates**: the same store, offer and end posted twice (dealnews and Hip2Save both cover Kohl's Deal Days) is
  one card; the dealnews post leads and the others are listed.
- **Checks**: each sale's post page is re-read (cached an hour) and the sale is dropped when the page is gone,
  redirects elsewhere, or is marked expired.
- **Order**: best deal first ranks by what a shopper can count on: a firm percent counts in full, an "up to" ceiling
  at half its distance above the firm part, BOGO as its per-item saving, "$10 off $30" as half of a third. Members-only
  and select-items sales rank a little lower.

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

