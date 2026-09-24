"""python demo.py "sony xm5"   — runs the full pipeline on simulated adapters and prints the receipt."""
from __future__ import annotations

import asyncio
import sys

from plum.demo_data import POLICIES, build_service


async def main(q: str) -> None:
    svc = build_service()
    rep = await svc.find(q)
    if rep.product is None:
        print(f"No product matched ({rep.how})")
        return
    print(f"\n{rep.product.title}   (found by {rep.how})")
    print("stores:", ", ".join(f"{a.retailer}:{a.status}/{len(a.listings)}" for a in rep.adapters))
    for i, o in enumerate(rep.offers):
        tag = "BEST" if i == 0 else "    "
        code = f"code {o.best_coupon.coupon.code} −${o.code_discount:.2f} ({o.best_coupon.reliability:.0%} works)" if o.best_coupon and o.code_discount else "no code"
        print(f"{tag} {POLICIES[o.listing.retailer].name:<10} sticker ${o.listing.price:>7.2f}  {code:<40} ship ${o.shipping:>5.2f}  pay ${o.pay_today:>7.2f}  net ${o.net:>7.2f}  [{o.match.tier.value}]")
    for s in rep.skipped:
        print(f"skip {s.listing.retailer:<10} ${s.listing.price:>7.2f}  {s.listing.title[:60]:<60} -> {s.why}")
    if rep.best:
        res = await svc.test_codes(rep.best.listing, rep.product)
        print("\nprobe:", ", ".join(f"{s.code}:{'ok −$%.2f' % s.discount if s.ok else s.why}" for s in res.steps), "| winner:", res.winner)
        rep2 = await svc.find(q)
        print(f"after probe: pay ${rep2.best.pay_today:.2f} at {POLICIES[rep2.best.listing.retailer].name} (verified={rep2.best.verified})")


if __name__ == "__main__":
    asyncio.run(main(" ".join(sys.argv[1:]) or "sony xm5"))
