"""Command line.

    slomp cities [QUERY]                                    find a city id
    slomp industries                                        the fixed industry list
    slomp local CITY -i tech,sports [-r 25] [--json]        Output 1: deals near CITY in the next 7 days
    slomp regulars [--all]                                  the regular deals Slomp knows, with each one's evidence
    slomp online -i tech,fashion [-n 15] [--json]           Output 2: biggest verified online discounts
    slomp verify --iteration N [--tests 200] [--seed S]     the live verification harness
    slomp verify --iteration N --plan regulars              the same for regular deals (Austin, Houston, Dallas areas)
    slomp serve [--port 8000]                               the web page and API
    slomp site build [--out site]                           the published site: data files the page searches itself
"""
from __future__ import annotations

import argparse
import asyncio
import errno
import json
import socket
import sys
from collections import Counter
from datetime import date
from pathlib import Path

from . import industries as ind
from .models import BASIS_TEXT
from .reference import find_cities
from .service import InputError, SlompService


def _money(v) -> str:
    return f"${v:,.2f}" if isinstance(v, (int, float)) else "—"


def print_local(res, limit: int) -> None:
    c = res.city
    print(f"\n{c.name}, TX (ZIP {c.zip}) · {', '.join(ind.BY_ID[i].name for i in res.industries)} · within "
          f"{res.radius_mi:g} mi · {res.window_start:%a %b %-d} to {res.window_end:%a %b %-d}")
    print(f"{len(res.deals)} deals, {len(res.promotions)} promotions, {len(res.unconfirmed)} with unconfirmed stores, "
          f"{len(res.regulars)} regular deals\n")
    for title, rows in (("DEALS", res.deals), ("PROMOTIONS", res.promotions), ("STORE NOT CONFIRMED", res.unconfirmed)):
        if not rows:
            continue
        print(title)
        for d in rows[:limit]:
            st = d.store
            where = f"{st.distance_mi:g} mi" if st else "store not mapped"
            ends = "ends today" if d.ends_in_days == 0 else f"ends {d.valid_to:%a %b %-d}"
            starts = f"starts {d.valid_from:%a %b %-d}, " if d.starts_in_days > 0 else ""
            print(f"  {d.terms.pct or 0:5.1f}%  {d.merchant} · {d.title[:70]}")
            print(f"          {d.terms.summary}  [{BASIS_TEXT.get(d.terms.basis, '')}]  {starts}{ends} · {where}"
                  f"{' · ' + ', '.join(d.terms.conditions) if d.terms.conditions else ''}")
        print()
    print_regulars(res, limit)
    print("left out: " + ", ".join(f"{k} {v}" for k, v in res.excluded.most_common()))


def print_regulars(res, limit: int) -> None:
    """Regular deals by the day they next run."""
    by_day: dict[str, list] = {}
    for d in res.regulars:
        by_day.setdefault(d.regular["next"][0], []).append(d)
    if by_day:
        print("REGULAR DEALS (they repeat on these days)")
    for day in sorted(by_day):
        rows = by_day[day]
        print(f"  {date.fromisoformat(day):%A %b %-d}")
        for d in rows[:limit]:
            r = d.regular
            when = " · ".join(x for x in (r["days_text"], r["time_text"]) if x)
            print(f"    {d.merchant} · {d.title[:84]}")
            print(f"          {when} · {d.store.distance_mi:g} mi · {r['status_text']}"
                  f"{' · ' + ', '.join(d.terms.conditions) if d.terms.conditions else ''}")
        if len(rows) > limit:
            print(f"    ... and {len(rows) - limit} more")
    if by_day:
        print()


async def _regulars(show_all: bool) -> int:
    """Every regular deal Slomp would show somewhere in Texas, and the state of its evidence."""
    svc = SlompService()
    try:
        rset = await svc.regulars.all(refresh=True)
    finally:
        await svc.aclose()
    rows = sorted(rset.regulars, key=lambda r: (r.origin != "registry", r.brand.lower(), r.schedule.days))
    for r in rows:
        if r.origin == "list" and not show_all:
            continue
        print(f"{r.status:9s} {r.brand} · {r.offer[:76]}")
        print(f"          {' · '.join(x for x in (r.schedule.days_text(), r.schedule.time_text()) if x)}")
        for e in r.evidence:
            seen = f"read {e.checked_at:%b %-d}" if e.checked_at else "not readable"
            dated = f", page dated {e.page_date:%b %-d %Y}" if e.page_date else ""
            state = "ok" if e.live else ("found, too old" if e.found else e.note or "words not found")
            print(f"          [{e.kind}] {e.source}: {state} ({seen}{dated})")
    by = Counter(r.status for r in rset.regulars)
    print(f"\n{len(rset.regulars)} regular deals: " + ", ".join(f"{by[k]} {k}" for k in ("confirmed", "listed", "reported", "yours")
                                                                if by[k]))
    print("left out: " + ", ".join(f"{k.removeprefix('regular deal: ')} {v}" for k, v in rset.excluded.most_common()))
    for s in rset.sources:
        if not s.get("ok", True):
            print(f"source problem: {s['name']}: {s.get('error', '')}")
    return 0


def print_online(res, limit: int) -> None:
    for i, rows in res.deals.items():
        print(f"\n{ind.BY_ID[i].name.upper()}: biggest discounts online")
        for d in rows[:limit]:
            print(f"  {d.discount_pct or 0:5.1f}%  {_money(d.price)} at {d.seller or '?'} · {d.title[:70]}")
            ref = f"vs {_money(d.market_median)} median at other stores" if d.basis == "market" else (
                f"vs {_money(d.reference_price)} ({BASIS_TEXT.get(d.basis, '')})" if d.reference_price else "")
            cmp_ = "; ".join(f"{p.site} {_money(p.price)}" for p in d.comparisons[:4])
            print(f"          {ref}{' · elsewhere: ' + cmp_ if cmp_ else ''} · {d.source}")
    print("\nleft out: " + ", ".join(f"{k} {v}" for k, v in res.excluded.most_common()))


async def _run(args) -> int:
    svc = SlompService()
    try:
        if args.cmd == "local":
            res = await svc.local(args.city, args.industries, args.radius)
            print(json.dumps(res.to_dict(), indent=1) if args.json else "", end="")
            if not args.json:
                print_local(res, args.limit)
        elif args.cmd == "online":
            res = await svc.online(args.industries, args.limit, compare=not args.no_compare)
            print(json.dumps(res.to_dict(), indent=1) if args.json else "", end="")
            if not args.json:
                print_online(res, args.limit)
    except InputError as e:
        print(f"error: {e}" + (f"\n  try: {', '.join(map(str, e.choices[:12]))}" if e.choices else ""), file=sys.stderr)
        return 2
    finally:
        await svc.aclose()
    return 0


PORT_BUSY = """\
Port {port} is already in use, most likely by a `slomp serve` started earlier.
A running server keeps the code it started with, so it has to be stopped to pick up changes:
press Ctrl+C in the terminal where it is running, then run `slomp serve` again.
To run a second copy beside it instead: slomp serve --port {other}
"""


def port_busy(port: int, host: str = "127.0.0.1") -> bool:
    """True when something already listens there, which uvicorn reports as "[Errno 48] address already in use"."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)    # as uvicorn binds, so a just-closed port is free
        try:
            s.bind((host, port))
        except OSError as e:
            return e.errno == errno.EADDRINUSE
    return False


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="slomp", description="Deals near Texas cities, and the biggest online discounts.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("cities", help="find a city id")
    c.add_argument("query", nargs="?", default="")
    sub.add_parser("industries", help="list the industries")
    lo = sub.add_parser("local", help="deals near a city in the next 7 days")
    lo.add_argument("city")
    lo.add_argument("-i", "--industries", required=True)
    lo.add_argument("-r", "--radius", type=float, default=25.0, choices=(10.0, 25.0, 50.0))
    lo.add_argument("-n", "--limit", type=int, default=15)
    lo.add_argument("--json", action="store_true")
    on = sub.add_parser("online", help="biggest verified online discounts")
    on.add_argument("-i", "--industries", required=True)
    on.add_argument("-n", "--limit", type=int, default=15)
    on.add_argument("--json", action="store_true")
    on.add_argument("--no-compare", action="store_true", help="skip other-site price checks (faster)")
    rg = sub.add_parser("regulars", help="the regular deals Slomp knows, with each one's evidence")
    rg.add_argument("--all", action="store_true", help="include the ones known only from deal-site lists")
    ve = sub.add_parser("verify", help="run the live verification harness")
    ve.add_argument("--iteration", type=int, required=True)
    ve.add_argument("--tests", type=int, default=200)
    ve.add_argument("--seed", type=int, default=None)
    ve.add_argument("--plan", choices=("standard", "regulars"), default="standard",
                    help="regulars: the regular-deals tests in the Austin, Houston and Dallas areas")
    ve.add_argument("--key", type=Path, default=None, help="regulars: the answer key for the recall tests")
    se = sub.add_parser("serve", help="run the web page and API")
    se.add_argument("--port", type=int, default=8000)
    si = sub.add_parser("site", help="build the published site (GitHub Pages)")
    si.add_argument("action", choices=("build",))
    si.add_argument("--out", type=Path, default=Path("site"), help="where to write it (replaced)")
    si.add_argument("--anchor-mi", type=float, default=None, help="every city within this distance of an anchor ZIP")
    si.add_argument("--no-online", action="store_true", help="leave out the online deals (faster, for testing)")
    si.add_argument("--prune-cache", action="store_true", help="drop cached responses 3 days past their lifetime")
    args = ap.parse_args(argv)

    if args.cmd == "cities":
        for x in find_cities(args.query, 25):
            print(f"{x.id:28s} {x.name}, TX · {x.county} · pop {x.population or '?'} · ZIP {x.zip}")
        return 0
    if args.cmd == "industries":
        for i in ind.INDUSTRIES:
            print(f"{i.id:8s} {i.name:24s} {i.description}")
        return 0
    if args.cmd == "regulars":
        return asyncio.run(_regulars(args.all))
    if args.cmd == "verify":
        if args.plan == "regulars":
            from .verify.regulars_run import main as regulars_main
            return regulars_main(args.iteration, args.tests, args.seed, args.key)
        from .verify.runner import main as verify_main
        return verify_main(args.iteration, args.tests, args.seed)
    if args.cmd == "site":
        from .site import ANCHOR_MI, build
        asyncio.run(build(args.out.resolve(), anchor_mi=args.anchor_mi or ANCHOR_MI, online=not args.no_online,
                          prune=args.prune_cache, log=lambda m: print(m, flush=True)))
        return 0
    if args.cmd == "serve":
        import uvicorn
        if port_busy(args.port):
            print(PORT_BUSY.format(port=args.port, other=args.port + 1), end="", file=sys.stderr)
            return 1
        uvicorn.run("slomp.api:app", port=args.port)
        return 0
    return asyncio.run(_run(args))


if __name__ == "__main__":
    sys.exit(main())
