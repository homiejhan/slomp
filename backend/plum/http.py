"""PoliteClient: every network call Plum makes goes through here.

  * per-host rate limit and concurrency cap, so no source is hit harder than its limit in config.RATE_LIMITS
  * retries with exponential backoff and jitter on timeouts, 429 and 5xx, honoring Retry-After
  * a circuit breaker per host (one broken source can't slow the rest, and can't trip the others' breakers)
  * a hard deadline per request, retries included
  * robots.txt honored for HTML pages; an honest User-Agent; bot walls detected and never worked around
  * a SQLite response cache with per-source lifetimes, and stale-if-error when a source is down
"""
from __future__ import annotations

import asyncio
import json
import random
import re
import time
import urllib.robotparser
from dataclasses import dataclass
from typing import Any, Optional
from urllib.parse import urlencode, urlsplit

import httpx

from .config import CONCURRENCY, DEFAULT_CONCURRENCY, DEFAULT_RATE, RATE_LIMITS, TTL, Settings
from .db import CachedResponse, Store

# Pages that are a challenge or a block, not content. Checked only on HTML, and only near the top of the page.
_WALL = re.compile(r"captcha-delivery|px-captcha|perimeterx|robot or human|verify you are human|cf-chl-|"
                   r"challenge-platform|<title>just a moment|<title>access denied|unusual traffic|"
                   r"api-services-support@amazon\.com|/errors/validateCaptcha", re.I)


class FetchError(Exception):
    """The source could not be read. `reason` is short and user-facing."""

    def __init__(self, url: str, reason: str, status: int = 0):
        super().__init__(f"{reason}: {url}")
        self.url, self.reason, self.status = url, reason, status


class Disallowed(FetchError):
    pass


class Blocked(FetchError):
    pass


@dataclass
class Response:
    url: str
    final_url: str
    status: int
    content_type: str
    body: bytes
    fetched_at: float
    from_cache: bool = False
    stale: bool = False

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")

    def json(self) -> Any:
        return json.loads(self.body)


class _Host:
    def __init__(self, rate: float, concurrency: int):
        self.interval = 1.0 / rate if rate > 0 else 0.0
        self.sem = asyncio.Semaphore(concurrency)
        self.lock = asyncio.Lock()
        self.next_at = 0.0
        self.failures = 0
        self.open_until = 0.0

    async def wait_turn(self) -> None:
        async with self.lock:
            now = time.monotonic()
            delay = self.next_at - now
            self.next_at = max(now, self.next_at) + self.interval
        if delay > 0:
            await asyncio.sleep(delay)


def cache_key(url: str, params: Optional[dict] = None) -> str:
    if params:
        url = f"{url}{'&' if '?' in url else '?'}{urlencode(sorted((k, str(v)) for k, v in params.items()))}"
    return url


class PoliteClient:
    def __init__(self, store: Store, settings: Optional[Settings] = None):
        self.settings = settings or Settings()
        self.store = store
        self._hosts: dict[str, _Host] = {}
        self._robots: dict[str, Optional[urllib.robotparser.RobotFileParser]] = {}
        self._client: Optional[httpx.AsyncClient] = None
        self.stats: dict[str, dict[str, int]] = {}

    async def __aenter__(self) -> "PoliteClient":
        return self

    async def __aexit__(self, *exc) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            s = self.settings
            self._client = httpx.AsyncClient(
                follow_redirects=True, timeout=httpx.Timeout(s.request_timeout_s, connect=10.0),
                headers={"User-Agent": s.user_agent, "Accept-Language": "en-US,en;q=0.9"},
                limits=httpx.Limits(max_connections=32, max_keepalive_connections=16))
        return self._client

    def _host(self, host: str) -> _Host:
        if host not in self._hosts:
            self._hosts[host] = _Host(RATE_LIMITS.get(host, DEFAULT_RATE), CONCURRENCY.get(host, DEFAULT_CONCURRENCY))
        return self._hosts[host]

    def _count(self, host: str, what: str) -> None:
        self.stats.setdefault(host, {}).setdefault(what, 0)
        self.stats[host][what] += 1

    def health(self) -> dict[str, dict]:
        now = time.monotonic()
        return {h: {**self.stats.get(h, {}), "circuit_open": st.open_until > now, "consecutive_failures": st.failures}
                for h, st in self._hosts.items()}

    async def allowed(self, url: str) -> bool:
        """robots.txt check for our User-Agent token. An unreadable robots.txt means no restrictions (RFC 9309)."""
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._robots:
            parser: Optional[urllib.robotparser.RobotFileParser] = None
            try:
                r = await self.get(origin + "/robots.txt", ttl_s=TTL["robots"], robots=False)
                if r.status == 200:
                    parser = urllib.robotparser.RobotFileParser()
                    parser.parse(r.text.splitlines())
            except FetchError:
                parser = None
            self._robots[origin] = parser
        parser = self._robots[origin]
        return parser is None or parser.can_fetch("Plum", url)

    async def get(self, url: str, params: Optional[dict] = None, *, ttl_s: float, html: bool = False,
                  robots: Optional[bool] = None, headers: Optional[dict] = None, use_cache: bool = True,
                  timeout_s: Optional[float] = None) -> Response:
        """GET with cache. `html=True` marks a web page: robots.txt is checked and bot walls are detected.
        `timeout_s` overrides the per-attempt timeout for sources that are slow by design (Overpass)."""
        key = cache_key(url, params)
        cached = self.store.cache_get(key) if use_cache else None
        if cached and (cached.fresh or self.settings.offline):
            return self._from_cache(cached)
        if self.settings.offline:
            raise FetchError(key, "not cached (offline mode)")
        if (html if robots is None else robots) and not await self.allowed(key):
            raise Disallowed(key, "disallowed by robots.txt")
        try:
            resp = await self._fetch(url, params, headers, html, timeout_s or self.settings.request_timeout_s)
        except FetchError as e:
            return self._stale_or_raise(cached, e)
        ok = 200 <= resp.status < 300
        self.store.cache_put(key, CachedResponse(key, resp.status, resp.content_type, resp.final_url, resp.body,
                                                 resp.fetched_at, resp.fetched_at + (ttl_s if ok else TTL["error"])))
        return resp

    def _from_cache(self, c: CachedResponse, stale: bool = False) -> Response:
        return Response(c.url, c.final_url, c.status, c.content_type or "", c.body or b"", c.fetched_at, True, stale)

    def _stale_or_raise(self, cached: Optional[CachedResponse], err: FetchError) -> Response:
        if cached and 200 <= cached.status < 300:
            return self._from_cache(cached, stale=True)
        raise err

    async def _fetch(self, url: str, params: Optional[dict], headers: Optional[dict], html: bool,
                     timeout_s: float) -> Response:
        """One request with retries. The deadline is enforced here, between attempts, rather than by cancelling the
        request from outside (cancelling httpx's anyio streams from asyncio.wait_for leaks CancelledError)."""
        host = urlsplit(url).netloc
        st = self._host(host)
        if st.open_until > time.monotonic():
            raise FetchError(url, f"{host} is failing; paused for a minute")
        deadline = time.monotonic() + max(self.settings.deadline_s, timeout_s * 1.5)
        attempt = 0
        while True:
            attempt += 1
            remaining = deadline - time.monotonic()
            if remaining < 1:
                self._fail(st)
                raise FetchError(url, f"no answer within {max(self.settings.deadline_s, timeout_s * 1.5):.0f}s")
            await st.wait_turn()
            async with st.sem:
                try:
                    r = await self._http().get(url, params=params, headers=headers,
                                               timeout=httpx.Timeout(min(timeout_s, remaining), connect=10.0))
                    self._count(host, "requests")
                except (httpx.TimeoutException, httpx.TransportError) as e:
                    self._count(host, "errors")
                    if attempt > self.settings.retries:
                        self._fail(st)
                        raise FetchError(url, f"network error ({type(e).__name__})")
                    await asyncio.sleep(min(self._backoff(attempt), max(0.0, deadline - time.monotonic())))
                    continue
            body = r.content
            ctype = r.headers.get("content-type", "")
            if r.status_code == 429 or r.status_code >= 500:
                self._count(host, f"http_{r.status_code}")
                if attempt > self.settings.retries:
                    self._fail(st)
                    raise FetchError(url, f"HTTP {r.status_code}", r.status_code)
                await asyncio.sleep(self._backoff(attempt, r.headers.get("retry-after")))
                continue
            if html and (r.status_code in (403, 503) or _WALL.search(body[:60000].decode("utf-8", "replace"))):
                self._count(host, "blocked")
                raise Blocked(url, "the site served a bot check instead of the page", r.status_code)
            st.failures = 0
            return Response(url if not params else cache_key(url, params), str(r.url), r.status_code, ctype, body,
                            time.time())

    def _fail(self, st: _Host) -> None:
        st.failures += 1
        if st.failures >= self.settings.breaker_threshold:
            st.open_until = time.monotonic() + self.settings.breaker_cooldown_s
            st.failures = 0

    @staticmethod
    def _backoff(attempt: int, retry_after: Optional[str] = None) -> float:
        if retry_after:
            try:
                return min(30.0, float(retry_after))
            except ValueError:
                pass
        return min(30.0, 2 ** (attempt - 1)) + random.uniform(0, 0.5)


async def follow(client: "PoliteClient", url: str, hops: int = 4, ttl_s: float = 6 * 3600) -> Optional[str]:
    """Where a deal site's "buy" link ends up: HTTP redirects plus the `location.replace(...)` script some sites use.
    Each hop must be allowed by robots.txt. Returns the final URL (the store's page may itself block us; its address
    is what matters), or None."""
    for _ in range(hops):
        try:
            if not await client.allowed(url):
                return None
            r = await client.get(url, ttl_s=ttl_s)
        except FetchError:
            return None
        nxt = re.search(r"location\.(?:replace|href)\s*\(?\s*=?\s*['\"](https?://[^'\"]+)", r.text[:3000]) \
            if r.status == 200 and len(r.body) < 5000 else None
        if not nxt:
            return r.final_url
        url = nxt.group(1)
    return url
