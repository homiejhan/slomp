"""HTTP API and the web page.

    uvicorn slomp.api:app --app-dir backend --port 8000

  GET /                     the web page
  GET /api/v1/meta          the fixed lists: Texas cities, industries, radii
  GET /api/v1/local         ?city=austin&industries=tech,sports&radius_mi=25     Output 1
  GET /api/v1/online        ?industries=tech,fashion&limit=25                   Output 2
  GET /api/v1/sales         ?industries=fashion,home                            sales at online stores
  GET /api/v1/search        all three, in one response
                            &q=lego+star+wars on any of the four: only the deals that say every word (slomp/search.py);
                            with q, industries may be left out and every industry is searched
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
from . import search as keywords
from .reference import cities
from .service import ONLINE_MAX, RADII, InputError, SlompService, searched

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
                        "online": i.online, "sales": i.sales} for i in ind.INDUSTRIES],
        "radii_mi": list(RADII),
    }


INDUSTRIES = Query("", description="comma-separated industry ids; with q they may be left out, and every industry is searched")
KEYWORDS = Query("", description="keywords: only the deals that say every word (\"lego star wars\")")


def _asked(payload: dict, q: str) -> dict:
    """An answer with how its keywords were read, when it had any."""
    return {**payload, "query": keywords.query(q)} if keywords.words(q) else payload


@app.get("/api/v1/local")
async def local(request: Request, city: str = Query(..., description="city id from /api/v1/meta"),
                industries: str = INDUSTRIES, radius_mi: float = Query(25.0), q: str = KEYWORDS) -> dict:
    industries, asked = searched(industries, q)
    res = await svc(request).local(city, industries, radius_mi)
    return _asked(keywords.local(res.to_dict(), asked), q)


@app.get("/api/v1/online")
async def online(request: Request, industries: str = INDUSTRIES, limit: int = Query(25, ge=1, le=100),
                 q: str = KEYWORDS) -> dict:
    industries, asked = searched(industries, q)
    if asked and not ind.parse_ids(industries)[1]:            # every industry: the ones that have online deals
        industries = [i for i in ind.parse_ids(industries)[0] if ind.BY_ID[i].online] or industries
    res = await svc(request).online(industries, ONLINE_MAX if asked else limit)
    return _asked(keywords.online(res.to_dict(), asked, limit), q)


@app.get("/api/v1/sales")
async def sales(request: Request, industries: str = INDUSTRIES, q: str = KEYWORDS) -> dict:
    industries, asked = searched(industries, q)
    return _asked(keywords.sales(await svc(request).sales(industries), asked), q)


@app.get("/api/v1/search")
async def search(request: Request, city: str = Query(...), industries: str = INDUSTRIES,
                 radius_mi: float = Query(25.0), limit: int = Query(25, ge=1, le=100), q: str = KEYWORDS) -> dict:
    return await svc(request).search(city, industries, radius_mi, limit, q)


@app.get("/api/v1/top")
async def top(request: Request) -> dict:
    """The deals the home page shows before a search: the same anywhere in Texas (slomp/top.py)."""
    return await svc(request).top()


@app.get("/api/v1/health")
async def health(request: Request) -> dict:
    return svc(request).health()
