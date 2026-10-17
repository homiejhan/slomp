"""Replay deal-site posts through Slomp's own feed parsers and filters, offline.

    slomp replay posts.json [--now 2026-10-17T12:00:00-05:00] [--json]

For the comparisons against a manual search (docs/VERIFICATION.md): a search by hand finds posts on the sites Slomp
reads, and replaying their words shows what Slomp makes of each one without reaching the sites. Each post becomes the
RSS item its site's feed carries, is read by that site's parser, then by the filter for its kind: a store's sale
(the Sales tab), a single-product online deal (Online) or a restaurant chain's promotion. One post:

    {"source": "dealnews" | "slickdeals" | "hip2save" | "9to5toys" | "theinventory" | "bensbargains" | "dealcatcher",
     "kind": "sale" | "online" | "promo", "title": "...", "text": "...", "url": "...",
     "posted": "2026-10-16T10:00-05:00",
     "categories": [...],                      # the feed's own categories (Hip2Save, The Inventory)
     "seller": "...", "price": "...", "deal_type": "...", "category": "...", "expires": "2026-10-19"}   # dealnews

A dealnews post with no "expires" gets one of dealnews' placeholder ends (30 days on), which Slomp knows is not the
deal's end. What a replay leaves out: a sale's check on the store's own page, other stores' prices for an online
deal, a promotion's nearest branch. And it reads only the words given it, so a title a search engine cut short is
read as cut.
"""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path
from typing import Optional
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

from ..online import OnlineDeals, OnlineResult
from ..promos import RestaurantPromos
from ..sales import StoreSales
from ..sources.feeds import PARSERS, Post
from ..sources.stores import RestaurantLocator

CENTRAL = ZoneInfo("America/Chicago")
KINDS = ("sale", "online", "promo")


def _x(v) -> str:
    return escape(str(v or ""))


def post_of(d: dict, i: int, now: datetime) -> Post:
    """The post as its site's parser reads it from a feed item carrying these fields."""
    src = d.get("source", "dealnews")
    if src not in PARSERS:
        raise ValueError(f"unknown source {src!r}: one of {', '.join(PARSERS)}")
    posted = datetime.fromisoformat(d["posted"]) if d.get("posted") else now
    if posted.tzinfo is None:
        posted = posted.replace(tzinfo=CENTRAL)
    made_up = {"dealnews": f"https://www.dealnews.com/x/{22000000 + i}.html",
               "slickdeals": f"https://slickdeals.net/f/{19000000 + i}-x"}
    url = d.get("url") or made_up.get(src, f"https://x.example/{i}")
    item = [f"<title>{_x(d.get('title'))}</title>", f"<link>{_x(url)}</link>", f"<guid>{_x(url)}</guid>",
            f"<pubDate>{format_datetime(posted.astimezone(timezone.utc))}</pubDate>"]
    if src == "dealnews":
        exp = d.get("expires")
        if exp and len(exp) == 10:                 # a date: its last minute in Texas, as an editor sets a real end
            exp = datetime.fromisoformat(exp).replace(hour=23, minute=59, tzinfo=CENTRAL).isoformat()
        exp = exp or (posted + timedelta(days=30)).astimezone(timezone.utc).isoformat()
        item += [f"<description>{_x(d.get('text'))}</description>", f"<dn:expires>{_x(exp)}</dn:expires>",
                 f"<dn:price>{_x(d.get('price'))}</dn:price>", f"<dn:retailer>{_x(d.get('seller'))}</dn:retailer>",
                 f"<dn:dealType>{_x(d.get('deal_type'))}</dn:dealType>",
                 f"<dn:category>{_x(d.get('category'))}</dn:category>"]
    elif src == "slickdeals":
        item.append(f"<content:encoded>{_x(d.get('text'))}</content:encoded>")
    else:
        item.append(f"<description>{_x(d.get('text'))}</description>")
        item += [f"<category>{_x(c)}</category>" for c in d.get("categories", [])]
    xml = ('<rss xmlns:dn="https://www.dealnews.com/ns/rss/1.0.htm" '
           'xmlns:content="http://purl.org/rss/1.0/modules/content/">'
           f"<channel><item>{''.join(item)}</item></channel></rss>").encode()
    return PARSERS[src](xml, "replay", d.get("feed_industries", []))[0]


def verdict(d: dict, i: int, now: datetime, promos: Optional[RestaurantPromos] = None) -> dict:
    """What Slomp makes of one post: kept or not, why not, and what it read."""
    kind = d.get("kind", "sale")
    if kind not in KINDS:
        raise ValueError(f"unknown kind {kind!r}: one of {', '.join(KINDS)}")
    p = post_of(d, i, now)
    out = {"title": d.get("title", ""), "source": p.source, "kind": kind}
    if kind == "sale":
        ex: Counter = Counter()
        s = StoreSales(None, None).sale(p, now, ex)
        return {**out, "kept": s is not None, "why": ", ".join(ex),
                **({"store": s.store_name, "offer": s.offer, "badge": s.badge, "code": s.code,
                    "ends": s.ends_at.astimezone(CENTRAL).date().isoformat() if s.ends_at else None,
                    "ends_how": s.ends_how, "industries": s.industries, "conditions": s.conditions} if s else {})}
    if kind == "online":
        res = OnlineResult(["replay"])
        o = OnlineDeals(None, None)._deal(p, now, res)
        why = ", ".join(res.excluded) if o is None else "" if o.pct else "no reference price: never ranked"
        return {**out, "kept": bool(o and o.pct), "why": why,
                **({"price": o.price, "reference": o.reference_price, "basis": o.basis, "pct": o.pct,
                    "seller": o.seller, "industries": o.industries, "conditions": o.conditions} if o else {})}
    ex = Counter()
    promos = promos or RestaurantPromos(None, RestaurantLocator())
    r = promos.offer(p, CENTRAL, now, now + timedelta(days=7), ex)
    deal = r[1] if r else None
    return {**out, "kept": r is not None, "why": ", ".join(ex),
            **({"chain": deal.merchant, "from": deal.valid_from.date().isoformat(),
                "to": deal.valid_to.date().isoformat(), "dates": deal.raw.get("dates"),
                "conditions": deal.terms.conditions} if deal else {})}


def replay(posts: list[dict], now: datetime) -> list[dict]:
    promos = RestaurantPromos(None, RestaurantLocator())
    return [verdict(d, i, now, promos) for i, d in enumerate(posts)]


def _line(v: dict) -> str:
    head = f"[{v['kind']}] {v['source']}: {v['title']}"
    if not v["kept"]:
        return f"{head}\n    left out: {v['why'] or 'no reason counted'}"
    if v["kind"] == "sale":
        what = (f"{v['store']} · {v['offer']} · code {v['code'] or '-'} · ends {v['ends'] or '-'} "
                f"({v['ends_how']}) · {','.join(v['industries']) or 'no industry'}")
    elif v["kind"] == "online":
        what = (f"${v['price']} vs ${v['reference']} ({v['basis']}) = {v['pct']}% · {v['seller'] or '-'} · "
                f"{','.join(v['industries'])}")
    else:
        what = f"{v['chain']} · {v['from']} to {v['to']} ({v['dates']})"
    return f"{head}\n    kept: {what}"


def main(path: Path, now: Optional[str] = None, as_json: bool = False) -> int:
    when = datetime.fromisoformat(now) if now else datetime.now(CENTRAL)
    if when.tzinfo is None:
        when = when.replace(tzinfo=CENTRAL)
    out = replay(json.loads(path.read_text()), when)
    if as_json:
        print(json.dumps(out, indent=1, default=str))
    else:
        print("\n".join(_line(v) for v in out))
        kept = Counter((v["kind"], v["kept"]) for v in out)
        print("\n" + "; ".join(f"{k}: {kept[(k, True)]} kept, {kept[(k, False)]} left out"
                               for k in KINDS if kept[(k, True)] or kept[(k, False)]))
    return 0
