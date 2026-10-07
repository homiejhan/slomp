"""HTTP API and the web page.

    uvicorn slomp.api:app --app-dir backend --port 8000

  GET /                     the web page
  GET /api/v1/meta          the fixed lists: Texas cities, industries, radii
  GET /api/v1/local         ?city=austin&industries=tech,sports&radius_mi=25     Output 1
  GET /api/v1/online        ?industries=tech,fashion&limit=25                   Output 2
  GET /api/v1/sales         ?industries=fashion,home                            sales at online stores
  GET /api/v1/search        all three, in one response
  GET /api/v1/top           the home page's biggest deals: chains found all over Texas, big online stores
  GET /api/v1/health        per-source status
"""
from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Query, Request
from fastapi.responses import FileResponse, JSONResponse

from . import industries as ind
from .reference import cities
from .service import RADII, InputError, SlompService

STATIC = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.slomp = SlompService()
    warm = asyncio.create_task(app.state.slomp.warm()) if os.environ.get("SLOMP_WARM", "1") != "0" else None
    yield
    if warm:
        warm.cancel()
    await app.state.slomp.aclose()


app = FastAPI(title="Slomp", version="1.0.0", lifespan=lifespan,
              description="Deals near any Texas city in the next 7 days, the biggest verified online discounts, and "
                          "online stores' sales.")


@app.exception_handler(InputError)
async def input_error(_: Request, exc: InputError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"error": str(exc), "choices": exc.choices})


def svc(request: Request) -> SlompService:
    return request.app.state.slomp


@app.get("/", include_in_schema=False)
async def page() -> FileResponse:
    # "no-cache" makes browsers revalidate, so an updated page shows up on the next load instead of a stale copy.
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/api/v1/meta")
async def meta() -> dict:
    return {
        "cities": [{"id": c.id, "name": c.name, "county": c.county, "population": c.population, "zip": c.zip,
                    "kind": c.kind} for c in cities()],
        "industries": [{"id": i.id, "name": i.name, "description": i.description,
                        "online": i.online} for i in ind.INDUSTRIES],
        "radii_mi": list(RADII),
    }


@app.get("/api/v1/local")
async def local(request: Request, city: str = Query(..., description="city id from /api/v1/meta"),
                industries: str = Query(..., description="comma-separated industry ids"),
                radius_mi: float = Query(25.0)) -> dict:
    res = await svc(request).local(city, industries, radius_mi)
    return res.to_dict()


@app.get("/api/v1/online")
async def online(request: Request, industries: str = Query(...), limit: int = Query(25, ge=1, le=100)) -> dict:
    res = await svc(request).online(industries, limit)
    return res.to_dict()


@app.get("/api/v1/sales")
async def sales(request: Request, industries: str = Query(..., description="comma-separated industry ids")) -> dict:
    return await svc(request).sales(industries)


@app.get("/api/v1/search")
async def search(request: Request, city: str = Query(...), industries: str = Query(...),
                 radius_mi: float = Query(25.0), limit: int = Query(25, ge=1, le=100)) -> dict:
    s = svc(request)
    online_inds = [i for i in ind.parse_ids(industries)[0] if ind.BY_ID[i].online]
    local_task = s.local(city, industries, radius_mi)
    if online_inds:
        loc, onl, sal = await asyncio.gather(local_task, s.online(",".join(online_inds), limit),
                                             s.sales(",".join(online_inds)))
        return {"local": loc.to_dict(), "online": onl.to_dict(), "sales": sal}
    return {"local": (await local_task).to_dict(), "online": None, "sales": None}


@app.get("/api/v1/top")
async def top(request: Request) -> dict:
    """The deals the home page shows before a search: the same anywhere in Texas (slomp/top.py)."""
    return await svc(request).top()


@app.get("/api/v1/health")
async def health(request: Request) -> dict:
    return svc(request).health()
