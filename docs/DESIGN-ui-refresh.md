# Friendlier, more visual page, and a logo: design

**Request (Oct 7, 2026):** the page reads a little robotic. Make it more appealing, less information-heavy and more
digestible, driven by visuals: only the necessary details at face value, with dropdowns for the rest. Also create a
nice, simple logo.

## What reads as robotic today

Seen on the live page on Oct 7 (Austin, 25 mi, six categories; 1,041 nearby deals, 120 regulars, 67 online, 156 sales,
45 stores):

1. **Cards say too much.** A nearby deal shows the store and distance, a two-line name, the price, a note ("save
   $199.99 per the ad"), the dates and up to three tags ("vs. list price", "rewards price", "+2"). A regular deal is
   denser still: a full sentence as its title ("Kids Bowl Free: 2 free games of bowling for kids 15 and under, Monday
   to Friday until 5 pm"), the offer again ("Kids bowl free"), the schedule, "until Oct 31", an evidence tag and the
   first condition.
2. **Explanations everywhere.** Each tab opens with a sentence about how it works ("Deals that repeat every week,
   within 25 mi of Austin. Each one says how Slomp knows about it."), and ends with fine print, "What Slomp left out,
   and why" and a long footer.
3. **The details popup is a form.** Every fact is a labeled row, all shown at once ("Discount: The ad states this
   saving but not the regular price it is measured from.").
4. **The words talk about the machine** ("Slomp reads…", "measured against", "per the ad", "as published for").
5. **The look is flat:** one muted plum, gray text, every card alike; the mark is a generic price tag.

## Principles

- **Face value is what you need to decide at a glance:** the picture, how much you save (the badge), the price, what
  it is (one or two lines), where (store and distance) and when it ends. Nothing else.
- **Everything else is one tap away, in dropdowns.** Nothing is deleted: the facts, the evidence for regular deals and
  the price comparisons all stay, collapsed.
- **Pictures and small icons do the talking:** a pin for distance, a clock for the end date, a check seal for a deal
  the company's own site confirms, a dashed chip for a code. Color carries urgency (red "Ends today").
- **Short, friendly words**, written to the reader ("we checked", "ends Sat"), not about the system.
- **Every existing behavior keeps working:** tabs, sorting, day picker, store pages, codes, the card and its picture,
  the tour, keyboard use, the published site.

## The pieces

### Logo

A drop with a price tag's hole near its tip: "slomp" is the sound of something dropping, like a price, and the hole
makes it a tag. In the wordmark the drop is the "o": **sl●mp**. The letters are drawn as rounded single strokes in
SVG (no font needed, so it looks the same everywhere); the drop is a plum gradient. The drop alone is the browser-tab
icon, and the logo heads the shared card picture.

The files are in `docs/logo/`: the logo (`slomp-logo.svg`, and `slomp-logo-white.svg` for dark backgrounds), the
drop alone (`slomp-mark.svg`), an app icon (`slomp-icon.svg`: the white drop on the gradient), and PNG copies
(`slomp-logo.png`, `slomp-logo-white.png` at 1280 × 600, `slomp-icon-512.png`).

### Header and search

- The logo, a one-line tagline ("This week's deals near you and online."), and the Tour button.
- Categories become round picture tiles, one tint per category, with a check on the chosen ones. On a phone they are
  one row that scrolls sideways.
- Distance and Find deals become rounded pills; Find deals uses the brand gradient.

### Welcome (before a search)

A headline, one line of instruction, three picture tiles for what you get (store ads, regulars, online deals and
sales) and the popular cities. No paragraph. (Since Oct 7 the popular cities come right after the instruction, and the
biggest deals that need no city sit between them and the tiles: [DESIGN-top-deals.md](DESIGN-top-deals.md).)

### Results

- **Tabs** are a pill bar with an icon per tab and a count; the chosen tab is filled. On a phone the bar scrolls
  sideways and keeps the chosen tab in sight (as before).
- **Under the tabs:** the category filter, two small chips for where and when ("Within 25 mi of Austin", "Oct 7–13"),
  and Sort. The sentences that explained each tab move into an **"About these deals"** dropdown at the bottom of the
  tab, with the fine print and the list of what was left out.
- **Deal cards** (nearby, online, sales): a square picture with the badge and the + button, then the price (big), the
  name (two lines at most), and one line with the store, the distance and the end. At most one condition shows on the
  card, and only one that changes whether you can get the price: a membership or rewards price, a coupon, a price
  that has changed, or out of stock. Online deals whose discount Slomp checked against other stores get a small
  "✓ Checked" seal. A sale shows its code on the card, since that is what you need at the register.
- **Regular-deal cards:** the company's logo; the offer in a few words as the headline, in plum ("Half price",
  "BOGO", "Kids bowl free", "$12.99"); the deal's own words in two lines; the store with a ✓ seal when the company's
  site confirms it; and the schedule as one chip ("Mon–Thu · 3–6 pm").
- **Store tiles:** the logo, the name, the best offer as a badge, and the counts in small type.

### Details popup

Tapping a card opens the same popup as today, rebuilt as a hero plus dropdowns:

- **Hero:** the picture; the store; the name; the price with its badge; two or three chips (where, when, the code
  with a Copy button); and the buttons (see it in the ad or post, the store's page, add to card).
- **Dropdowns, all closed at first:** *Details* (dates, address, conditions, the offer in full), *About this price*
  (what the discount is measured against, in plain words, and the store check), *Compare prices* (online deals: other
  stores' prices), *How we know* (regular deals: every source, with its quote), *Where this comes from* (sales and
  online deals: the deal site, when it was posted, other sites that posted it).
- On a phone the popup rises from the bottom as a sheet.

### Footer

One line ("Prices come from store ads and deal sites and can change. Check before you go.") with the sources in a
dropdown; the OpenStreetMap credit stays visible.

## Look

- Rounded corners (18–24 px), soft shadows instead of hard borders, more room between cards.
- Plum stays the brand color, slightly brighter (#8a2c72), with a plum gradient (#b13f91 → #6e2459) for badges, the
  chosen tab, the main button and the logo; white text on it keeps at least 5:1 contrast.
- Headings, prices and badges use the system's rounded font where there is one (Safari on Apple devices), else the
  system font. No web fonts are loaded.
- Dark mode gets the same treatment; picture tiles stay light in both, because product cut-outs are on white.

## What must keep working

The tour's targets (`.combo`, the `#chips` fieldset, `#results .tabs`, `#results [data-add]`, `#tour-btn`, `#go`);
the Sales and Stores tabs' hooks (`.card[data-store]`, `[data-store-back]`, `[data-copy]`, `[data-card-toggle]`, the
image fallbacks for `.slogo` and `.lchip`, contain-fit for `.thumb.logo` and `.lchip.wide`); `saleSnapshot()` and
`cardKey()`; the + buttons and the card; and the `<script>` marker that the published site's build inserts `engine.js`
before.

## How it's checked

In the browser, on `slomp serve` and on a locally built copy of the published site: every tab at desktop and phone
widths, light and dark; every kind of details popup with its dropdowns; keyboard use (cards, dropdowns, tabs, the
category tiles); the tour's six steps; the card and its picture; a sale's code copy and a store page; no console
errors. The test suite runs, including the site build's check for the script marker. The data and `engine.js` don't
change, so the published site's parity check is not affected.

**Checked on Oct 7, 2026** (Austin, 25 mi, six categories, on `slomp serve`; Buda on a local copy of the published
site, whose ads come from Kyle's): at 1280 px and at a 390 px phone, light and dark, every tab renders with no console
errors; the details popups for a nearby deal, a regular deal, an online deal and a sale with a code open with all
dropdowns closed and show their facts when opened; on a phone the popup and the card rise from the bottom as sheets;
Enter on a focused card opens its details; a category tile toggles on and off; an empty category shows its empty
state and buttons; three deals (nearby, regular, sale) go on the card and its picture draws with the new logo; the
tour's six steps each highlight their target with the words on screen and clear of it; the published-site copy shows
the "Ads from Kyle" chip, the update time and the About dropdown with what was left out. The 187 tests pass.
