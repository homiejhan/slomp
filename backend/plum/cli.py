"""Command line.

    plum cities [QUERY]                                    find a city id
    plum industries                                        the fixed industry list
    plum local CITY -i tech,sports [-r 25] [--json]        Output 1: deals near CITY in the next 7 days
    plum online -i tech,fashion [-n 15] [--json]           Output 2: biggest verified online discounts
    plum verify --iteration N [--tests 200] [--seed S]     the live verification harness
    plum serve [--port 8000]                               the web page and API
"""
from __future__ import annotations

import argparse
import asyncio
import errno
import json
import socket
import sys

from . import industries as ind
from .models import BASIS_TEXT
from .reference import find_cities
from .service import InputError, PlumService


def _money(v) -> str:
    return f"${v:,.2f}" if isinstance(v, (int, float)) else "—"


def print_local(res, limit: int) -> None:
    c = res.city
    print(f"\n{c.name}, TX (ZIP {c.zip}) · {', '.join(ind.BY_ID[i].name for i in res.industries)} · within "
          f"{res.radius_mi:g} mi · {res.window_start:%a %b %-d} to {res.window_end:%a %b %-d}")
    print(f"{len(res.deals)} deals, {len(res.promotions)} promotions, {len(res.unconfirmed)} with unconfirmed stores\n")
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
    print("left out: " + ", ".join(f"{k} {v}" for k, v in res.excluded.most_common()))


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
    svc = PlumService()
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
Port {port} is already in use, most likely by a `plum serve` started earlier.
A running server keeps the code it started with, so it has to be stopped to pick up changes:
press Ctrl+C in the terminal where it is running, then run `plum serve` again.
To run a second copy beside it instead: plum serve --port {other}
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
    ap = argparse.ArgumentParser(prog="plum", description="Deals near Texas cities, and the biggest online discounts.")
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
    ve = sub.add_parser("verify", help="run the live verification harness")
    ve.add_argument("--iteration", type=int, required=True)
    ve.add_argument("--tests", type=int, default=200)
    ve.add_argument("--seed", type=int, default=None)
    se = sub.add_parser("serve", help="run the web page and API")
    se.add_argument("--port", type=int, default=8000)
    args = ap.parse_args(argv)

    if args.cmd == "cities":
        for x in find_cities(args.query, 25):
            print(f"{x.id:28s} {x.name}, TX · {x.county} · pop {x.population or '?'} · ZIP {x.zip}")
        return 0
    if args.cmd == "industries":
        for i in ind.INDUSTRIES:
            print(f"{i.id:8s} {i.name:24s} {i.description}")
        return 0
    if args.cmd == "verify":
        from .verify.runner import main as verify_main
        return verify_main(args.iteration, args.tests, args.seed)
    if args.cmd == "serve":
        import uvicorn
        if port_busy(args.port):
            print(PORT_BUSY.format(port=args.port, other=args.port + 1), end="", file=sys.stderr)
            return 1
        uvicorn.run("plum.api:app", port=args.port)
        return 0
    return asyncio.run(_run(args))


if __name__ == "__main__":
    sys.exit(main())
