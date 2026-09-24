"""TTL cache with single-flight: concurrent callers for the same key share one fetch."""
from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from typing import Any, Awaitable, Callable, Generic, Hashable, Optional, TypeVar

T = TypeVar("T")
_MISSING: Any = object()


class TTLCache(Generic[T]):
    def __init__(self, ttl_s: float, maxsize: int = 10_000):
        self.ttl = ttl_s
        self.maxsize = maxsize
        self._data: OrderedDict[Hashable, tuple[float, T]] = OrderedDict()
        self._locks: dict[Hashable, asyncio.Lock] = {}

    def _lookup(self, key: Hashable) -> Any:
        item = self._data.get(key)
        if item is None:
            return _MISSING
        exp, val = item
        if exp < time.monotonic():
            self._data.pop(key, None)
            return _MISSING
        self._data.move_to_end(key)
        return val

    def get(self, key: Hashable) -> Optional[T]:
        hit = self._lookup(key)
        return None if hit is _MISSING else hit

    def set(self, key: Hashable, val: T, ttl_s: Optional[float] = None) -> None:
        self._data[key] = (time.monotonic() + (self.ttl if ttl_s is None else ttl_s), val)
        self._data.move_to_end(key)
        while len(self._data) > self.maxsize:
            self._data.popitem(last=False)

    async def get_or_fetch(self, key: Hashable, fetch: Callable[[], Awaitable[T]], ttl_s: Optional[float] = None) -> T:
        hit = self._lookup(key)            # a cached None is still a hit
        if hit is not _MISSING:
            return hit
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            hit = self._lookup(key)
            if hit is not _MISSING:
                return hit
            try:
                val = await fetch()
                self.set(key, val, ttl_s)
                return val
            finally:
                # Waiters already hold this lock object and will find the value; later callers make a fresh lock.
                self._locks.pop(key, None)

    def invalidate(self, key: Hashable) -> None:
        self._data.pop(key, None)
