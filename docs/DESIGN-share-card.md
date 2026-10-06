# Your card: design

**Request (Oct 6, 2026):** an "Add to card" button that puts deals on a card, which can be shared with other people
as a JPG or PNG. The card empties at the end of the day.

## 1. What the user sees

- Every deal, in all three tabs, has a small **+** button on its tile ("Add to card"). It turns into a check once the
  deal is on the card, and tapping it again takes the deal off. The details view has the same button in words.
- Once the card holds a deal, a **Your card** button with the count floats at the bottom right of the page.
- **Your card** opens a sheet with a preview of the image that will be shared, the deals on it (each can be removed),
  and four actions: **Share** (the phone's or computer's own share menu: Messages, WhatsApp, Mail, Save to Photos...),
  **Save PNG**, **Save JPG** and **Clear**. Where the browser can't share files (Firefox on a computer), Share is
  left out and the two save buttons remain.
- The sheet says when the card empties: at midnight, by the clock of the device it's on.

## 2. The image

One picture, 1,080 px wide (the width most apps show at full size), drawn on a canvas in the browser:

```
┌───────────────────────────────────────────────┐
│ ◆ Slomp   My deals · Tuesday, October 6        │   header in the brand color
│           near Austin, TX                      │
├───────────────────────────────────────────────┤
│ ┌──────┐  Walgreens · 1.2 mi from Austin       │
│ │ pic  │  Arm & Hammer Laundry Care            │   one row per deal: the ad's own picture (or the
│ │ 72%  │  3 for $7.49  $2.50 each              │   company's logo, or the category's icon), its
│ └──────┘  Ends Sat, Oct 10                     │   badge, where, what, price, when
│   ...                                          │
├───────────────────────────────────────────────┤
│ Found with Slomp · homiejhan.github.io/slomp   │
└───────────────────────────────────────────────┘
```

- Up to 12 deals, so the picture stays readable on a phone. Type is at least 26 px in the image.
- **Pictures.** A canvas that has drawn another site's picture can't be saved unless that site allows it (CORS).
  Checked on Oct 6, 2026: Flipp's picture server (every weekly-ad picture), dealnews, Hip2Save, Slickdeals and
  Wikimedia (many company logos) send `Access-Control-Allow-Origin: *`; most companies' own sites do not. Each
  picture is loaded in "anonymous" mode; one that doesn't load that way is drawn as the category's icon instead,
  so the image can always be saved. A weekly ad's product-card picture is clipped to the product, as on the page.
- **JPG** gets a solid background (JPG has no transparency); **PNG** is the default for sharing because it keeps text
  sharp.

## 3. Storage and the daily reset

- The card lives in the browser (`localStorage`, key `slomp.card`): `{day, items}`, where `day` is the local date it
  was started. Nothing is sent anywhere; on the published site, as on `slomp serve`, the card is per device.
- Each deal is stored as it looked when added (title, place, price, badge, dates, picture), so the card doesn't
  change when the site's data is rebuilt, and a deal added from a search in another city keeps that city.
- **Reset:** when the page opens, when it comes back into view, and at the next midnight while it stays open, a card
  whose `day` is not today is emptied. A deal can't be added to yesterday's card.
- Storage can be unavailable (private browsing with storage blocked): the card then works for the visit and is
  simply not kept.

## 4. Sharing

`navigator.share({files: [image]})` where `navigator.canShare({files})` says yes: Safari on iPhone, iPad and Mac,
Chrome and Edge on Android and on computers (Chrome 128+), Firefox on Android. Firefox on computers has it behind a
flag, so it gets the save buttons only. The image is named `slomp-deals-YYYY-MM-DD.png` (or `.jpg`).

## 5. Verification

In the browser, on the published-site build and on `slomp serve`: add and remove deals from each tab and from the
details view; the count; the card's image for 1, 6 and 12 deals; PNG and JPG saved, with the right type and size and
a canvas that was not tainted; a deal whose picture can't be used falls back to its icon; the card emptying when the
day changes (simulated) and at midnight; phone width; dark mode; no console errors.

**Done on Oct 6, 2026**, in the browser, on the site's build and on `slomp serve`:

- Adding and removing from the + buttons in all three tabs and from the details view; the count; the button hidden
  while the card is empty; a 13th deal refused with a message.
- The picture for 2, 4, 6, 7 and 12 deals (1,080 × 3,664 px for 12): PNG and JPG made, with the right types and file
  names, so no picture tainted the canvas. Flipp's photos, dealnews' and a company logo drawn; deals without a usable
  picture drawn with their icon.
- Found and fixed while testing: a photo the page had already shown came back from the browser's cache without the
  permission to draw it, so it fell back to the icon. A photo that fails is now fetched once more, afresh.
- Share: where the browser can share files, Share hands the PNG to the share menu (simulated in the test browser,
  which can't share); elsewhere only the two save buttons show.
- The daily reset: a card saved on an earlier day is empty when the page opens; the step the midnight timer and the
  "page back in view" check run empties it, hides the button and clears the ✓ marks.
- Speed: drawing 12 deals took 4.3 s when the photos were loaded on opening; loading each one when its deal is added
  brought it to about a quarter of a second.
- Phone width, light and dark themes, no console errors.
