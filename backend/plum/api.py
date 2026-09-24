"""FastAPI surface. `pip install 'plum[api]'` then `uvicorn plum.api:app --reload`.

The frontend (PlumApp.jsx) talks to this when `window.PLUM_API` is set; otherwise it simulates adapters locally.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Optional

from .ranking import deal_heat, rank_deals
from .service import DealService

try:
    from fastapi import FastAPI, HTTPException
    from fastapi.middleware.cors import CORSMiddleware
except Exception as e:  # noqa: BLE001
    raise SystemExit("pip install 'plum[api]' to run the API") from e


def _quote(q):
    return {
        "listing": asdict(q.listing), "match": asdict(q.match),
        "shipping": q.shipping, "ship_cost": q.ship_cost,
        "code": q.best_coupon.coupon.code if q.best_coupon else None, "code_discount": q.code_discount,
        "code_reliability": q.best_coupon.reliability if q.best_coupon else None,
        "pay_today": q.pay_today, "cashback": q.cashback, "net": q.net, "verified": q.verified,
        "codes": [{"code": e.coupon.code, "type": e.coupon.type.value, "applicable": e.applicable, "why": e.why,
                   "reliability": round(e.reliability, 3), "discount": e.discount, "expected": e.expected,
                   "note": e.coupon.note, "source": e.coupon.source} for e in q.coupon_evals],
    }


def create_app(service: DealService) -> FastAPI:
    app = FastAPI(title="Plum", version="0.1.0")
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

    @app.get("/health")
    async def health():
        return {"ok": True, "stores": [a.retailer for a in service.adapters]}

    @app.get("/retailers")
    async def retailers():
        return {r: asdict(p) for r, p in service.policies.items()}

    @app.get("/search")
    async def search(q: str = "", include_used: bool = False, product_id: Optional[str] = None):
        rep = await service.find(q, include_used, product_id=product_id)
        if rep.product is None:
            raise HTTPException(404, {"how": rep.how, "message": "no product matched"})
        return {
            "product": asdict(rep.product), "how": rep.how,
            "adapters": [{"retailer": a.retailer, "status": a.status, "ms": a.ms, "count": len(a.listings), "error": a.error} for a in rep.adapters],
            "offers": [dict(_quote(x), lowest_90d=rep.is_low(x)) for x in rep.offers],
            "skipped": [{"id": s.listing.id, "title": s.listing.title, "retailer": s.listing.retailer, "price": s.listing.price,
                         "condition": s.listing.condition.value, "why": s.why} for s in rep.skipped],
        }

    @app.post("/probe/{listing_id}")
    async def probe(listing_id: str, product_id: str):
        product = service.index.products.get(product_id)
        if product is None:
            raise HTTPException(404, "unknown product")
        outcomes = await service._fetch(product)
        listing = next((l for o in outcomes for l in o.listings if l.id == listing_id), None)
        if listing is None:
            raise HTTPException(404, "listing not in current results")
        res = await service.test_codes(listing, product)
        return asdict(res)

    @app.get("/coupons/{retailer}")
    async def coupons(retailer: str):
        from .coupons import reliability
        return [dict(asdict(c), type=c.type.value, scope=c.scope.value, reliability=round(reliability(c), 3))
                for c in service.coupons if c.retailer == retailer]

    @app.get("/deals")
    async def deals():
        products = service.index.products
        return {
            "events": [asdict(e) for e in service.events],
            "deals": [dict(asdict(d), product_title=products[d.product_id].title if d.product_id in products else d.product_id,
                           glyph=products[d.product_id].glyph if d.product_id in products else "", heat=round(deal_heat(d), 4))
                      for d in rank_deals(service.deals)],
        }

    return app


def _default_app() -> FastAPI:
    from .demo_data import build_service
    return create_app(build_service())


app = _default_app()
