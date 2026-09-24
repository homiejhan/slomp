"""TTL cache with single-flight: concurrent callers for the same key share one fetch."""
from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from typing import Any, Awaitable, Callable, Generic, Hashable, Optional, TypeVar

T = TypeVar("T")


class TTLCache(Generic[T]):
    def __init__(self, ttl_s: float, maxsize: int = 10_000):
        self.ttl = ttl_s
        self.maxsize = maxsize
        self._data: OrderedDict[Hashable, tuple[float, T]] = OrderedDict()
        self._locks: dict[Hashable, asyncio.Lock] = {}

    def get(self, key: Hashable) -> Optional[T]:
        item = self._data.get(key)
        if not item:
            return None
        exp, val = item
        if exp < time.monotonic():
            self._data.pop(key, None)
            return None
        self._data.move_to_end(key)
        return val

    def set(self, key: Hashable, val: T, ttl_s: Optional[float] = None) -> None:
        self._data[key] = (time.monotonic() + (ttl_s or self.ttl), val)
        self._data.move_to_end(key)
        while len(self._data) > self.maxsize:
            self._data.popitem(last=False)

    async def get_or_fetch(self, key: Hashable, fetch: Callable[[], Awaitable[T]], ttl_s: Optional[float] = None) -> T:
        hit = self.get(key)
        if hit is not None:
            return hit
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            hit = self.get(key)
            if hit is not None:
                return hit
            val = await fetch()
            self.set(key, val, ttl_s)
            return val

    def invalidate(self, key: Hashable) -> None:
        self._data.pop(key, None)
