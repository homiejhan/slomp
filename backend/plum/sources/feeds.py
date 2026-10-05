"""Online deal feeds: public RSS from deal sites, read into plain `Post` records.

  dealnews     category feeds with structured retailer, price, deal type and expiry, and editor comparisons
  Slickdeals   front page, popular, and keyword searches (community-vetted)
  Hip2Save     category feeds; titles carry "Only $X on <Store> (Reg. $Y)"
  Ben's Bargains, The Inventory, 9to5Toys, DealCatcher: general feeds, classified by keywords

Every field is read defensively; a post without a parseable price is kept only so it can be counted as excluded.
"""
from __future__ import annotations

import html as htmllib
import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from functools import lru_cache
from typing import Optional
from urllib.parse import parse_qs, unquote, urlsplit

from ..config import TTL
from ..geo import parse_time
from ..http import FetchError, PoliteClient
from ..reference import DATA, store_from_domain
from ..terms import clean, money, title_price

DN = "{https://www.dealnews.com/ns/rss/1.0.htm}"
CONTENT = "{http://purl.org/rss/1.0/modules/content/}encoded"
ATOM = "{http://www.w3.org/2005/Atom}"

# Which dealnews category feeds serve each industry (root categories; see data/dealnews_categories.json).
DEALNEWS_FEEDS: dict[str, list[int]] = {
    "tech": [39, 142, 191], "sports": [211], "fashion": [202], "home": [196], "beauty": [759], "health": [765],
    "grocery": [214, 637, 804], "toys": [226, 294], "baby": [224], "pets": [221], "auto": [238], "office": [182],
    "dining": [377],
}
HIP2SAVE_FEEDS: dict[str, list[str]] = {
    "grocery": ["sales-deals/groceries"], "beauty": ["sales-deals/beauty"], "baby": ["sales-deals/baby", "sales-deals/kids"],
    "toys": ["sales-deals/toys"], "fashion": ["sales-deals/mens", "sales-deals/women", "sales-deals/shoes"],
    "office": ["sales-deals/office-supplies", "sales-deals/school-supplies"], "pets": ["sales-deals/pet-food-supplies-dog-cat"],
    "health": ["health-wellness"], "home": ["home-deals-coupons-tips"],
}
SLICKDEALS_QUERIES: dict[str, list[str]] = {
    "tech": ["laptop", "headphones", "tv", "monitor"], "sports": ["fitness", "camping", "golf"],
    "fashion": ["shoes", "jacket", "jeans"], "home": ["vacuum", "cookware", "tool"], "beauty": ["skin care", "shampoo"],
    "health": ["vitamins", "toothbrush"], "grocery": ["coffee", "snacks"], "toys": ["lego", "toy"],
    "baby": ["diapers", "baby"], "pets": ["dog", "cat"], "auto": ["car", "tire"], "office": ["office", "printer"],
    "dining": ["restaurant"],
}
GENERAL_FEEDS = {
    "slickdeals-frontpage": "https://slickdeals.net/newsearch.php?mode=frontpage&searcharea=deals&searchin=first&rss=1",
    "slickdeals-popular": "https://slickdeals.net/newsearch.php?mode=popdeals&searcharea=deals&searchin=first&rss=1",
    "bensbargains": "https://bensbargains.com/rss/",
    "theinventory": "https://theinventory.com/rss",
    "9to5toys": "https://9to5toys.com/feed/",
    "dealcatcher": "https://www.dealcatcher.com/rss",
}
SOURCE_NAMES = {"dealnews": "dealnews", "slickdeals": "Slickdeals", "hip2save": "Hip2Save", "bensbargains": "Ben's Bargains",
                "theinventory": "The Inventory", "9to5toys": "9to5Toys", "dealcatcher": "DealCatcher"}


@dataclass
class Post:
    source: str                         # "dealnews", "slickdeals", ...
    id: str
    url: str
    title: str
    text: str                           # description as plain text
    posted_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    expires_stated: bool = False        # True when the expiry is a real stated end, not a feed placeholder
    price: Optional[float] = None       # structured price, when the feed gives one
    reference: Optional[float] = None   # a "Reg. $Y" price stated in the title
    pct_stated: Optional[float] = None  # "(40% off)" stated by the post
    seller: str = ""
    deal_type: str = ""                 # dealnews: product | deal | sale
    category: str = ""                  # the feed's own category for the post
    feeds: list[str] = field(default_factory=list)            # which feeds it came from
    feed_industries: list[str] = field(default_factory=list)  # industries implied by those feeds
    merchant_link: str = ""
    image: str = ""
    links: list[str] = field(default_factory=list)       # every link in the post body
    others: list[tuple[str, float]] = field(default_factory=list)   # other stores' prices the post itself lists


def _plain(fragment: str) -> str:
    return clean(htmllib.unescape(re.sub(r"<[^>]+>", " ", fragment or "")))


def _when(raw: Optional[str]) -> Optional[datetime]:
    if not raw:
        return None
    try:
        d = parsedate_to_datetime(raw)
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return parse_time(raw)


def _items(xml_bytes: bytes) -> list[ET.Element]:
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        # Some feeds carry a stray control character or an unescaped '&'.
        text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", xml_bytes.decode("utf-8", "replace"))
        text = re.sub(r"&(?!#?\w+;)", "&amp;", text)
        root = ET.fromstring(text.encode())
    return root.findall(".//item") or root.findall(f".//{ATOM}entry")


def _first_link(fragment: str) -> str:
    m = re.search(r'href=["\'](https?://[^"\']+)', fragment or "")
    return htmllib.unescape(m.group(1)) if m else ""


def _links(fragment: str) -> list[str]:
    return [htmllib.unescape(u) for u in re.findall(r'href=["\'](https?://[^"\']+)', fragment or "")]


def _image(*candidates: Optional[str]) -> str:
    """The first usable picture: a plain image URL, or the first <img> in an HTML fragment. Always https."""
    for c in candidates:
        c = (c or "").strip()
        if not c:
            continue
        m = re.search(r'<img[^>]+src=["\']([^"\']+)', c)
        url = htmllib.unescape(m.group(1)) if m else (c if re.match(r"(?:https?:)?//\S+$", c) else "")
        if url.startswith("//"):
            url = "https:" + url
        if url.startswith("http://"):
            url = "https://" + url[7:]
        if url.startswith("https://"):
            return url
    return ""


def _child(it: ET.Element, local: str) -> Optional[ET.Element]:
    """A child element by its tag name without the namespace (feeds disagree about namespaces)."""
    for ch in it:
        if isinstance(ch.tag, str) and ch.tag.rsplit("}", 1)[-1] == local:
            return ch
    return None


@lru_cache(maxsize=1)
def dealnews_paths() -> dict[int, str]:
    data = json.loads((DATA / "dealnews_categories.json").read_text())["categories"]
    return {int(k): v["path"] for k, v in data.items()}


def dealnews_url(cid: int) -> str:
    return f"https://www.dealnews.com/c{cid}/{dealnews_paths().get(cid, '')}/?rss=1"


# --- per-source parsers ----------------------------------------------------------------------------------------
def parse_dealnews(xml_bytes: bytes, feed: str, industries: list[str]) -> list[Post]:
    out = []
    for it in _items(xml_bytes):
        link = clean(it.findtext("link")).split("?")[0]
        m = re.search(r"/(\d{5,})(?:\.html)?$", link)
        exp_raw = clean(it.findtext(DN + "expires"))
        exp = parse_time(exp_raw)
        out.append(Post(
            source="dealnews", id=f"dealnews:{m.group(1) if m else link}", url=link, title=clean(it.findtext("title")),
            text=_plain(it.findtext("description")), posted_at=_when(it.findtext("pubDate")),
            expires_at=exp, expires_stated=bool(exp and exp_raw[11:19] == "23:59:00"),
            price=money(it.findtext(DN + "price")), seller=clean(it.findtext(DN + "retailer")),
            deal_type=clean(it.findtext(DN + "dealType")).lower(), category=clean(it.findtext(DN + "category")),
            feeds=[feed], feed_industries=list(industries),
            image=_image(it.find("{http://search.yahoo.com/mrss/}content").get("url", "")
                         if it.find("{http://search.yahoo.com/mrss/}content") is not None else "",
                         it.findtext("description"))))
    return out


def parse_slickdeals(xml_bytes: bytes, feed: str, industries: list[str]) -> list[Post]:
    out = []
    for it in _items(xml_bytes):
        link = clean(it.findtext("link")).split("?")[0]
        m = re.search(r"/f/(\d+)", link)
        content = it.findtext(CONTENT) or ""
        text = _plain(content) or _plain(it.findtext("description"))
        click = _first_link(content)
        text = re.sub(r"^Thumb Score: [+-]?\d+\s*", "", text)
        title = clean(it.findtext("title"))
        seller = slickdeals_store(text, title)
        stores = [(store_from_domain(d), money(p)) for d, p in _SD_STORE_PRICE.findall(text)]
        others = [(st, pr) for st, pr in dict(stores).items() if pr and st and st.lower() != seller.lower()]
        out.append(Post(source="slickdeals", id=f"slickdeals:{m.group(1) if m else link}", url=link, title=title,
                        text=text, posted_at=_when(it.findtext("pubDate")), seller=seller,
                        feeds=[feed], feed_industries=list(industries), merchant_link=click, links=_links(content),
                        others=others, image=_image(content, it.findtext("description"))))
    return out


# "Target [ target.com ] has 799-Piece LEGO ... on sale for $51.99": one store's price in a multi-store post
_SD_STORE_PRICE = re.compile(r"\[\s*((?:[a-z0-9-]+\.)+[a-z]{2,})\s*\] has [^$]{3,220}?\bfor \*?\$\s?(\d[\d,]*(?:\.\d\d)?)")


def slickdeals_store(text: str, title: str) -> str:
    """The store a Slickdeals post is for, strongest evidence first: '[amazon.com]', 'via Amazon', 'Amazon has',
    a product URL in the text, 'at Amazon' in the title."""
    dm = re.search(r"\[\s*((?:[a-z0-9-]+\.)+[a-z]{2,})\s*\]", text)
    if dm:
        return store_from_domain(dm.group(1))
    vm = re.search(r"\bvia ([A-Z][\w&'.!\- ]{1,30}?)(?: \[| has| offers| is\b|[.,])", text)
    if vm:
        return vm.group(1).strip()
    hm = re.search(r"(?:^|[.!] )([A-Z][\w&'.!\-]*(?: [A-Z][\w&'.!\-]*){0,3}) (?:has|offers|is offering|is selling)\b", text)
    if hm:
        return hm.group(1).strip()
    um = re.search(r"https?://(?:www\.)?((?:[a-z0-9-]+\.)+[a-z]{2,})/", text)
    if um:
        return store_from_domain(um.group(1))
    tm = re.search(r"\bat ([A-Z][\w&'.\- ]{1,30})$", title)
    return tm.group(1) if tm else ""




_H2S = re.compile(r"(?:just|only|as low as|for|now)\s+" + r"\$\s?(\d[\d,]*(?:\.\d{1,2})?)", re.I)
_H2S_STORE = re.compile(r"\b(?:on|at|from|@)\s+([A-Z][\w&'.\- ]{1,30}?)(?:\.com)?(?:\s*\(|\s*[|!]|$|\s+\+|\s+-)", re.I)
_REG_TITLE = re.compile(r"\((?:reg(?:ularly)?\.?|was)\s*\$\s?(\d[\d,]*(?:\.\d{1,2})?)\)", re.I)


def parse_hip2save(xml_bytes: bytes, feed: str, industries: list[str]) -> list[Post]:
    out = []
    for it in _items(xml_bytes):
        title = clean(it.findtext("title"))
        link = clean(it.findtext("link"))
        pid = clean(it.findtext("{com-wordpress:feed-additions:1}post-id")) or link
        pm = _H2S.search(title)
        sm = _H2S_STORE.search(title)
        rm = _REG_TITLE.search(title)
        cats = [clean(c.text) for c in it.findall("category")]
        out.append(Post(source="hip2save", id=f"hip2save:{pid}", url=link, title=title,
                        text=_plain(it.findtext("description")), posted_at=_when(it.findtext("pubDate")),
                        price=money(pm.group(1)) if pm else None, reference=money(rm.group(1)) if rm else None,
                        seller=sm.group(1).strip() if sm else "", category=", ".join(cats[:4]), feeds=[feed],
                        feed_industries=list(industries),
                        image=_image(getattr(_child(it, "thumbnail-image"), "text", ""), it.findtext("description"))))
    return out


def parse_bensbargains(xml_bytes: bytes, feed: str, industries: list[str]) -> list[Post]:
    out = []
    for it in _items(xml_bytes):
        title = clean(it.findtext("title"))
        link = clean(it.findtext("link"))
        m = re.search(r"\$\s?(\d[\d,]*(?:\.\d{1,2})?)\s+at\s+(.+)$", title)
        desc = it.findtext("description") or ""
        out.append(Post(source="bensbargains", id=f"bensbargains:{link.rstrip('/').rsplit('/', 1)[-1]}", url=link,
                        title=title, text=_plain(desc), posted_at=_when(it.findtext("pubDate")),
                        price=money(m.group(1)) if m else None, seller=clean(m.group(2)) if m else "", feeds=[feed],
                        feed_industries=list(industries), merchant_link=_first_link(desc), links=_links(desc),
                        image=_image(desc)))
    return out


_INV_NOW = re.compile(r"(?:is|are) (?:now |down to |on sale for )?" + r"\$\s?(\d[\d,]*(?:\.\d{1,2})?)\s*\((\d{1,2})% off\)", re.I)
_INV_OFF_AT = re.compile(r"(\d{1,2})% off at \$\s?(\d[\d,]*(?:\.\d{1,2})?)", re.I)


def parse_theinventory(xml_bytes: bytes, feed: str, industries: list[str]) -> list[Post]:
    out = []
    for it in _items(xml_bytes):
        title = clean(it.findtext("title"))
        text = _plain(it.findtext("description"))
        price = pct_ = None
        m = _INV_NOW.search(text)
        if m:
            price, pct_ = money(m.group(1)), float(m.group(2))
        else:
            m2 = _INV_OFF_AT.search(f"{title} {text}")
            if m2:
                price, pct_ = money(m2.group(2)), float(m2.group(1))
        sm = re.search(r"\b(?:on|at) (Amazon|Walmart|Target|Best Buy|Nordstrom|Macy's|Kohl's|Zappos|REI|Wayfair)\b",
                       f"{title} {text}")
        out.append(Post(source="theinventory", id=f"theinventory:{clean(it.findtext('guid')) or clean(it.findtext('link'))}",
                        url=clean(it.findtext("link")), title=title, text=text, posted_at=_when(it.findtext("pubDate")),
                        price=price, pct_stated=pct_, seller=sm.group(1) if sm else "",
                        category=", ".join(clean(c.text) for c in it.findall("category")[:3]), feeds=[feed],
                        feed_industries=list(industries),
                        image=_image((_child(it, "thumbnail").get("url", "") if _child(it, "thumbnail") is not None
                                      else ""), it.findtext("description"))))
    return out


def parse_9to5toys(xml_bytes: bytes, feed: str, industries: list[str]) -> list[Post]:
    out = []
    for it in _items(xml_bytes):
        title = clean(it.findtext("title"))
        rm = _REG_TITLE.search(title)
        text = _plain(it.findtext("description"))
        sm = (re.search(r"\b(?:via|at|on) (Amazon|Walmart|Target|Best Buy|Woot|Newegg|B&H|Home Depot|Lowe's|eBay)\b", title)
              or re.search(r"\b(Amazon|Walmart|Target|Best Buy|Woot|Newegg|B&H|Home Depot|Lowe's|eBay|Wellbots|Anker)"
                           r"(?:'s official storefront)? (?:is (?:now )?offering|now offers|has|is now selling)\b", text)
              or re.search(r"\b(?:via|at|on) (Amazon|Walmart|Target|Best Buy|Woot|Newegg|B&H|Home Depot|Lowe's|eBay)\b", text))
        out.append(Post(source="9to5toys", id=f"9to5toys:{clean(it.findtext('{com-wordpress:feed-additions:1}post-id')) or clean(it.findtext('link'))}",
                        url=clean(it.findtext("link")), title=title, text=text,
                        posted_at=_when(it.findtext("pubDate")), reference=money(rm.group(1)) if rm else None,
                        seller=sm.group(1) if sm else "", feeds=[feed], feed_industries=list(industries),
                        image=re.sub(r"([?&]w=)\d{4}\b", r"\g<1>600", _image(it.findtext("description")))))
    return out


def parse_dealcatcher(xml_bytes: bytes, feed: str, industries: list[str]) -> list[Post]:
    out = []
    for it in _items(xml_bytes):
        title = clean(it.findtext("title"))
        link = clean(it.findtext("link"))
        m = re.match(r"^(.{2,40}?) - (.+?)\s+\$\s?(\d[\d,]*(?:\.\d{1,2})?)\s*$", title)
        cat = re.search(r"/deals/([\w-]+)/", link)
        out.append(Post(source="dealcatcher", id=f"dealcatcher:{link.rstrip('/').rsplit('/', 1)[-1]}", url=link,
                        title=m.group(2) if m else title, text=_plain(it.findtext("description")),
                        posted_at=_when(it.findtext("pubDate")), price=money(m.group(3)) if m else None,
                        seller=m.group(1) if m else "", category=cat.group(1).replace("-", " ") if cat else "",
                        feeds=[feed], feed_industries=list(industries), image=_image(it.findtext("description"))))
    return out


PARSERS = {"dealnews": parse_dealnews, "slickdeals": parse_slickdeals, "hip2save": parse_hip2save,
           "bensbargains": parse_bensbargains, "theinventory": parse_theinventory, "9to5toys": parse_9to5toys,
           "dealcatcher": parse_dealcatcher}


@dataclass
class FeedPlan:
    """A feed to read: its source, URL, and the industries posts from it belong to (empty = classify by text)."""
    source: str
    name: str
    url: str
    industries: list[str]


def plan(industries: list[str]) -> list[FeedPlan]:
    out: list[FeedPlan] = []
    for ind in industries:
        for cid in DEALNEWS_FEEDS.get(ind, []):
            out.append(FeedPlan("dealnews", f"dealnews c{cid}", dealnews_url(cid), [ind]))
        for slug in HIP2SAVE_FEEDS.get(ind, []):
            out.append(FeedPlan("hip2save", f"hip2save {slug}", f"https://hip2save.com/{slug}/feed/", [ind]))
        for q in SLICKDEALS_QUERIES.get(ind, []):
            out.append(FeedPlan("slickdeals", f"slickdeals q={q}",
                                f"{GENERAL_FEEDS['slickdeals-frontpage']}&q={q.replace(' ', '+')}", []))
    for name, url in GENERAL_FEEDS.items():
        out.append(FeedPlan(name.split("-")[0], name, url, []))
    return out


class DealFeeds:
    def __init__(self, http: PoliteClient):
        self.http = http

    async def read(self, p: FeedPlan) -> tuple[list[Post], str]:
        """(posts, error). Errors are reported per feed so one dead feed can't sink the result."""
        try:
            r = await self.http.get(p.url, ttl_s=TTL["feed"])
        except FetchError as e:
            return [], e.reason
        if r.status != 200:
            return [], f"HTTP {r.status}"
        try:
            return PARSERS[p.source](r.body, p.name, p.industries), ""
        except ET.ParseError as e:
            return [], f"unreadable feed ({e})"


_EXPIRED = re.compile(r"this deal (?:has |is )?expired|deal (?:has )?expired|\bexpired deal\b|this deal is no longer|"
                      r"no longer available|deal has ended|offer has ended|\bsold out\b", re.I)


_DN_STORE_PAGE = re.compile(r"^/s\d+/")
_TITLE_STOP = {"for", "with", "and", "the", "free", "shipping", "shipped", "only", "just", "deal", "off", "via", "from"}


def post_gone(url: str, final_url: str, page_text: str, title: str = "") -> str:
    """Why a deal post is no longer live ('' if it is): the site redirected it elsewhere, the feed now points at a
    store's listing page (dealnews does this for ended deals), the page marks it expired, or the page no longer
    shows the deal's title at all."""
    def path(u: str) -> str:
        return urlsplit(u).path.rstrip("/")
    if final_url and path(final_url) != path(url) and not path(final_url).startswith(path(url)):
        return "the post was removed (redirects elsewhere)"
    if "dealnews.com" in url and _DN_STORE_PAGE.match(path(final_url or url)):
        return "the post was removed (the link now goes to the store's listing page)"
    plain = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", page_text[:300000]))
    m = _EXPIRED.search(plain[:8000])
    if m:
        return f"the post is marked expired ({m.group(0)!r})"
    words = [w for w in re.findall(r"[a-z0-9]{3,}", re.sub(r"\$[\d,.]+", " ", title.lower())) if w not in _TITLE_STOP][:10]
    if len(words) >= 3 and sum(w in plain.lower() for w in words) / len(words) < 0.5:
        return "the post page no longer shows this deal"
    return ""
