"""FastAPI surface. `pip install 'plum[api]'` then `uvicorn plum.api:app --reload`.

  /local/deals?where=Austin,TX       live weekly-ad deals near a city or ZIP
  /local/search?q=eggs&where=78701   one item across nearby stores' ads
  /search, /probe, /coupons, /deals  the product engine (the default app runs it on simulated demo data)
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from dataclasses import asdict
from typing import Any, AsyncIterator, Optional

from . import __version__
from .coupons import reliability
from .local import LocalDealService
from .net import HttpError
from .ranking import deal_heat, rank_deals
from .render import jsonable
from .service import DealService

try:
    from fastapi import FastAPI, HTTPException, Query
    from fastapi.middleware.cors import CORSMiddleware
except ImportError as e:  # pragma: no cover
    raise ImportError("the API needs FastAPI: pip install 'plum[api]'") from e


def _quote(q: Any) -> dict:
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


def create_app(service: DealService, local: Optional[LocalDealService] = None) -> FastAPI:
    state: dict[str, Optional[LocalDealService]] = {"local": local}

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        if local is None and state["local"] is not None:     # only close what this app opened
            await state["local"].aclose()

    def live() -> LocalDealService:
        if state["local"] is None:
            state["local"] = LocalDealService.live()
        return state["local"]

    app = FastAPI(title="Plum", version=__version__, lifespan=lifespan)
    origins = [o.strip() for o in os.getenv("PLUM_CORS_ORIGINS", "*").split(",") if o.strip()]
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET", "POST"], allow_headers=["*"])

    @app.get("/health")
    async def health():
        return {"ok": True, "version": __version__, "stores": [a.retailer for a in service.adapters]}

    @app.get("/local/deals")
    async def local_deals(where: str, radius_mi: float = Query(25.0, gt=0, le=100), limit: int = Query(25, ge=1, le=100),
                          promos: int = Query(10, ge=0, le=100), per_store: int = Query(3, ge=1, le=100),
                          store: list[str] = Query(default=[]), category: str = "", confirmed_only: bool = False):
        try:
            rep = await live().deals(where, radius_mi=radius_mi, limit=limit, promo_limit=promos, per_store=per_store,
                                     merchants=store, category=category, confirmed_only=confirmed_only)
        except LookupError as e:
            raise HTTPException(404, str(e))
        except HttpError as e:
            raise HTTPException(502, str(e))
        return jsonable(rep)

    @app.get("/local/search")
    async def local_search(q: str, where: str, radius_mi: float = Query(25.0, gt=0, le=100),
                           limit: int = Query(20, ge=1, le=100), confirmed_only: bool = False):
        try:
            rep = await live().search(q, where, radius_mi=radius_mi, limit=limit, confirmed_only=confirmed_only)
        except LookupError as e:
            raise HTTPException(404, str(e))
        except HttpError as e:
            raise HTTPException(502, str(e))
        return jsonable(rep)

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
            "adapters": [{"retailer": a.retailer, "status": a.status, "ms": a.ms, "count": len(a.listings),
                          "error": a.error} for a in rep.adapters],
            "offers": [dict(_quote(x), lowest_90d=rep.is_low(x)) for x in rep.offers],
            "skipped": [{"id": s.listing.id, "title": s.listing.title, "retailer": s.listing.retailer,
                         "price": s.listing.price, "condition": s.listing.condition.value, "why": s.why}
                        for s in rep.skipped],
        }

    @app.post("/probe/{listing_id}")
    async def probe(listing_id: str, product_id: str):
        product, listing = await service.listing(product_id, listing_id)
        if product is None:
            raise HTTPException(404, "unknown product")
        if listing is None:
            raise HTTPException(404, "listing not in current results")
        return asdict(await service.test_codes(listing, product))

    @app.get("/coupons/{retailer}")
    async def coupons(retailer: str):
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
