"""Command line.

  plum deals "Austin, TX"                         this week's best weekly-ad deals near a city or ZIP
  plum search "chicken breast" --near 78701       one item across nearby stores' ads, cheapest first
  plum online --near 78701                        the biggest online discounts, with the same product elsewhere
  plum demo "sony xm5"                            the product engine on simulated stores (no network)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Optional

from .net import HttpError


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="plum", description="Find the plum deal near you.")
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("deals", help="this week's best weekly-ad deals near a city or ZIP")
    d.add_argument("where", help='a US city ("Austin, TX") or ZIP code')
    d.add_argument("--radius", type=float, default=25.0, help="miles around the city center (default 25)")
    d.add_argument("--limit", type=int, default=25, help="deals to list (default 25)")
    d.add_argument("--promos", type=int, default=10, help="promotions to list (default 10)")
    d.add_argument("--per-store", type=int, default=3, help="most deals shown from one merchant (default 3)")
    d.add_argument("--store", action="append", default=[], help="only this merchant; repeatable")
    d.add_argument("--category", default="", help='an ad category such as "Groceries" or "Electronics"')
    d.add_argument("--confirmed-only", action="store_true", help="only merchants with a mapped store in range")

    s = sub.add_parser("search", help="one item across nearby stores' ads, cheapest first")
    s.add_argument("query")
    s.add_argument("--near", required=True, help='a US city ("Austin, TX") or ZIP code')
    s.add_argument("--radius", type=float, default=25.0)
    s.add_argument("--limit", type=int, default=20)
    s.add_argument("--confirmed-only", action="store_true")

    o = sub.add_parser("online", help="the biggest online discounts right now, with the same product elsewhere")
    o.add_argument("--near", default="", help="a city or ZIP whose store ads to compare against (optional)")
    o.add_argument("--min", type=float, default=30.0, help="smallest discount to list, in percent (default 30)")
    o.add_argument("--limit", type=int, default=30)

    for sp in (d, s, o):
        sp.add_argument("--json", action="store_true", help="machine-readable output")
        sp.add_argument("--no-cache", action="store_true", help="ignore cached responses")

    m = sub.add_parser("demo", help="the product engine on simulated stores (no network)")
    m.add_argument("query", nargs="*", default=["sony", "xm5"])
    return p


async def _online(args: argparse.Namespace) -> int:
    from .net import DiskCache, HttpClient
    from .local import POLITE_INTERVALS
    from .online import OnlineDealService
    from .render import jsonable, render_online

    svc = OnlineDealService(HttpClient(cache=None if args.no_cache else DiskCache(), min_interval_s=POLITE_INTERVALS))
    try:
        rep = await svc.deals(where=args.near, min_pct=args.min, limit=args.limit)
    finally:
        await svc.http.aclose()
    print(json.dumps(jsonable(rep), indent=2) if args.json else render_online(rep))
    return 0 if all(s.ok for s in rep.sources) else 1


async def _local(args: argparse.Namespace) -> int:
    from .local import LocalDealService
    from .render import jsonable, render_deals, render_search

    svc = LocalDealService.live(cache=not args.no_cache)
    try:
        if args.cmd == "deals":
            rep = await svc.deals(args.where, radius_mi=args.radius, limit=args.limit, promo_limit=args.promos,
                                  per_store=args.per_store, merchants=args.store, category=args.category,
                                  confirmed_only=args.confirmed_only)
            text = render_deals(rep)
        else:
            rep = await svc.search(args.query, args.near, radius_mi=args.radius, limit=args.limit,
                                   confirmed_only=args.confirmed_only)
            text = render_search(rep)
    finally:
        await svc.aclose()
    print(json.dumps(jsonable(rep), indent=2) if args.json else text)
    return 0 if all(s.ok for s in rep.sources) else 1


async def _demo(query: str) -> int:
    from .demo_data import POLICIES, build_service

    svc = build_service()
    rep = await svc.find(query)
    if rep.product is None:
        print(f"No product matched ({rep.how})")
        return 1
    print(f"\n{rep.product.title}   (found by {rep.how}; SIMULATED stores, prices and codes)")
    print("stores:", ", ".join(f"{a.retailer}:{a.status}/{len(a.listings)}" for a in rep.adapters))
    for i, o in enumerate(rep.offers):
        code = (f"code {o.best_coupon.coupon.code} -${o.code_discount:.2f} ({o.best_coupon.reliability:.0%} works)"
                if o.best_coupon and o.code_discount else "no code")
        print(f"{'BEST' if i == 0 else '    '} {POLICIES[o.listing.retailer].name:<10} sticker ${o.listing.price:>7.2f}  "
              f"{code:<40} ship ${o.shipping:>5.2f}  pay ${o.pay_today:>7.2f}  net ${o.net:>7.2f}  [{o.match.tier.value}]")
    for s in rep.skipped:
        print(f"skip {s.listing.retailer:<10} ${s.listing.price:>7.2f}  {s.listing.title[:60]:<60} -> {s.why}")
    if rep.best:
        res = await svc.test_codes(rep.best.listing, rep.product)
        print("\nprobe:", ", ".join(f"{s.code}:{'ok -$%.2f' % s.discount if s.ok else s.why}" for s in res.steps),
              "| winner:", res.winner)
        again = await svc.find(query)
        print(f"after probe: pay ${again.best.pay_today:.2f} at {POLICIES[again.best.listing.retailer].name} "
              f"(verified={again.best.verified})")
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.cmd == "demo":
            return asyncio.run(_demo(" ".join(args.query)))
        if args.cmd == "online":
            return asyncio.run(_online(args))
        return asyncio.run(_local(args))
    except LookupError as e:
        print(f"plum: {e}", file=sys.stderr)
        return 2
    except (HttpError, RuntimeError) as e:
        print(f"plum: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
