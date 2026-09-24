"""Text and JSON views of local reports. Every deal carries its fine print and links to its evidence."""
from __future__ import annotations

import dataclasses
from collections import Counter
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from .adapters.flipp import end_day
from .geo import KM_PER_MILE
from .local import LocalReport, SearchReport
from .models import DealTerms, LocalDeal, OnlineDeal
from .online import OnlineReport

_UNIT = {"lb": "/lb", "each": " ea", "case": "/case"}


def price_label(t: DealTerms) -> str:
    if t.price is None:
        return ""
    if t.quantity > 1:
        s = f"{t.quantity} for ${t.price:,.2f} (${t.unit_price:,.2f} ea)"
    else:
        s = f"${t.price:,.2f}{_UNIT.get(t.unit, '')}"
    return f"from {s}" if t.hedge == "starting at" else s


def saving_label(t: DealTerms) -> str:
    parts = []
    if t.hedge == "no reference" and (t.dollars_off or t.pct_off):
        amount = f"saves ${t.dollars_off:,.2f}" if t.dollars_off else f"{t.pct_off:.0f}% off"
        parts.append(f"{amount} (the ad gives no regular price)")
    elif t.pct_off and t.hedge == "compare at":
        parts.append(f"{t.pct_off:.0f}% below a compare-at value")
    elif t.pct_off:
        parts.append(f"{'up to ' if t.hedge == 'up to' else ''}{t.pct_off:.0f}% off")
    if t.was:
        parts.append(f"{'value' if t.hedge == 'compare at' else 'reg.'} ${t.was:,.2f}")
    return ", ".join(parts)


def _day(d: datetime) -> str:
    return f"{d:%b} {d.day}"          # the ad's own calendar date, in the ad's time zone


def _store(d: LocalDeal) -> str:
    if d.store is None:
        return "; ".join(d.flags)
    s = d.store
    where = f", {s.address}" if s.address else ""
    return f"nearest: {s.name}{where} ({s.distance_km / KM_PER_MILE:.1f} mi)"


def _deal_lines(i: int, d: LocalDeal) -> list[str]:
    t = d.terms
    head = " · ".join(x for x in (saving_label(t), price_label(t)) if x)
    fine = [t.offer] if t.offer and t.offer.lower() not in head.lower() else []
    if t.conditions:
        fine.append("needs: " + ", ".join(t.conditions))
    fine.append(f"ends {end_day(d.valid_to)}")
    links = f"ad: {d.source_url}" + (f"  ·  store page: {d.product_url}" if d.product_url else "")
    return [f"{i:>3}. {head}", f"     {d.merchant} · {d.title}", f"     {' · '.join(fine)}",
            f"     {_store(d)}", f"     {links}"]


def render_deals(rep: LocalReport) -> str:
    miles = rep.radius_km / KM_PER_MILE
    out = [f"Plum · weekly-ad deals near {rep.place.name} (ZIP {rep.place.postal_code}, {miles:.0f} mi)",
           f"as of {rep.generated_at:%Y-%m-%d %H:%M} UTC · {len(rep.flyers)} ads running, "
           f"{rep.items_seen:,} items read, {rep.details_read} full ad records checked",
           "Prices are what each retailer's weekly ad says. Prices and stock can change after an ad is published,",
           "so open the store page (or the ad) before you go.", ""]
    if rep.deals:
        out.append("BEST DEALS: a firm price, and a saving against the store's own regular price")
        for i, d in enumerate(rep.deals, 1):
            out += _deal_lines(i, d)
        out.append("")
    if rep.promos:
        out.append("OTHER OFFERS: percent-off and multi-buy promos, 'up to' savings, and savings without a stated "
                   "regular price")
        for i, d in enumerate(rep.promos, 1):
            out += _deal_lines(i, d)
        out.append("")
    if not (rep.deals or rep.promos):
        out += ["No deals found.", ""]
    if not rep.complete:
        out += ["(Stopped reading full ad records at the budget; lower-ranked deals may be missing.)", ""]
    far = sorted(m for m, p in rep.presence.items() if p.status.value in ("far", "unmapped"))
    if far:
        out += ["No store mapped within range for: " + ", ".join(far) + " (their deals are flagged).", ""]
    if rep.upcoming:
        out += ["Starting soon: " + ", ".join(sorted(f"{f.merchant} ({_day(f.valid_from)})" for f in rep.upcoming)), ""]
    out.append("Left out: " + ", ".join(f"{n:,} {why}" for why, n in rep.skipped.most_common()))
    out.append("Sources: " + " | ".join(f"{s.name}: {'ok' if s.ok else 'FAILED'} ({s.detail})" for s in rep.sources))
    return "\n".join(out)


def render_search(rep: SearchReport) -> str:
    miles = rep.radius_km / KM_PER_MILE
    out = [f"Plum · {rep.query!r} in this week's ads near {rep.place.name} (ZIP {rep.place.postal_code}, {miles:.0f} mi)", ""]
    if not rep.results:
        out.append("Nothing in this week's ads matches.")
    for i, d in enumerate(rep.results, 1):
        out += _deal_lines(i, d)
    out += ["", "Left out: " + (", ".join(f"{n:,} {why}" for why, n in rep.skipped.most_common()) or "nothing"),
            "Sources: " + " | ".join(f"{s.name}: {'ok' if s.ok else 'FAILED'} ({s.detail})" for s in rep.sources)]
    return "\n".join(out)


def basis_label(d: OnlineDeal) -> str:
    """What an online discount is measured against, in plain words."""
    t = d.terms
    if t.hedge == "elsewhere":
        best = max((p for p in d.elsewhere if p.source.startswith("dealnews")), key=lambda p: p.price or 0, default=None)
        return f"vs {'at least ' if best and best.at_least else 'about ' if best and best.approx else ''}" \
               f"${best.price:,.2f} at {best.store}" if best else "vs other stores' prices"
    if t.hedge == "compare at":
        return f"vs a list price of ${t.was:,.2f}" if t.was else "vs a list price"
    if t.hedge == "starting at":
        return "price depends on the option you pick"
    if t.hedge == "up to":
        return "the saving is an 'up to', not this item's guaranteed discount"
    if t.hedge == "no reference":
        return "the post gives no regular price" + (f"; says it saves ${t.dollars_off:,.2f}" if t.dollars_off else "")
    if d.source == "camelcamelcamel":
        return f"vs Amazon's own recent price of ${t.was:,.2f}"
    if t.was and (d.code or "clip coupon" in t.conditions):
        return f"vs ${t.was:,.2f} at {d.store or 'the store'} without the {'code' if d.code else 'coupon'}"
    return f"vs ${t.was:,.2f} regular price" if t.was else ""


def _ago(then: Optional[datetime], now: datetime) -> str:
    if then is None:
        return ""
    hours = max(0, int((now - then).total_seconds() // 3600))
    return "posted just now" if hours < 1 else f"posted {hours} h ago" if hours < 48 else f"posted {hours // 24} days ago"


def render_online(rep: OnlineReport) -> str:
    near = f", compared with store ads near {rep.compared_near.name}" if rep.compared_near else ""
    out = [f"Plum · biggest online discounts right now{near}",
           "Prices move fast online and codes run out; open the post or store page before you buy.", ""]
    for title, deals in (("BIGGEST DISCOUNTS", rep.deals), ("POPULAR, NO STATED DISCOUNT", rep.popular)):
        if not deals:
            continue
        out.append(title)
        for i, d in enumerate(deals, 1):
            t = d.terms
            head = " · ".join(x for x in (f"{t.pct_off:.0f}% off" if t.pct_off else "", price_label(t), basis_label(d)) if x)
            meta = [f"needs: {', '.join(t.conditions)}" if t.conditions else "",
                    f"{d.source} +{d.votes}" if d.votes else ("dealnews staff pick" if d.staff_pick else d.source),
                    d.history, _ago(d.posted, rep.generated_at)]
            out += [f"{i:>3}. {head}", f"     {' · '.join(x for x in (d.store, d.title) if x)}",
                    f"     {' · '.join(x for x in meta if x)}"]
            if d.elsewhere:
                out.append("     elsewhere: " + "; ".join(
                    f"{p.store} {'≥' if p.at_least else '~' if p.approx else ''}${p.price:,.2f} ({p.source})"
                    for p in d.elsewhere if p.price))
            out.append(f"     post: {d.url}" + (f"  ·  store: {d.store_url}" if d.store_url else ""))
        out.append("")
    if not (rep.deals or rep.popular):
        out += ["No online deals found.", ""]
    if rep.compared_near:
        out.append(f"Looked up {rep.looked_up} model numbers in this week's store ads near {rep.compared_near.name}.")
    out.append("Left out: " + (", ".join(f"{n:,} {why}" for why, n in rep.skipped.most_common()) or "nothing"))
    out.append("Sources: " + " | ".join(f"{s.name}: {'ok' if s.ok else 'FAILED'} ({s.detail})" for s in rep.sources))
    return "\n".join(out)


def jsonable(x: Any) -> Any:
    if isinstance(x, LocalDeal):
        return dict(jsonable(dataclasses.asdict(x)), price_label=price_label(x.terms), saving_label=saving_label(x.terms),
                    unit_price=x.terms.unit_price)
    if isinstance(x, OnlineDeal):
        return dict(jsonable(dataclasses.asdict(x)), price_label=price_label(x.terms), basis=basis_label(x),
                    unit_price=x.terms.unit_price)
    if dataclasses.is_dataclass(x) and not isinstance(x, type):
        return {f.name: jsonable(getattr(x, f.name)) for f in dataclasses.fields(x)}
    if isinstance(x, Enum):
        return x.value
    if isinstance(x, datetime):
        return x.isoformat()
    if isinstance(x, (Counter, dict)):
        return {str(k): jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple, set)):
        return [jsonable(v) for v in x]
    return x
