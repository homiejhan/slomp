/* Slomp's search, for the published site (GitHub Pages).
 *
 * The server answers a search by reading the sources then and there. The published site can't run code on request,
 * so a scheduled build (`slomp site build`, slomp/site.py) reads the sources ahead of time and writes data files, and
 * this script does the rest of each search in the browser: which ads the city gets, the nearest store or branch, the
 * radius, the next 7 days from now in the city's own time zone, duplicates and order. It returns what the server's
 * /api/v1/search returns, so the page itself doesn't change. Each part names the Python it mirrors; the site's
 * parity check (slomp/verify/site_check.py) compares the two. Design: docs/DESIGN-static-site.md.
 */
(function (root) {
"use strict";

const WINDOW_DAYS = 7;                     // config.Settings.window_days
const MAX_RADIUS_MI = 50;                  // sources/stores.py
const EARTH_MI = 3958.8;                   // geo.py
const DAY_KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];
const BASIS_TEXT = {                       // models.py
  market: "vs other stores' current prices (checked by Slomp)",
  store_regular: "vs the store's own regular price",
  editor_compare: "vs other stores, per the deal's editor",
  claimed_savings: "saving stated by the ad; no regular price given",
  history: "vs this product's own price history",
  list: "vs list price / MSRP",
  none: "no regular price given",
};
const terms = t => ({price: null, regular: null, savings: null, pct: null, basis: "none", qty: 1, bundle_price: null,
                     bogo: "", hedge: "", unit: "", conditions: [], promo: false, summary: "", rejected: "", ...t});

/* ---- data files ------------------------------------------------------------------------------------------- */
// meta.json is checked with the server on every search; the other files carry its build time, so one search never
// mixes two builds' files and a new build's files are never hidden behind a browser's copy of the old ones.
let loader = path => fetch("data/" + path + (path === "meta.json" ? "" : "?v=" + encodeURIComponent(meta.built)),
                           path === "meta.json" ? {cache: "no-cache"} : {}).then(r => {
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
});
const memo = new Map();
function load(path) {
  if (!memo.has(path)) {
    memo.set(path, Promise.resolve().then(() => loader(path)).catch(() => {
      memo.delete(path);                   // tried again on the next search
      throw new Error("Slomp's deals couldn't be loaded. Check your connection and try again.");
    }));
  }
  return memo.get(path);
}
// One part of a search whose files can't be loaded leaves the others standing, as a source the server couldn't read.
async function part(res, name, run, empty) {
  try {
    return await run();
  } catch (e) {
    res.sources.push({name, ok: false, error: "couldn't be loaded"});
    return empty;
  }
}

/* ---- time: the city's own zone (geo.py) ------------------------------------------------------------------- */
const formats = {};
function wall(ms, tz) {                    // the date and time on a clock in `tz`
  const f = formats[tz] || (formats[tz] = new Intl.DateTimeFormat("en-US", {timeZone: tz, hourCycle: "h23",
    year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit"}));
  const p = {};
  for (const x of f.formatToParts(new Date(ms))) p[x.type] = x.value;
  return {date: `${p.year}-${p.month}-${p.day}`, h: +p.hour % 24, m: +p.minute, s: +p.second, ms: ((ms % 1000) + 1000) % 1000};
}
function offsetMin(ms, tz) {
  const w = wall(ms, tz), [y, mo, d] = w.date.split("-").map(Number);
  return Math.round((Date.UTC(y, mo - 1, d, w.h, w.m, w.s) - (ms - w.ms)) / 60000);
}
// A clock time in `tz` as a moment, like datetime.combine(day, t, ZoneInfo(tz)).
function zoned(date, time, tz, ms = 0) {
  const [y, mo, d] = date.split("-").map(Number), [h, mi, s] = time.split(":").map(Number);
  const guess = Date.UTC(y, mo - 1, d, h, mi, s || 0) + ms;
  const first = guess - offsetMin(guess, tz) * 60000;
  return guess - offsetMin(first, tz) * 60000;
}
const pad = n => String(n).padStart(2, "0");
function isoIn(ms, tz) {                   // "2026-10-07T17:00:00-05:00", as Python's isoformat() writes it
  const w = wall(ms, tz), off = offsetMin(ms, tz), a = Math.abs(off);
  return `${w.date}T${pad(w.h)}:${pad(w.m)}:${pad(w.s)}${w.ms ? "." + String(w.ms).padStart(3, "0") : ""}` +
    `${off < 0 ? "-" : "+"}${pad(Math.floor(a / 60))}:${pad(a % 60)}`;
}
const secsOf = t => { const [h, m, s] = t.split(":").map(Number); return h * 3600 + m * 60 + (s || 0); };
const toDay = iso => Date.UTC(+iso.slice(0, 4), +iso.slice(5, 7) - 1, +iso.slice(8, 10)) / 864e5;
const addDays = (iso, n) => new Date((toDay(iso) + n) * 864e5).toISOString().slice(0, 10);
const weekday = iso => (new Date(toDay(iso) * 864e5).getUTCDay() + 6) % 7;        // Monday 0, as Python counts
const daysBetween = (a, b, tz) => toDay(wall(b, tz).date) - toDay(wall(a, tz).date);
// `now + timedelta(days=n)` on a zoned datetime: the same clock time n days later.
function plusDays(ms, n, tz) {
  const w = wall(ms, tz);
  return zoned(addDays(w.date, n), `${pad(w.h)}:${pad(w.m)}:${pad(w.s)}`, tz, w.ms);
}
const cmp = (a, b) => a < b ? -1 : a > b ? 1 : 0;   // Python's string order

/* ---- distance (geo.py) ------------------------------------------------------------------------------------ */
function miles(lat1, lon1, lat2, lon2) {
  const rad = Math.PI / 180, p1 = lat1 * rad, p2 = lat2 * rad;
  const a = Math.sin((p2 - p1) / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin((lon2 - lon1) * rad / 2) ** 2;
  return EARTH_MI * 2 * Math.asin(Math.min(1, Math.sqrt(a)));
}
const round1 = x => Number(x.toFixed(1));
const store = (merchant, name, lat, lon, address, d, source, ref) =>
  ({merchant, name, lat, lon, address, distance_mi: round1(d), source, ref});

/* ---- one search ------------------------------------------------------------------------------------------- */
class Result {
  constructor() { this.excluded = new Map(); this.sources = []; }
  add(why, n = 1) { this.excluded.set(why, (this.excluded.get(why) || 0) + n); }
  counts() {                               // Counter.most_common(): biggest first, ties in the order first seen
    return Object.fromEntries([...this.excluded.entries()].sort((a, b) => b[1] - a[1]));
  }
}

// local.LocalDeals.run, for the ads the city's anchor lists (site.py reads them, item by item, ahead of time).
async function weeklyAds(city, wanted, radius, win, res) {
  const tz = city.tz, mountain = tz === "America/Denver";
  const idx = await load("ads/index.json");
  const at = idx.anchors[city.anchor];
  if (!at || !at.ads) {
    res.sources.push({name: "Flipp weekly ads", ok: false, error: (at && at.error) || "no ads were read for this area"});
    return {deals: [], merchants: []};
  }
  res.sources.push({name: "Flipp weekly ads", ok: true, ads: at.ads.length + at.out});
  const when = (o, k) => Date.parse(mountain && o[k + "m"] ? o[k + "m"] : o[k]);
  const ends = o => o.gone ? Math.min(when(o, "vt"), Date.parse(o.gone)) : when(o, "vt");
  if (at.out) res.add("ad outside the 7-day window", at.out);
  const live = [];
  for (const id of at.ads) {
    const f = idx.flyers[id];
    if (ends(f) < win.start || when(f, "vf") > win.end) res.add("ad outside the 7-day window");
    else live.push(id);
  }
  const stores = await load("stores.json");
  res.sources.push({name: "OpenStreetMap stores", ok: true, built: stores.built});
  const nearest = new Map();
  const nearestStore = name => {           // sources/stores.StoreLocator.near: the nearest within 50 mi
    if (!nearest.has(name)) {
      let best = null;
      for (const r of stores.merchants[name] || []) {
        const d = round1(miles(city.lat, city.lon, r[0], r[1]));
        if (d <= MAX_RADIUS_MI && (!best || d < best.distance_mi)) best = store(name, r[2], r[0], r[1], r[3], d, "osm", r[4]);
      }
      nearest.set(name, best);
    }
    return nearest.get(name);
  };

  const ads = await Promise.all(live.map(id => load(`ads/${id}.json`)));
  const candidates = [], seen = new Map();
  for (const ad of ads) {
    for (const [why, n] of Object.entries(ad.excluded)) res.add(why, n);
    for (const row of ad.deals) {
      const vf = when(row, "vf"), vt = when(row, "vt");
      if (ends(row) < win.start) { res.add("item already ended"); continue; }
      if (vf > win.end) { res.add("item starts after the 7-day window"); continue; }
      if (!row.industries.some(i => wanted.has(i))) { res.add("other industry"); continue; }
      const d = adDeal(row, ad, vf, vt, win, tz);
      const keep = seen.get(row.dk);
      if (keep) {                          // the same item at the same price in two ads: keep the longer-running one
        res.add("same item in another ad");
        if (vt > keep._vt) { candidates[candidates.indexOf(keep)] = d; seen.set(row.dk, d); }
        continue;
      }
      seen.set(row.dk, d);
      candidates.push(d);
    }
  }
  const flags = idx.merchants;
  for (const d of candidates) {           // LocalDeals._attach_store
    const near = nearestStore(d.merchant);
    if (near && near.distance_mi <= radius) { d.store = near; d.store_status = "nearby"; }
    else if (near) { d.store = near; d.store_status = "far"; res.add(`nearest store beyond ${radius} mi`); }
    else if ((flags[d.merchant] || {}).uncertain) d.store_status = "unmapped";
    else { d.store_status = "far"; res.add("no store within 50 mi"); }
  }
  const kept = candidates.filter(d => d.store_status === "nearby" || d.store_status === "unmapped");
  kept.sort((a, b) => (b.score - a.score) || ((b.terms.savings || 0) - (a.terms.savings || 0)) || cmp(a.title, b.title));
  kept.forEach(d => delete d._vt);
  const entries = new Map();               // LocalDeals._merchant_table, by Flipp's name for the merchant
  for (const id of live) entries.set(idx.flyers[id].flipp, idx.flyers[id].merchant);
  const merchants = [...entries.keys()].sort(cmp).map(flipp => {
    const name = entries.get(flipp), near = nearestStore(name);
    const status = near && near.distance_mi <= radius ? "nearby" : (flags[name] || {}).uncertain ? "unmapped" : "far";
    return {merchant: name, flipp_name: flipp, status, nearest_mi: near ? near.distance_mi : null, store: near};
  });
  return {deals: kept, merchants};
}

function adDeal(row, ad, vf, vt, win, tz) {
  const t = terms(row.terms);
  return {
    id: `flipp:${row.id}`, item_id: row.id, flyer_id: ad.id, title: row.title, merchant: ad.merchant, brand: "",
    industries: row.industries, industry_rule: "", category: row.category || "", terms: t,
    valid_from: isoIn(vf, tz), valid_to: isoIn(vt, tz), source_url: `https://flipp.com/en-us/item/${row.id}`,
    retailer_url: row.retailer_url || "", image_url: row.image_url || "", store: null, store_status: "unknown",
    feed: !!row.feed, detailed: !!row.detailed, score: row.score || 0,
    starts_in_days: Math.max(0, daysBetween(win.start, vf, tz)), ends_in_days: daysBetween(win.start, vt, tz),
    regular: null, kind: t.promo || t.hedge || t.bogo ? "promotion" : "deal", basis_text: BASIS_TEXT[t.basis] || "",
    _vt: vt,
  };
}

// promos.RestaurantPromos.near: site.py has read the posts and the dates each states, in both Texas zones.
async function promotions(city, radius, win, res) {
  const P = await load("promos.json"), tz = city.tz, out = [];
  for (const [why, n] of Object.entries(P.excluded)) res.add(why, n);
  const today = wall(win.start, tz).date, last7 = wall(win.end, tz).date;
  for (const p of P.items) {
    const z = p.zones[tz] || p.zones["America/Chicago"];
    const posted = p.posted_now ? today : z.posted;
    let first = z.first, last = z.last, how = z.how;
    if (z.stated && (!first || z.stated >= first)) { last = z.stated; how = how || "stated expiry"; }
    if (p.recur.length && !first) {        // "every Tuesday": the next such day
      first = p.recur.map(wd => addDays(today, (((wd - weekday(today)) % 7) + 7) % 7)).sort()[0];
      last = last || last7;
      how = "recurring weekday";
    }
    if (!(first || last)) {
      if (toDay(today) - toDay(posted) > 3) { res.add("promotion: no dates and posted over 3 days ago"); continue; }
      first = posted; last = null; how = "no dates stated";
    }
    if (first && last && last < first) last = first;
    const vf = zoned(first || posted, "00:00:00", tz), vt = last ? zoned(last, "23:59:59", tz) : win.end;
    if (vt < win.start || vf > win.end) { res.add("promotion: outside the 7-day window"); continue; }
    const chain = P.chains[p.qid];
    let branch = null;                     // sources/stores.RestaurantLocator.nearest
    for (const [lat, lon, address, ref] of chain ? chain.rows : []) {
      const d = miles(city.lat, city.lon, lat, lon);
      if (!branch || d < branch.distance_mi) branch = store(chain.name, chain.name, lat, lon, address, d, "osm", ref);
    }
    if (!branch || branch.distance_mi > radius) { res.add("promotion: no branch nearby"); continue; }
    const t = terms({promo: true, summary: p.summary, conditions: [how === "no dates stated" ? "dates not stated" : "",
      p.app ? "in the app" : "", p.dinein ? "dine-in only" : ""].filter(Boolean)});
    out.push({
      id: `promo:${p.id}`, item_id: 0, flyer_id: 0, title: p.title, merchant: branch.merchant, brand: branch.merchant,
      industries: ["dining"], industry_rule: "restaurant chain", category: "Restaurants", terms: t,
      valid_from: isoIn(vf, tz), valid_to: isoIn(vt, tz), source_url: p.url, retailer_url: "", image_url: p.image || "",
      store: branch, store_status: "nearby", feed: false, detailed: false, score: 0,
      starts_in_days: Math.max(0, daysBetween(win.start, vf, tz)), ends_in_days: daysBetween(win.start, vt, tz),
      regular: null, kind: "promotion", basis_text: BASIS_TEXT.none,
    });
  }
  res.sources.push(...P.sources);
  return out;
}

/* ---- regular deals (regulars.Regulars.near and schedule.Schedule) ----------------------------------------- */
function runsOn(s, d) {                    // Schedule.runs_on
  if ((s.since && d < s.since) || (s.until && d > s.until)) return false;
  if (s.monthly) {
    const [kind, n] = s.monthly.split(":");
    const day = +d.slice(8, 10);
    if (kind === "d") return day === +n;
    if (weekday(d) !== +n) return false;
    if (+kind === -1) {
      const inMonth = new Date(Date.UTC(+d.slice(0, 4), +d.slice(5, 7), 0)).getUTCDate();
      return day + 7 > inMonth;
    }
    return Math.floor((day - 1) / 7) + 1 === +kind;
  }
  return s.days.includes(weekday(d));
}

function occurrences(s, windows, win, tz) {   // Schedule.occurrences
  const a = wall(win.start, tz), b = wall(win.end, tz), out = [];
  const startSecs = a.h * 3600 + a.m * 60 + a.s + a.ms / 1000, endSecs = b.h * 3600 + b.m * 60 + b.s + b.ms / 1000;
  for (let d = a.date; d <= b.date; d = addDays(d, 1)) {
    if (!runsOn(s, d)) continue;
    const over = d === a.date && windows.length && windows.every(([, to]) => to !== null && secsOf(to) <= startSecs);
    const notYet = d === b.date && windows.length && windows.every(([from]) => from !== null && secsOf(from) >= endSecs);
    if (!over && !notYet) out.push(d);
  }
  return out;
}

function branchOf(r, chains, city) {     // Regulars.place and venues.Venues.nearest
  if (r.places) {
    let best = null;
    for (const [lat, lon, name, address] of r.places) {
      const d = miles(city.lat, city.lon, lat, lon);
      if (!best || d < best.distance_mi) best = store(r.brand, name || r.brand, lat, lon, address, d, "entry", `entry:${r.id}`);
    }
    return best;
  }
  const chain = r.chain && chains[r.chain];
  if (!chain) return null;
  let best = null, bestD = 0;
  for (const row of chain.rows) {
    if (r.area && miles(r.area.lat, r.area.lon, row[0], row[1]) > r.area.mi) continue;
    const d = miles(city.lat, city.lon, row[0], row[1]);
    if (!best || d < bestD) { best = row; bestD = d; }
  }
  return best && store(chain.name, best[2] || chain.name, best[0], best[1], best[3], bestD, "osm", best[4]);
}

async function regulars(city, inds, radius, win, res) {
  const R = await load("regulars.json"), tz = city.tz, wanted = new Set(inds), out = [];
  for (const [why, n] of Object.entries(R.excluded)) res.add(why, n);
  for (const r of R.regulars) {
    const di = r.industries.filter(i => wanted.has(i));
    if (!di.length) continue;
    const near = branchOf(r, R.chains, city);
    if (!near || near.distance_mi > radius) { res.add("regular deal: no branch within the radius"); continue; }
    const windows = r.schedule.windows[tz] || r.schedule.windows["America/Chicago"];
    let dates = occurrences(r.schedule, windows, win, tz);
    if (!dates.length) { res.add("regular deal: does not run in the next 7 days"); continue; }
    dates = dates.filter(d => !r.off.includes(d));
    if (!dates.length) { res.add("regular deal: its page says the coming date is sold out"); continue; }
    out.push(regularDeal(r, di, near, dates, windows, win, tz));
  }
  out.sort((a, b) => (a.starts_in_days - b.starts_in_days) || (b.score - a.score) || cmp(a.merchant, b.merchant) ||
    cmp(a.title, b.title));
  res.sources.push(...R.sources);
  return out;
}

function regularDeal(r, inds, near, dates, windows, win, tz) {   // Regulars._deal
  const first = dates[0], last = dates[dates.length - 1];
  const opens = windows.length && windows.every(([from]) => from) ? windows.map(([from]) => from).sort()[0] : null;
  const closes = windows.length && windows.every(([, to]) => to) ? windows.map(([, to]) => to).sort().pop() : null;
  const vf = Math.max(win.start, zoned(first, opens || "00:00:00", tz)), vt = zoned(last, closes || "23:59:59", tz);
  const t = terms(r.terms);
  return {
    id: `regular:${r.id}`, item_id: 0, flyer_id: 0, title: r.offer, merchant: r.brand, brand: r.brand, industries: inds,
    industry_rule: `regular deal at a ${r.kind}`, category: r.kind, terms: t, valid_from: isoIn(vf, tz),
    valid_to: isoIn(vt, tz), source_url: r.source_url, retailer_url: r.link, image_url: r.image_url, store: near,
    store_status: "nearby", feed: false, detailed: false, score: r.score,
    starts_in_days: Math.max(0, daysBetween(win.start, vf, tz)), ends_in_days: daysBetween(win.start, vt, tz),
    regular: {days: r.schedule.days.map(d => DAY_KEYS[d]), monthly: r.schedule.monthly, days_text: r.days_text,
              time_text: r.time_text[tz] ?? r.time_text["America/Chicago"], next: dates, until: r.schedule.until,
              ends: closes ? closes.slice(0, 5) : null, logo: r.logo, status: r.status, status_text: r.status_text,
              origin: r.origin, kind: r.kind, note: r.note, evidence: r.evidence},
    kind: "regular", basis_text: BASIS_TEXT[t.basis] || "",
  };
}

/* ---- online deals (service.SlompService.online) ----------------------------------------------------------- */
async function online(inds, limit) {
  const missing = {deals: {}, excluded: {}, sources: [{name: "Online deals", ok: false, error: "couldn't be loaded"}]};
  const parts = await Promise.all(inds.map(i => load(`online/${i}.json`).catch(() => missing)));
  const deals = {}, excluded = new Map(), sources = [], names = new Set();
  let generated = null;
  parts.forEach((part, k) => {
    const i = inds[k];
    deals[i] = (part.deals[i] || []).slice(0, limit);
    for (const [why, n] of Object.entries(part.excluded)) excluded.set(why, Math.max(excluded.get(why) || 0, n));
    for (const s of part.sources) if (!names.has(s.name)) { names.add(s.name); sources.push(s); }
    if (part.generated_at && (!generated || Date.parse(part.generated_at) < Date.parse(generated))) generated = part.generated_at;
  });
  return {industries: inds, generated_at: generated, deals,
          counts: Object.fromEntries(Object.entries(deals).map(([k, v]) => [k, v.length])),
          excluded: Object.fromEntries([...excluded.entries()].sort((a, b) => b[1] - a[1])), sources};
}

/* ---- the API the page calls ------------------------------------------------------------------------------- */
let meta = null, cities = null;
async function getMeta(check = false) {
  if (!meta || check) {
    let m;
    try {
      m = await loader("meta.json");
    } catch (e) {
      if (meta) return meta;               // offline for a moment: keep using what was loaded
      throw new Error("Slomp's deals couldn't be loaded. Check your connection and try again.");
    }
    if (!meta || m.built !== meta.built) {
      memo.clear();                        // a new build: none of the old build's files
      meta = m;
      cities = new Map(meta.cities.map(c => [c.id, c]));
    }
  }
  return meta;
}

// /api/v1/search: {local, online}. `now` (an ISO time) is for the parity check; the page leaves it out.
async function search({city: cityId, industries, radius_mi = 25, limit = 25, now} = {}) {
  const M = await getMeta(true);
  const city = cities.get(String(cityId || "").trim().toLowerCase());
  if (!city) throw new Error("Choose a Texas city from the list.");
  const known = new Set(M.industries.map(i => i.id)), localOnly = new Set(M.industries.filter(i => !i.online).map(i => i.id));
  const raw = Array.isArray(industries) ? industries : String(industries || "").split(",");
  const inds = [...new Set(raw.map(i => String(i).trim().toLowerCase()).filter(i => known.has(i)))];
  if (!inds.length) throw new Error("Choose at least one thing you're shopping for.");
  const radius = Number(radius_mi);
  if (!M.radii_mi.includes(radius)) throw new Error(`Choose a distance of ${M.radii_mi.join(", ")} miles.`);
  const tz = city.tz, start = now ? Date.parse(now) : Date.now(), win = {start, end: plusDays(start, WINDOW_DAYS, tz)};

  const res = new Result();
  const retail = inds.filter(i => !localOnly.has(i));
  let ads = {deals: [], merchants: []};
  if (retail.length) ads = await part(res, "Flipp weekly ads", () => weeklyAds(city, new Set(retail), radius, win, res), ads);
  let promos = ads.deals.filter(d => d.store_status !== "unmapped" && d.kind === "promotion");
  if (inds.includes("dining")) {
    promos = promos.concat(await part(res, "Restaurant promotions", () => promotions(city, radius, win, res), []));
    promos.sort((a, b) => (b.score - a.score) || (a.ends_in_days - b.ends_in_days) || cmp(a.title, b.title));
  }
  const regular = await part(res, "Regular deals registry", () => regulars(city, inds, radius, win, res), []);
  const deals = ads.deals.filter(d => d.store_status !== "unmapped" && d.kind !== "promotion");
  const unconfirmed = ads.deals.filter(d => d.store_status === "unmapped");
  const local = {
    city: {id: city.id, name: city.name, county: city.county, zip: city.zip, tz, lat: city.lat, lon: city.lon},
    industries: inds, radius_mi: radius, window: {start: isoIn(win.start, tz), end: isoIn(win.end, tz)},
    counts: {deals: deals.length, promotions: promos.length, unconfirmed: unconfirmed.length, regulars: regular.length},
    deals, promotions: promos, unconfirmed, regulars: regular, excluded: res.counts(), merchants: ads.merchants,
    sources: res.sources,
    beyond_radius: ads.merchants.filter(m => m.status === "far" && m.nearest_mi)
      .map(m => ({merchant: m.merchant, nearest_mi: m.nearest_mi})).sort((a, b) => a.nearest_mi - b.nearest_mi),
    // the published site's own notes: whose weekly ads these are, and when the data was read
    ads_from: retail.length && city.anchor !== city.id
      ? {id: city.anchor, name: (M.anchors[city.anchor] || {}).name || city.anchor, mi: city.anchor_mi} : null,
    built: M.built,
  };
  const onlineInds = inds.filter(i => !localOnly.has(i));
  return {local, online: onlineInds.length ? await online(onlineInds, Math.max(1, Math.min(100, Number(limit) || 25))) : null};
}

const SlompStatic = {
  meta: () => getMeta(), search,
  configure(opts) { if (opts.loader) { loader = opts.loader; memo.clear(); meta = null; } },
};
root.SlompStatic = SlompStatic;
if (typeof module !== "undefined" && module.exports) module.exports = SlompStatic;
})(typeof globalThis !== "undefined" ? globalThis : this);
