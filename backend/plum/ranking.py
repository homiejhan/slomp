"""Ordering offers and community deals."""
from __future__ import annotations

import math
from datetime import datetime
from typing import Iterable, Optional

from .models import DealPost, Quote, RetailerPolicy, utcnow


def rank_quotes(quotes: Iterable[Quote], policies: dict[str, RetailerPolicy]) -> list[Quote]:
    """Cheapest net first. Ties: better match, then more trusted store. Commission is never a key."""
    return sorted(quotes, key=lambda q: (q.net, -q.match.score, -policies[q.listing.retailer].trust))


def deal_heat(d: DealPost, now: Optional[datetime] = None) -> float:
    """Votes decay with age (news-ranker gravity) and are boosted by discount depth."""
    hours = max(0.0, ((now or utcnow()) - d.posted).total_seconds() / 3600)
    return d.votes / math.pow(hours + 2, 1.2) * (1 + d.depth)


def rank_deals(deals: Iterable[DealPost], now: Optional[datetime] = None) -> list[DealPost]:
    return sorted(deals, key=lambda d: -deal_heat(d, now))


def is_period_low(current: float, history: list[float], tolerance: float = 0.01) -> bool:
    return bool(history) and current <= min(history) * (1 + tolerance)
