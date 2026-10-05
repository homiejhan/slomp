"""Settings, rate limits and cache lifetimes. Environment variables override the defaults:

  PLUM_CACHE_DIR   where the SQLite cache lives (default ~/.cache/plum)
  PLUM_CONTACT     a URL or email appended to the User-Agent, as some API usage policies ask (default: none)
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

HOUR = 3600
DAY = 24 * HOUR

# Requests per second per host. Sources, not compute, are the bottleneck, so these are the system's real limits.
RATE_LIMITS: dict[str, float] = {
    "backflipp.wishabi.com": 4.0,
    "overpass-api.de": 0.5,
    "overpass.kumi.systems": 0.5,
    "www.dealnews.com": 1.0,
    "slickdeals.net": 1.0,
    "www.amazon.com": 0.5,
    "www.newegg.com": 1.0,
}
DEFAULT_RATE = 1.0
# Simultaneous requests per host.
CONCURRENCY: dict[str, int] = {"backflipp.wishabi.com": 4, "overpass-api.de": 1, "overpass.kumi.systems": 1}
DEFAULT_CONCURRENCY = 2

TTL = {
    "flyers": 6 * HOUR,
    "flyer_items": DAY,
    "merchant_search": DAY,
    "item": DAY,
    "flipp_search": 6 * HOUR,
    "stores": 30 * DAY,
    "feed": 30 * 60,
    "prices": 6 * HOUR,
    "robots": DAY,
    "page": HOUR,
    "error": 120,
}


def _contact() -> str:
    return os.environ.get("PLUM_CONTACT", "").strip()


@dataclass(frozen=True)
class Settings:
    cache_dir: Path = field(default_factory=lambda: Path(os.environ.get("PLUM_CACHE_DIR",
                                                                         Path.home() / ".cache" / "plum")))
    contact: str = field(default_factory=_contact)
    radius_mi: float = 25.0
    window_days: int = 7
    request_timeout_s: float = 20.0
    deadline_s: float = 60.0           # a request plus its retries never takes longer than this
    retries: int = 3
    breaker_threshold: int = 5         # consecutive failures before a host's circuit opens
    breaker_cooldown_s: float = 60.0
    offline: bool = False              # serve only from cache (tests, demos)

    @property
    def user_agent(self) -> str:
        return f"Mozilla/5.0 (compatible; Plum/1.0{'; +' + self.contact if self.contact else ''})"

    @property
    def db_path(self) -> Path:
        return self.cache_dir / "plum.db"
