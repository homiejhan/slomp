"""Adapter contract plus the plumbing every adapter needs: rate limits, circuit breaker, timeouts, fan-out."""
from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

from ..models import Listing, Product


class TokenBucket:
    """Per-retailer request budget so we never trip a partner's rate limit."""

    def __init__(self, rate_per_s: float, burst: int):
        self.rate, self.burst = rate_per_s, burst
        self.tokens, self.last = float(burst), time.monotonic()

    async def take(self) -> None:
        while True:
            now = time.monotonic()
            self.tokens = min(self.burst, self.tokens + (now - self.last) * self.rate)
            self.last = now
            if self.tokens >= 1:
                self.tokens -= 1
                return
            await asyncio.sleep((1 - self.tokens) / self.rate)


class CircuitBreaker:
    """Stop hammering a store that keeps failing; try again after cooldown."""

    def __init__(self, failures: int = 3, cooldown_s: float = 30):
        self.max_failures, self.cooldown = failures, cooldown_s
        self.failures, self.opened_at = 0, 0.0

    @property
    def open(self) -> bool:
        if self.failures < self.max_failures:
            return False
        if time.monotonic() - self.opened_at > self.cooldown:
            self.failures = 0
            return False
        return True

    def ok(self) -> None:
        self.failures = 0

    def fail(self) -> None:
        self.failures += 1
        if self.failures >= self.max_failures:
            self.opened_at = time.monotonic()


class Adapter(ABC):
    retailer: str = ""
    rate = TokenBucket(5, 10)
    breaker = CircuitBreaker()

    @abstractmethod
    async def search(self, product: Product) -> list[Listing]:
        """Return raw listings for a product. Prefer GTIN lookups; fall back to title search."""

    async def guarded_search(self, product: Product, timeout_s: float) -> list[Listing]:
        if self.breaker.open:
            raise RuntimeError(f"{self.retailer}: circuit open")
        await self.rate.take()
        try:
            res = await asyncio.wait_for(self.search(product), timeout=timeout_s)
        except Exception:
            self.breaker.fail()
            raise
        self.breaker.ok()
        return res


@dataclass
class AdapterOutcome:
    retailer: str
    status: str                       # done | timeout | error
    listings: list[Listing] = field(default_factory=list)
    ms: int = 0
    error: Optional[str] = None


async def run_adapters(adapters: list[Adapter], product: Product, budget_s: float = 1.4) -> list[AdapterOutcome]:
    """Fan out to every store at once; whoever answers within the budget is in. Partial results beat waiting."""

    async def one(a: Adapter) -> AdapterOutcome:
        t0 = time.monotonic()
        try:
            ls = await a.guarded_search(product, budget_s)
            return AdapterOutcome(a.retailer, "done", ls, int((time.monotonic() - t0) * 1000))
        except asyncio.TimeoutError:
            return AdapterOutcome(a.retailer, "timeout", [], int(budget_s * 1000))
        except Exception as e:  # noqa: BLE001 - one bad store must not sink the request
            return AdapterOutcome(a.retailer, "error", [], int((time.monotonic() - t0) * 1000), str(e))

    return list(await asyncio.gather(*(one(a) for a in adapters)))
