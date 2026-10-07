"""Build slomp/data/logos.json: a logo for each chain and place a regular deal can be shown at.

The company's own website comes first. Its home page is read (robots.txt honored; a bot check, or a robots.txt that
turns away AI assistants by name, means the site is left alone) and its icon picked: the square apple-touch icon,
else the largest icon the page links, else /apple-touch-icon.png or /favicon.ico. A chain whose site gives none falls
back on the logo its Wikidata entry records (P154), as a Wikimedia Commons thumbnail. Wikidata also supplies the
website (P856) of a chain that no deal page links to. The web page loads each picture from where it lives; Slomp
only stores its address.

Where the website comes from, in order: the company page a registry entry is confirmed on, a `site` the entry or
venue rule names, the chain's Wikidata website, and the link a deal list gives for the chain.

    python scripts/build_logos.py          # after scripts/build_stores.py; rerun when new chains appear
    python scripts/build_logos.py --stores # only the online stores (data/online_stores.json): keys o: and ow:

An online store gets two pictures: its own site's icon (`o:`, square, for the corner of a sale's picture) and its
Wikidata logo (`ow:`, usually a wordmark, for its tile on the Stores tab), each where it can be had.
"""
from __future__ import annotations

import asyncio
import hashlib
import html as htmllib
import json
import re
import struct
import sys
import unicodedata
from datetime import date
from pathlib import Path
from typing import Optional
from urllib.parse import quote, unquote, urljoin, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from slomp.config import Settings  # noqa: E402
from slomp.db import Store  # noqa: E402
from slomp.http import Blocked, Disallowed, FetchError, PoliteClient  # noqa: E402
from slomp.reference import fold, merchant  # noqa: E402
from slomp.regulars import Regulars, from_entry, load_entries, logo_key  # noqa: E402
from slomp.sources.venues import Venues, _spec  # noqa: E402

OUT = ROOT / "slomp" / "data" / "logos.json"
NSI = Path.home() / ".cache" / "slomp" / "osm" / "nsi.min.json"     # the brand index scripts/build_stores.py fetched
TTL = 30 * 86400
MIN_PX = 32
MAX_ASPECT = 3.2          # a wordmark wider than this is unreadable in a square tile
WORDMARK_ASPECT = 9.0     # a store's tile on the Stores tab is twice as wide as it is tall; Kohl's logo is 6.25:1
# Wikidata logos found to be wrong. Wikidata records Cracker Barrel's August 2025 redesign, which the company withdrew.
NOT_THIS_LOGO = {"Cracker Barrel": "Cracker_Barrel_logo_2025.svg"}
# A website's icon that is the platform's, not the company's: WordPress shows its own logo on a site that set none.
_PLATFORM_ICON = re.compile(r"/wp-includes/images/w-logo", re.I)
# Places whose website icons were looked at on a sheet of every logo (Oct 5, 2026) and left out, with why.
REVIEWED_OUT = {
    "Hank's": "the site serves a generic file icon",
    "Houston Museum of Natural Science": "its logo is white, invisible on a white tile",
    "Holocaust Museum Houston": "its icon is a plain gradient square",
}
# A website from Wikidata or a deal list that is about the brand rather than its own: Wikidata gives Texas Roadhouse's
# website as a menu-price site.
_NOT_OWN = re.compile(r"menu|menues|price|coupon|deal|review|promo", re.I)
# Links on deal pages that are not the company's own site.
NOT_THEIRS = ("facebook.com", "instagram.com", "twitter.com", "x.com", "tiktok.com", "youtube.com", "linktr.ee",
              "apps.apple.com", "play.google.com", "google.com", "goo.gl", "bit.ly", "yelp.com", "opentable.com",
              "doordash.com", "ubereats.com", "grubhub.com", "thekrazycouponlady.com", "eatdrinkdeals.com",
              "hip2save.com", "dfwchild.com", "culturemap.com", "austinfoodmagazine.com", "dallasites101.com",
              "milehighonthecheap.com", "thetakeout.com", "theinfatuation.com", "austinot.com", "calendar.utexas.edu",
              "wikipedia.org", "eventbrite.com")


def theirs(url: str) -> str:
    """The host of a company's own site, or "" for a link to someone else's (a social network, a deal site)."""
    host = urlsplit(url or "").netloc.lower()
    if not host or any(host == d or host.endswith("." + d) for d in NOT_THEIRS):
        return ""
    return host


def image_size(body: bytes) -> Optional[tuple[int, int]]:
    """Width and height of a PNG, GIF or ICO (its largest picture); None for a format this doesn't read (SVG is fine
    at any size)."""
    if body[:8] == b"\x89PNG\r\n\x1a\n" and len(body) >= 24:
        return struct.unpack(">II", body[16:24])
    if body[:4] in (b"GIF8",) and len(body) >= 10:
        return struct.unpack("<HH", body[6:10])
    if body[:4] == b"\x00\x00\x01\x00" and len(body) >= 6:
        n = struct.unpack("<H", body[4:6])[0]
        sizes = [((body[6 + 16 * i] or 256), (body[7 + 16 * i] or 256)) for i in range(n) if 8 + 16 * i <= len(body)]
        return max(sizes, default=None)
    return None


_LINK = re.compile(r"<link\b[^>]*>", re.I)
_ATTR = re.compile(r"([\w:-]+)\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)")


def icon_links(page: str, base: str) -> list[tuple[float, int, str, str]]:
    """(priority, size, url, fit) for each icon a page links, best first, with the two usual addresses after them."""
    out = []
    for tag in _LINK.findall(page):
        a = {k.lower(): v.strip("\"'") for k, v in _ATTR.findall(tag)}
        rel, href = set(a.get("rel", "").lower().split()), a.get("href", "")
        if not href or "mask-icon" in rel:
            continue
        sizes = [int(x) for x in re.findall(r"(\d+)x\d+", a.get("sizes", ""))]
        url = href if href.startswith("data:") else urljoin(base, href)
        svg = "svg" in a.get("type", "") or href.lower().split("?")[0].endswith(".svg")
        if rel & {"apple-touch-icon", "apple-touch-icon-precomposed"}:
            out.append((3, max(sizes, default=180), url, "cover"))
        elif "icon" in rel:
            size = 512 if svg else max(sizes, default=32)
            out.append((2 if size >= 96 else 1, size, url, "contain"))
    out.sort(key=lambda c: (c[0], c[1]), reverse=True)
    out += [(0.5, 180, urljoin(base, "/apple-touch-icon.png"), "cover"), (0, 32, urljoin(base, "/favicon.ico"), "contain")]
    seen, unique = set(), []
    for c in out:
        if c[2] not in seen:
            seen.add(c[2])
            unique.append(c)
    return unique


async def picture(c: PoliteClient, url: str, fit: str, max_aspect: float = MAX_ASPECT) -> Optional[dict]:
    """The picture at `url`, if it is one and big enough to show; `fit` becomes "contain" for a picture that is not
    square, so a wide logo is fitted, not cropped."""
    if url.startswith("data:image/"):
        return {"url": url, "fit": "contain"} if len(url) < 20000 else None
    if _PLATFORM_ICON.search(url):
        return None
    try:
        if await c.turns_away_ai(url):
            return None
        r = await c.get(url, ttl_s=TTL)
    except FetchError:
        return None
    kind = (r.content_type or "").lower()
    if r.status != 200 or len(r.body) < 100 or not (kind.startswith("image/") or url.lower().split("?")[0].endswith(".ico")):
        return None
    dims = image_size(r.body)
    if dims and (min(dims) < MIN_PX or max(dims) > max_aspect * min(dims)):
        return None
    if _PLATFORM_ICON.search(r.final_url or ""):
        return None                                  # /favicon.ico redirected to WordPress's own logo
    if dims and fit == "cover" and abs(dims[0] - dims[1]) > 0.1 * max(dims):
        fit = "contain"
    return {"url": r.final_url or url, "fit": fit, **({"px": max(dims)} if dims else {})}


_GENERIC = {"the", "and", "of", "cafe", "bar", "grill", "restaurant", "restaurants", "kitchen", "lounge", "house",
            "museum", "texas", "tx", "steakhouse", "steak", "pizza", "tacos", "taco", "co", "company", "market", "art",
            "store", "stores", "shop", "dine", "in", "cinema", "cinemas", "theatres", "theaters", "wing", "family"}


def belongs(brand: str, host: str, page: str) -> bool:
    """The site is this brand's: a distinctive word of its name is in the address, the page title or the site name.
    A link from a deal page can point at a parent company or an ordering service."""
    def plain(text: str) -> str:              # lower case, no accents or apostrophes, words kept apart
        t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower().replace("&", " and ")
        return re.sub(r"[^a-z0-9]+", " ", t.replace("'", "").replace("’", ""))
    words = [w for w in plain(brand).split() if w not in _GENERIC and len(w) >= 3] or \
        [plain(brand).replace(" ", ""), plain(brand).replace(" and ", "").replace(" ", "")]      # "B&B" is bb
    head = page[:200000]
    names = " ".join(re.findall(r"<title[^>]*>(.*?)</title>", head, re.S | re.I) +
                     re.findall(r'property="og:site_name"[^>]*content="([^"]*)"', head, re.I))
    hay = plain(host) + " " + plain(htmllib.unescape(names))
    return any(w in hay or w in hay.replace(" ", "") for w in words)


async def site_logo(c: PoliteClient, host: str, brand: str = "") -> tuple[Optional[dict], str]:
    home = f"https://{host}/"
    try:
        if await c.turns_away_ai(home):
            return None, "its robots.txt turns away AI assistants"
        r = await c.get(home, ttl_s=TTL, html=True)
    except Disallowed:
        return None, "its robots.txt does not allow reading the home page"
    except Blocked:
        return None, "its home page answers with a bot check"
    except FetchError as e:
        return None, e.reason
    if r.status != 200:
        return None, f"HTTP {r.status}"
    base = r.final_url or home
    if brand and not belongs(brand, urlsplit(base).netloc, r.text):
        return None, "the site does not look like this brand's"
    for _, _, url, fit in icon_links(r.text, base)[:6]:
        got = await picture(c, url, fit)
        if got:
            return {**got, "from": "site", "site": urlsplit(base).netloc}, ""
    return None, "no usable icon"


def _section(page: str, prop: str) -> str:
    i = page.find(f'id="{prop}"')
    return page[i:i + 20000] if i >= 0 else ""


async def wikidata(c: PoliteClient, qid: str) -> tuple[str, str]:
    """(official website, logo file name) from the chain's public Wikidata page. The data API sits under a path the
    site's robots.txt closes to automated readers; the entity page does not."""
    url = f"https://www.wikidata.org/wiki/{qid}"
    try:
        if await c.turns_away_ai(url):
            return "", ""
        page = (await c.get(url, ttl_s=TTL, html=True)).text
    except FetchError:
        return "", ""
    site = re.search(r'<a[^>]+class="[^"]*external[^"]*"[^>]+href="(https?://[^"]+)"', _section(page, "P856"))
    logo = re.search(r'commons\.wikimedia\.org/wiki/File:([^"#?]+)"', _section(page, "P154"))
    return (site.group(1) if site else ""), (unquote(logo.group(1)) if logo else "")


async def commons_logo(c: PoliteClient, name: str, widths: tuple[int, ...] = (250, 120),
                       max_aspect: float = MAX_ASPECT) -> Optional[dict]:
    """A Wikimedia Commons file as a thumbnail, addressed the way Commons stores it (Special:FilePath, the redirect
    service, is closed to automated readers)."""
    name = name.replace(" ", "_")
    h = hashlib.md5(name.encode("utf-8")).hexdigest()
    part = quote(name, safe="()_-.,'!")
    for width in widths:
        url = (f"https://upload.wikimedia.org/wikipedia/commons/thumb/{h[0]}/{h[:2]}/{part}/{width}px-{part}" +
               (".png" if name.lower().endswith(".svg") else ""))
        got = await picture(c, url, "contain", max_aspect)
        if got:
            return {**got, "from": "wikidata", "site": "commons.wikimedia.org"}
    return None


def venue_qids() -> dict[str, str]:
    """Wikidata ids for venue chains, from the brand index: a venue's brand names matched against it, kept only when
    they point at one id (or one in the venue's own kind of place)."""
    if not NSI.exists():
        return {}
    index: dict[str, set] = {}
    for path, cat in json.loads(NSI.read_text())["nsi"].items():
        for item in cat.get("items", []):
            t = item.get("tags", {})
            if t.get("brand:wikidata"):
                for n in {t.get("brand"), t.get("name"), item.get("displayName")} - {None}:
                    index.setdefault(n.strip().lower(), set()).add((t["brand:wikidata"], path.rsplit("/", 1)[-1]))
    out = {}
    for v in _spec()["venues"]:
        hits = set().union(*(index.get(n.strip().lower(), set()) for n in v.get("brands", []) + v.get("names", [])))
        kinds = {x for vals in (v.get("only") or {}).values() for x in vals}
        ids = {q for q, cat in hits if not kinds or cat in kinds} or {q for q, _ in hits}
        if len(ids) == 1:
            out[v["key"]] = ids.pop()
    return out


async def main() -> None:
    settings = Settings()
    venues = Venues()
    today = date.today()
    async with PoliteClient(Store(settings.db_path), settings) as c:
        regs = Regulars(c, Store(settings.db_path), settings, venues)
        items = list((await regs.all()).regulars)
        entries, _ = load_entries(regs.registry)
        for e in entries:
            r = from_entry(e, venues, "registry", today)
            if not isinstance(r, str):
                items.append(r)
        venue_sites = {v["name"]: v.get("site", "") for v in _spec()["venues"]}
        venue_qid = venue_qids()

        # Every place, with the websites that may be its own, best first.
        want: dict[str, dict] = {}
        for r in items:
            if r.suppress:
                continue
            k = logo_key(r)
            w = want.setdefault(k, {"brand": r.brand, "hosts": [], "qid": ""})
            official = [e.url for e in r.evidence if e.kind in ("official", "rewards")] + \
                [s["url"] for s in r.checks if s.get("kind", "official") in ("official", "rewards")]
            named = [r.site, venue_sites.get(r.chain.name, "") if r.chain else ""]
            w["hosts"] = list(dict.fromkeys(w["hosts"] + [h for h in map(theirs, official + named) if h]))
            w.setdefault("links", [])
            w["links"] = list(dict.fromkeys(w["links"] + [h for h in [theirs(r.link)] if h]))
            if r.chain and r.chain.key.startswith("r:"):
                w["qid"] = r.chain.key[2:]
            elif r.chain and r.chain.key.startswith("s:"):
                w["qid"] = next(iter(merchant(r.chain.name).wikidata), "")
            elif r.chain and r.chain.key.startswith("v:"):
                w["qid"] = venue_qid.get(r.chain.key[2:], "")

        async def one(k: str, w: dict) -> tuple[str, Optional[dict], list[str]]:
            notes, site_from_wd, logo_file = [], "", ""
            if w["qid"]:
                site_from_wd, logo_file = await wikidata(c, w["qid"])
            others = [h for h in [theirs(site_from_wd)] + w["links"] if h and not
                      (_NOT_OWN.search(h) and not _NOT_OWN.search(w["brand"]))]
            hosts = list(dict.fromkeys(w["hosts"] + others))
            if w["brand"] in REVIEWED_OUT:
                notes.append(f"its site's icons: {REVIEWED_OUT[w['brand']]}")
                hosts = []
            for host in hosts:
                got, why = await site_logo(c, host, w["brand"])
                if got:
                    return k, {"brand": w["brand"], **got}, notes
                notes.append(f"{host}: {why}")
            if logo_file and NOT_THIS_LOGO.get(w["brand"]) == logo_file.replace(" ", "_"):
                notes.append(f"Wikidata logo {logo_file}: known to be wrong")
            elif logo_file:
                got = await commons_logo(c, logo_file)
                if got:
                    return k, {"brand": w["brand"], **got}, notes
                notes.append(f"Wikidata logo {logo_file}: not usable")
            return k, None, notes or ["no website known"]

        results = await asyncio.gather(*(one(k, w) for k, w in want.items()))

    logos = {k: v for k, v, _ in sorted(results) if v}
    if OUT.exists():                       # the online stores' logos (--stores) are built separately: keep them
        logos.update({k: v for k, v in json.loads(OUT.read_text()).get("logos", {}).items() if k.startswith(("o:", "ow:"))})
    OUT.write_text(json.dumps({
        "built": today.isoformat(),
        "about": "A logo for each chain and place a regular deal can be shown at, keyed like the venue lookup "
                 "(r: Wikidata id of a restaurant chain, s: store, v: venue, place: a single place's folded name). "
                 "`url` is where the picture lives; `fit` says whether it fills its tile (a square app icon) or is "
                 "fitted into it. Built by scripts/build_logos.py from each company's own website, or its Wikidata "
                 "logo on Wikimedia Commons. Online stores: o: its own site's icon, ow: its Wikidata logo "
                 "(scripts/build_logos.py --stores).",
        "logos": dict(sorted(logos.items()))}, indent=1, ensure_ascii=False) + "\n")
    print(f"{len(logos)} of {len(want)} chains and places have a logo "
          f"({sum(v['from'] == 'site' for v in logos.values())} from their own site, "
          f"{sum(v['from'] == 'wikidata' for v in logos.values())} from Wikidata)")
    for k, v, notes in sorted(results):
        if not v:
            print(f"  none: {want[k]['brand']} ({k}): {'; '.join(notes)[:160]}")


async def store_logos() -> None:
    """Online stores: the icon on each store's own site (a site that turns AI assistants away by name, or answers
    with a bot check, is left alone), and the logo its Wikidata item records. Merged into logos.json."""
    rows = json.loads((ROOT / "slomp" / "data" / "online_stores.json").read_text())["stores"]
    settings = Settings()
    async with PoliteClient(Store(settings.db_path), settings) as c:
        async def one(r: dict) -> tuple[str, Optional[dict], Optional[dict], list[str]]:
            notes = []
            icon = None
            host = theirs(r.get("site", ""))
            if host:
                icon, why = await site_logo(c, host, r["name"])
                if not icon:
                    notes.append(f"{host}: {why}")
            mark = None
            if r.get("wikidata"):
                _, logo_file = await wikidata(c, r["wikidata"])
                if logo_file:
                    mark = await commons_logo(c, logo_file, (500, 250), WORDMARK_ASPECT)
                    if not mark:
                        notes.append(f"Wikidata logo {logo_file}: not usable")
                else:
                    notes.append(f"Wikidata {r['wikidata']}: no logo")
            return r["key"], icon and {"brand": r["name"], **icon}, mark and {"brand": r["name"], **mark}, notes
        results = await asyncio.gather(*(one(r) for r in rows))
    doc = json.loads(OUT.read_text()) if OUT.exists() else {"logos": {}}
    logos = {k: v for k, v in doc.get("logos", {}).items() if not k.startswith(("o:", "ow:"))}
    for key, icon, mark, _ in results:
        if icon:
            logos[f"o:{key}"] = icon
        if mark:
            logos[f"ow:{key}"] = mark
    doc["logos"] = dict(sorted(logos.items()))
    doc["about"] = doc.get("about", "").split(" Online stores:")[0] + (
        " Online stores: o: its own site's icon, ow: its Wikidata logo (scripts/build_logos.py --stores).")
    OUT.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
    print(f"{sum(1 for _, i, m, _ in results if i or m)} of {len(rows)} online stores have a logo "
          f"({sum(1 for _, i, _, _ in results if i)} site icons, {sum(1 for _, _, m, _ in results if m)} Wikidata logos)")
    for key, icon, mark, notes in results:
        if not (icon and mark):
            print(f"  {key}: {'icon' if icon else 'no icon'}, {'logo' if mark else 'no logo'}; {'; '.join(notes)[:150]}")


if __name__ == "__main__":
    asyncio.run(store_logos() if "--stores" in sys.argv else main())
