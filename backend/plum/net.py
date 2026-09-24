"""Polite HTTP for public data sources.

Every request identifies Plum, requests to one host are spaced out, transient failures (timeouts, 429, 5xx, an HTML
error page where JSON was expected) are retried with backoff, and JSON responses can be cached on disk. Nominatim and
Overpass both ask clients to cache and to stay near one request per second; Flipp gets the same courtesy.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import random
import time
from pathlib import Path
from typing import Any, Mapping, Optional
from urllib.parse import urlsplit

from . import __version__

try:  # transport is optional so the engine and its tests run without it
    import httpx  # type: ignore
except ImportError:  # pragma: no cover
    httpx = None

RETRY_STATUS = {429, 500, 502, 503, 504}
MISS = object()


def user_agent() -> str:
    """Set PLUM_CONTACT (an email or URL) to include a contact, as Nominatim's usage policy recommends."""
    contact = os.getenv("PLUM_CONTACT", "").strip()
    return f"plum/{__version__} (local deals finder{'; ' + contact if contact else ''})"


class HttpError(RuntimeError):
    """A source failed: bad status, a body that isn't JSON, or no answer after retries."""

    def __init__(self, message: str, retry_after: Optional[float] = None):
        super().__init__(message)
        self.retry_after = retry_after


class DiskCache:
    """One JSON file per response, with an expiry. Safe to delete at any time."""

    def __init__(self, root: Optional[os.PathLike | str] = None):
        self.root = Path(root or os.getenv("PLUM_CACHE_DIR") or Path.home() / ".cache" / "plum")

    def _path(self, key: str) -> Path:
        return self.root / key[:2] / f"{key}.json"

    def get(self, key: str) -> Any:
        try:
            with open(self._path(key), encoding="utf-8") as fh:
                entry = json.load(fh)
        except (OSError, ValueError):
            return MISS
        return entry.get("data") if entry.get("expires", 0) > time.time() else MISS

    def set(self, key: str, data: Any, ttl_s: float) -> None:
        path = self._path(key)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(f".{os.getpid()}.tmp")
            tmp.write_text(json.dumps({"expires": time.time() + ttl_s, "data": data}), encoding="utf-8")
            os.replace(tmp, path)
        except OSError:
            pass  # a cache that can't write is just a slower cache


def _cache_key(method: str, url: str, params: Optional[Mapping[str, Any]], data: Optional[Mapping[str, Any]]) -> str:
    raw = json.dumps([method, url, sorted((params or {}).items()), sorted((data or {}).items())], default=str)
    return hashlib.sha1(raw.encode()).hexdigest()


def _retry_after(headers: Mapping[str, str]) -> Optional[float]:
    try:
        return float(headers.get("retry-after", ""))
    except ValueError:
        return None


class HttpClient:
    def __init__(self, *, cache: Optional[DiskCache] = None, min_interval_s: Optional[Mapping[str, float]] = None,
                 timeout_s: float = 30.0, retries: int = 3, backoff_s: float = 1.0, transport: Any = None):
        if httpx is None:
            raise RuntimeError("httpx is not installed; pip install 'plum[live]'")
        self.cache = cache
        self.min_interval = dict(min_interval_s or {})    # host -> seconds between request starts
        self.retries = retries
        self.backoff_s = backoff_s
        self.requests = 0                                 # network requests made (cache hits don't count)
        self._client = httpx.AsyncClient(timeout=timeout_s, transport=transport, follow_redirects=True,
                                         headers={"User-Agent": user_agent(), "Accept": "application/json"})
        self._host_locks: dict[str, asyncio.Lock] = {}
        self._host_next: dict[str, float] = {}

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "HttpClient":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def get_json(self, url: str, params: Optional[Mapping[str, Any]] = None, *,
                       headers: Optional[Mapping[str, str]] = None, ttl_s: Optional[float] = None) -> Any:
        return await self._json("GET", url, params=params, headers=headers, ttl_s=ttl_s)

    async def post_json(self, url: str, data: Mapping[str, Any], *, ttl_s: Optional[float] = None,
                        timeout_s: Optional[float] = None, retries: Optional[int] = None) -> Any:
        """Form-encoded POST (what Overpass expects)."""
        return await self._json("POST", url, data=data, ttl_s=ttl_s, timeout_s=timeout_s, retries=retries)

    async def _json(self, method: str, url: str, *, params: Optional[Mapping[str, Any]] = None,
                    data: Optional[Mapping[str, Any]] = None, headers: Optional[Mapping[str, str]] = None,
                    ttl_s: Optional[float] = None, timeout_s: Optional[float] = None,
                    retries: Optional[int] = None) -> Any:
        key = _cache_key(method, url, params, data)
        if self.cache and ttl_s:
            hit = self.cache.get(key)
            if hit is not MISS:
                return hit
        host = urlsplit(url).netloc
        last: Optional[HttpError] = None
        for attempt in range(self.retries if retries is None else retries):
            if attempt:
                await asyncio.sleep(self._backoff(attempt, last))
            await self._pace(host)
            self.requests += 1
            try:
                r = await self._client.request(method, url, params=params, data=data, headers=headers,
                                               **({"timeout": timeout_s} if timeout_s else {}))
            except httpx.HTTPError as e:  # timeouts, resets, DNS
                last = HttpError(f"{host}: {type(e).__name__}")
                continue
            if r.status_code in RETRY_STATUS:
                last = HttpError(f"{host} answered {r.status_code}", _retry_after(r.headers))
                continue
            if r.status_code >= 400:
                raise HttpError(f"{host} answered {r.status_code} for {r.request.url.path}")
            try:
                body = r.json()
            except ValueError:  # e.g. Overpass's HTML "too busy" page
                last = HttpError(f"{host} sent a non-JSON response")
                continue
            if self.cache and ttl_s:
                self.cache.set(key, body, ttl_s)
            return body
        raise last or HttpError(f"{host}: no response")

    def _backoff(self, attempt: int, err: Optional[HttpError]) -> float:
        if err is not None and err.retry_after is not None:
            return min(err.retry_after, 30.0)
        return self.backoff_s * 2 ** (attempt - 1) * (0.75 + random.random() / 2)

    async def _pace(self, host: str) -> None:
        gap = self.min_interval.get(host, 0.0)
        if gap <= 0:
            return
        async with self._host_locks.setdefault(host, asyncio.Lock()):
            wait = self._host_next.get(host, 0.0) - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            self._host_next[host] = time.monotonic() + gap
