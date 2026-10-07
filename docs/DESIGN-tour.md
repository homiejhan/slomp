# Guided tour: design

**Request (Oct 6, 2026):** a concise guided tour for people who have never seen the site, which can also be started
again with a button.

## When it shows

- **First visit:** it opens by itself once the page is ready (after the results, when the visit starts from a shared
  link). Finishing it, skipping it or closing it marks it seen in this browser (`localStorage`, `slomp.toured`), so it
  doesn't open again by itself. Where storage is blocked, it never opens by itself, so it can't nag on every visit.
- **Any time:** a **Tour** button in the header starts it again.

## The steps

Six short steps, one sentence each. Each one highlights one part of the page and dims the rest.

| # | Points at | Says |
|---|---|---|
| 1 | nothing (centered) | What Slomp is: this week's deals near any Texas city, deals that repeat every week, the biggest discounts online |
| 2 | the city box | Type a few letters of any Texas city |
| 3 | the categories | Tap what you're shopping for, and choose how far you'll go |
| 4 | Find deals (or the tabs, once there are results) | Deals come in tabs: Near you, Regulars and the online ones (worded without a count, so a new tab doesn't make it wrong) |
| 5 | a deal's + (or a small picture of one, before any search) | Put deals on your card and share it as a picture; it empties at midnight |
| 6 | the Tour button | Tap it to see this again |

The tour explains and points; it never searches or picks a city for the person.

## How it's built

- One `<dialog>` opened with `showModal()` holds the step's words and buttons: focus stays in it, the page behind
  can't be clicked, and Esc closes it. Its own backdrop is transparent; a separate box drawn around the highlighted
  element dims everything else with a large shadow.
- The highlighted element is scrolled into view, and the box and the words are placed again when the window is resized
  or scrolled. The words go below the element, or above it when there isn't room, kept inside the screen on a phone.
- Keys: Enter or → for next, ← for back, Esc to close. A counter shows "2 of 6". Animation is off for people who ask
  for reduced motion.
- It works the same on the published site and on `slomp serve`.

## Checked

Checked in the browser on Oct 6, 2026: it opens by itself on a first visit, after the welcome or after a shared link's
results, and not on the next visit; Next, Back, Skip, Esc and the arrow keys; at desktop and phone widths, with and
without results, every step's box is on screen and clear of what it points at (steps 4 and 5 point at the real tabs and
+ button once there are results); the Tour button; no console errors. The header keeps the button on the first line at
phone width, with the tagline below.
