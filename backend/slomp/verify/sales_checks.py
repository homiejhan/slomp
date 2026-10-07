"""Live checks for online stores' sales (slomp verify --plan sales). Each test reads its source again, now, rather
than trusting what the pipeline read; the blind-judge tests are set up in sales_run.py.

  S-SRC   the post page shows the store, every number of the offer and the code, and is not taken down or expired
  S-END   the end Slomp shows is the one the source states (or the post states none), and the sale is live now
  S-STORE the post names the store Slomp shows, or links to its site
  S-OFFER the badge, the offer line and the code agree with the post's own title and text
  S-QUAL  across a whole list: no duplicates, nothing ended or stale, best-first order, every card complete
"""
from __future__ import annotations

import html as htmllib
import re
from datetime import date, datetime, timedelta
from urllib.parse import unquote, urlsplit
from zoneinfo import ZoneInfo

from ..config import TTL
from ..http import Blocked, Disallowed, FetchError, PoliteClient
from ..models import StoreSale
from ..promos import _MONTHS, _date
from ..sales import POSTED_DAYS, UNDATED_DAYS, _words
from ..sources.feeds import post_gone
from ..stores_online import by_key
from .checks import FAIL, INCONCLUSIVE, PASS

CT = ZoneInfo("America/Chicago")


def plain(page: str) -> str:
    body = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", page)
    text = htmllib.unescape(re.sub(r"<[^>]+>", " ", body))
    return re.sub(r"\s+", " ", text.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"'))


def post_body(url: str, page: str) -> tuple[str, str]:
    """(the post's own text, the HTML it came from), without the site's menus and the other deals beside it, whose
    dates and stores would otherwise answer for this one."""
    host = urlsplit(url).netloc
    if host.endswith("dealnews.com"):
        i = page.find('class="snippet summary"')
        if i >= 0:
            chunk = page[i:page.find("</div>", i)]
            m = re.search(r'title="([^"]*)"', chunk)
            return plain((htmllib.unescape(m.group(1)) if m else "") + " " + chunk + ">"), chunk
    if host.endswith("hip2save.com"):
        i = page.find('class="entry-content"')
        if i >= 0:                                  # the article, up to its end (related posts follow it)
            j = page.find("</article>", i)
            chunk = page[i:j if j > i else i + 40000]
            return plain(chunk), chunk
    if host.endswith("slickdeals.net"):              # the summary, then the editors' notes ("Offer valid through ...")
        og = re.search(r'<meta[^>]+property="og:description"[^>]+content="([^"]*)"', page)
        notes = re.findall(r'<div class="dealDetailsRawHtml[^"]*"[^>]*>(.*?)</div>', page, re.S)
        chunk = (htmllib.unescape(og.group(1)) if og else "") + " " + " ".join(notes)
        return plain(chunk), chunk
    m = re.search(r'class="[^"]*\b(?:post-content|entry-content|article-content)\b[^"]*"', page)    # 9to5Toys and others
    if m:
        j = page.find("</article>", m.start())
        chunk = page[m.start():j if j > m.start() else m.start() + 40000]
        return plain(chunk), chunk
    m = re.search(r'<meta[^>]+property="og:description"[^>]+content="([^"]*)"', page)    # Slickdeals
    if m:
        return plain(htmllib.unescape(m.group(1))), m.group(1)
    return plain(page)[:4000], page[:20000]


async def read(http: PoliteClient, url: str) -> tuple[str, str, str, str]:
    """(plain text, html, final url, why it couldn't be read): read now, not from the cache."""
    try:
        r = await http.get(url, ttl_s=TTL["page"], html=True, use_cache=False)
    except (Blocked, Disallowed) as e:
        return "", "", "", e.reason
    except FetchError as e:
        return "", "", "", e.reason
    if r.status == 404:
        return "", r.text, r.final_url, "HTTP 404"
    if r.status != 200:
        return "", "", "", f"HTTP {r.status}"
    return plain(r.text), r.text, r.final_url, ""


def names_of(s: StoreSale) -> list[str]:
    st = by_key().get(s.store)
    return sorted({s.store_name, *(st.names if st else ())}, key=len, reverse=True)


def _has(text: str, phrase: str) -> bool:
    return re.search(r"(?<![\w])" + re.escape(phrase.replace("’", "'")) + r"(?![\w])", text, re.I) is not None


def offer_numbers(s: StoreSale) -> list[str]:
    """The figures the offer line states, as a post would print them."""
    out = []
    for v in (s.pct, s.upto, s.extra, s.extra_upto):
        if v is not None:
            out.append(f"{v:g}%")
    for v in (s.off, s.min_spend):
        if v is not None:
            out.append(f"${v:,.2f}".replace(".00", ""))
    m = re.match(r"buy (\d+) get (\d+) (?:(\d+)% off|free)", s.bogo or "")
    if m and m.group(3):
        out.append(f"{m.group(3)}%")
    return out


def _num_in(text: str, n: str) -> bool:
    t = text.replace(",", "")
    k = n.replace(",", "")
    if k.endswith("%"):
        return re.search(r"(?<![\d.])" + re.escape(k[:-1]) + r"\s?(?:%|percent)", t, re.I) is not None
    return re.search(re.escape(k) + r"(?![\d])", t) is not None


async def sale_source(http: PoliteClient, s: StoreSale) -> tuple[str, dict]:
    text, page, final, why = await read(http, s.source_url)
    if why == "HTTP 404":
        return FAIL, {"why": "the post was removed (404)", "url": s.source_url}
    if why:
        return INCONCLUSIVE, {"why": why, "url": s.source_url}
    gone = post_gone(s.source_url, final, page, s.title)
    if gone:
        return FAIL, {"why": gone, "url": s.source_url}
    body, _ = post_body(final or s.source_url, page)
    title = re.search(r"(?is)<title[^>]*>(.*?)</title>", page)
    text = f"{plain(title.group(1)) if title else ''} {body}"
    problems = []
    if not any(_has(text, n) for n in names_of(s)):
        problems.append(f"the page doesn't name {s.store_name}")
    for n in offer_numbers(s):
        if not _num_in(text, n):
            problems.append(f"the page doesn't say {n}")
    if s.code and s.code not in text:
        problems.append(f"the page doesn't show the code {s.code}")
    return (FAIL if problems else PASS), {"problems": problems, "url": s.source_url, "offer": s.offer, "code": s.code}


# The end a post states, read independently of the pipeline's rules: a month and day, or m/d, after an end word, a
# range's last day, or "today only".
_MON = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"
_D = r"(\d{1,2})(?:st|nd|rd|th)?"
_ENDS = re.compile(r"\b(?:ends?|ending|expires?|through|thru|until|till|valid (?:through|thru|until))\s+(?:on\s+)?"
                   r"(?:\w+day,?\s+)?(?:" + _MON + r"\s+" + _D + r"|(\d{1,2})/(\d{1,2}))", re.I)
_RANGE = re.compile(_MON + r"\s+" + _D + r"\s*(?:-|–|to|through)\s*(?:" + _MON + r"\s+)?" + _D + r"\b|"
                    r"\b(\d{1,2})/(\d{1,2})(?:/\d{2,4})?\s*(?:-|–|to)\s*(\d{1,2})/(\d{1,2})\b", re.I)
_TODAY = re.compile(r"\btoday[- ]only\b|\bends today\b|\bone[- ]day (?:only|sale)\b", re.I)


def stated_ends(text: str, posted: date) -> set[date]:
    out: set[date] = set()
    for m in _ENDS.finditer(text):
        d = (_date(_MONTHS[m.group(1)[:3].lower()], int(m.group(2)), posted) if m.group(1)
             else _date(int(m.group(3)), int(m.group(4)), posted) if 1 <= int(m.group(3)) <= 12 else None)
        if d:
            out.add(d)
    for m in _RANGE.finditer(text):
        if m.group(1):
            d = _date(_MONTHS[(m.group(3) or m.group(1))[:3].lower()], int(m.group(4)), posted)
        else:
            d = _date(int(m.group(7)), int(m.group(8)), posted) if 1 <= int(m.group(7)) <= 12 else None
        if d:
            out.add(d)
    if _TODAY.search(text):
        out.add(posted)
    return {d for d in out if d >= posted - timedelta(days=1)}


def end_day(ends: datetime) -> date:
    """The day a shopper would say a sale ends: one ending in the small hours here (11:59 PM Pacific is 1:59 AM
    Central) ends the day before, as the page shows it."""
    local = ends.astimezone(CT)
    return (local - timedelta(hours=4)).date() if local.hour < 4 else local.date()


async def sale_dates(http: PoliteClient, s: StoreSale, now: datetime) -> tuple[str, dict]:
    det = {"ends_at": s.ends_at, "ends_how": s.ends_how, "posted_at": s.posted_at, "url": s.source_url}
    if s.ends_at and s.ends_at < now:
        return FAIL, {**det, "why": "shown after its end"}
    if s.posted_at and now - s.posted_at > timedelta(days=POSTED_DAYS):
        return FAIL, {**det, "why": f"posted over {POSTED_DAYS} days ago"}
    if not s.ends_at and (not s.posted_at or now - s.posted_at > timedelta(days=UNDATED_DAYS)):
        return FAIL, {**det, "why": f"no end and posted over {UNDATED_DAYS} days ago"}
    _, page, final, why = await read(http, s.source_url)
    if why:
        return INCONCLUSIVE, {**det, "why": why}
    text, _ = post_body(final or s.source_url, page)
    posted = (s.posted_at or now).astimezone(CT).date()
    found = stated_ends(f"{s.title}. {text}", posted)
    det["page_ends"] = sorted(d.isoformat() for d in found)
    if not s.ends_at:
        later = {d for d in found if d >= now.astimezone(CT).date() - timedelta(days=1)}
        if later:
            return FAIL, {**det, "why": "the post states an end Slomp didn't show"}
        return PASS, det
    mine = end_day(s.ends_at)
    det["slomp_end_day"] = mine.isoformat()
    if mine in found or any(abs((mine - d).days) <= 1 and s.ends_how.endswith("end date") for d in found):
        return PASS, det                       # the post states this end (a source's end date may be a time zone off)
    if found:
        return FAIL, {**det, "why": "the post states a different end"}
    if s.ends_how.startswith("the post says"):
        quote = s.ends_how.split("“", 1)[-1].rstrip("”").replace("’", "'")
        if quote.lower() not in f"{s.title}. {text}".lower():
            return FAIL, {**det, "why": f"the post no longer says {quote!r}"}
    return PASS, det


_PLACE = r"(?:at|on|from|via|over to|head to|run to|to)\s+"


async def sale_store(http: PoliteClient, s: StoreSale) -> tuple[str, dict]:
    _, page, final, why = await read(http, s.source_url)
    if why:
        return INCONCLUSIVE, {"why": why, "url": s.source_url}
    text, html = post_body(final or s.source_url, page)
    names = names_of(s)
    st = by_key().get(s.store)
    said = [n for n in names if re.search(_PLACE + re.escape(n) + r"(?:\.com)?\b", text, re.I) or
            re.search(r"\bShop Now at " + re.escape(n), text, re.I) or _has(text, f"{n}.com") or
            re.search(r"(?:^|[.!?]\s+)" + re.escape(n) + r"(?:\s+\[[\w.]+\])?\s+(?:is (?:now )?offering|offers|has|is selling|"
                      r"now offers|is (?:now )?taking|knocks|takes|discounts)\b", text, re.I)]
    links = unquote(unquote(" ".join(re.findall(r'href="([^"]+)"', html)))).lower()
    linked = [d for d in (st.domains if st else ()) if d in links]
    starts = [n for n in names if re.match(r"\W*" + re.escape(n) + r"\b", s.title, re.I)]
    det = {"store": s.store_name, "said": said[:3], "linked": linked[:3], "title_starts": starts[:1], "url": s.source_url}
    return (PASS if said or linked or starts else FAIL), det


_PCT_ANY = re.compile(r"(\d{1,3})\s?%")
_USD_ANY = re.compile(r"\$\s?(\d[\d,]*)(?:\.\d\d)?")


def sale_offer(s: StoreSale) -> tuple[str, dict]:
    """The badge and the offer line come from the title's own figures; a firm percent is not an "up to" one in
    disguise; the code is in the post as written."""
    title = s.title.replace("’", "'")
    pcts = {float(x) for x in _PCT_ANY.findall(title)}
    usds = {float(x.replace(",", "")) for x in _USD_ANY.findall(title)}
    problems = []
    for part in (s.badge, s.offer):
        for x in _PCT_ANY.findall(part):
            if float(x) not in pcts:
                problems.append(f"{x}% is not in the title")
        for x in _USD_ANY.findall(part):
            if float(x.replace(",", "")) not in usds:
                problems.append(f"${x} is not in the title")
    if s.pct is not None and not s.upto and re.search(r"\bup\s?to\s+(?:an?\s+)?(?:extra\s+)?" + f"{s.pct:g}" + r"\s?%",
                                                      title, re.I):
        problems.append(f"{s.pct:g}% is shown as firm but the title says up to")
    text = s.raw.get("text", "")
    if s.code and s.code not in f"{s.title} {text}":
        problems.append(f"the code {s.code} is not in the post")
    if s.code and s.code.upper() in {"CODE", "PROMO", "NEEDED", "REQUIRED", "COUPON"}:
        problems.append(f"{s.code} is a word, not a code")
    return (FAIL if problems else PASS), {"title": s.title, "badge": s.badge, "offer": s.offer, "code": s.code,
                                          "problems": problems}


def quality(sales: list[StoreSale], now: datetime, what: str) -> tuple[str, dict]:
    """One whole list, as a search shows it."""
    problems = []
    if what == "duplicates":
        seen: dict = {}
        for s in sales:
            key = (s.store or s.store_name, s.badge, s.ends_at.date() if s.ends_at else None)
            for other in seen.get(key, []):
                a, b = _words(s.name), _words(other.name)
                if a == b or (a and b and len(a & b) / min(len(a), len(b)) >= 0.6):
                    problems.append(f"{other.id} and {s.id}: {s.store_name} {s.badge} {s.name!r}")
            seen.setdefault(key, []).append(s)
        if len({s.id for s in sales}) != len(sales):
            problems.append("the same id twice")
    elif what == "fresh":
        for s in sales:
            if s.ends_at and s.ends_at < now:
                problems.append(f"{s.id} ended {s.ends_at}")
            elif s.posted_at and now - s.posted_at > timedelta(days=POSTED_DAYS):
                problems.append(f"{s.id} posted {s.posted_at}")
            elif not s.ends_at and (not s.posted_at or now - s.posted_at > timedelta(days=UNDATED_DAYS)):
                problems.append(f"{s.id} has no end and was posted {s.posted_at}")
    elif what == "order":
        for a, b in zip(sales, sales[1:]):
            if b.score > a.score:
                problems.append(f"{b.id} ({b.score}) after {a.id} ({a.score})")
    elif what == "complete":
        for s in sales:
            missing = [k for k in ("store_name", "name", "offer", "badge", "source_url") if not getattr(s, k)]
            if missing or not s.industries or not s.source_url.startswith("https://"):
                problems.append(f"{s.id} lacks {missing or 'industries or an https link'}")
    return (FAIL if problems else PASS), {"check": what, "sales": len(sales), "problems": problems[:12]}
