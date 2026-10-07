"""Online stores that ship anywhere in Texas (data/online_stores.json), and finding them by name.

The Sales and Stores tabs (sales.py) and the Online tab's product deals (online.py) name stores the same way through
this registry. docs/DESIGN-online-stores.md has the design.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from typing import Optional

from .models import OnlineStore
from .reference import DATA, norm
from .terms import clean


@lru_cache(maxsize=1)
def registry() -> tuple[OnlineStore, ...]:
    rows = json.loads((DATA / "online_stores.json").read_text(encoding="utf-8"))["stores"]
    return tuple(OnlineStore(key=r["key"], name=r["name"], aliases=tuple(r.get("aliases", [])),
                             domains=tuple(r.get("domains", [])), dealnews=r.get("dealnews", ""),
                             sells=tuple(r.get("sells", [])), site=r.get("site", ""), brand=bool(r.get("brand")),
                             events=tuple(r.get("events", []))) for r in rows)


@lru_cache(maxsize=1)
def by_key() -> dict[str, OnlineStore]:
    return {s.key: s for s in registry()}


def _straight(text: str) -> str:
    return (text or "").replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')


@lru_cache(maxsize=1)
def _names() -> dict[str, OnlineStore]:
    """Every spelling, compared without case, spaces or punctuation."""
    out: dict[str, OnlineStore] = {}
    for s in registry():
        for n in s.names:
            out.setdefault(norm(_straight(n)), s)
    return out


@lru_cache(maxsize=1)
def _patterns() -> list[tuple[re.Pattern, OnlineStore, bool]]:
    """(pattern, store, is an event) for finding a store named in text: longest first, as whole words, as written,
    in capitals, or with a capital first letter (so "Target" is the store and "target" is not)."""
    out = []
    for s in registry():
        for n, event in [(n, False) for n in s.names] + [(e, True) for e in s.events]:
            n = _straight(n)
            if len(norm(n)) < 2:
                continue
            forms = {n, n.upper(), n[:1].upper() + n[1:]}
            body = "|".join(re.escape(f) for f in sorted(forms, key=len, reverse=True))
            out.append((re.compile(r"(?<![\w&'.-])(?:" + body + r")(?:'s)?(?![\w&-])"), s, event))
    out.sort(key=lambda x: -len(x[0].pattern))
    return out


def store_named(name: str) -> Optional[OnlineStore]:
    """The registry store a name or a domain stands for: an exact spelling, a domain, or a name that begins with one
    ("Amazon After Rebate", "Woot! An Amazon Company")."""
    n = _straight(clean(name))
    if not n:
        return None
    hit = _names().get(norm(n))
    if hit:
        return hit
    host = n.lower().removeprefix("www.")
    for s in registry():
        if any(host == d or host.endswith("." + d) for d in s.domains):
            return s
    if n.lower().endswith(".com") and len(n) > 4:
        hit = _names().get(norm(n[:-4]))
        if hit:
            return hit
    words = n.split()
    for k in range(len(words) - 1, 0, -1):          # the longest leading words that are a store's name
        hit = _names().get(norm(" ".join(words[:k])))
        if hit:
            return hit
    return None


def stores_in(text: str) -> list[tuple[int, OnlineStore, bool]]:
    """Every registry store named in the text: (where, store, named by an event), first first."""
    t = _straight(text)
    found: dict[str, tuple[int, OnlineStore, bool]] = {}
    taken: list[tuple[int, int]] = []
    for rx, s, event in _patterns():
        for m in rx.finditer(t):
            if any(a < m.end() and m.start() < b for a, b in taken):     # inside a longer name already found
                continue
            taken.append((m.start(), m.end()))
            if s.key not in found or m.start() < found[s.key][0]:
                found[s.key] = (m.start(), s, event)
    return sorted(found.values(), key=lambda x: x[0])
