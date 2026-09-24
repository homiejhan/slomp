"""Turns a product title into comparable features: word bag, model codes, sizes.

Mirrors frontend/PlumApp.jsx `features()` so both sides agree on what a match is.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

STOP = {"the", "a", "an", "and", "with", "for", "of", "in", "by", "to", "new", "latest", "model", "edition", "pack",
        "official", "genuine", "authentic", "original", "free", "shipping", "fast", "us", "usa", "ships", "sealed",
        "brand", "best"}
ACCESSORY = {"case", "cover", "skin", "cable", "charger", "replacement", "compatible", "stand", "protector", "strap",
             "filter", "bag", "mount", "earpads", "cushions", "adapter", "bundle", "kit", "refill", "sleeve", "holder",
             "lid", "screen"}
_UNITS = "oz|qt|quart|gb|tb|mm|cm|in|inch|ft|lb|lbs|kg|ml|l|w|v|hz|mah|ct"
UNIT_RE = re.compile(rf"^(\d+(?:\.\d+)?)({_UNITS})$")
UNIT_WORD = re.compile(rf"^({_UNITS})$")
ORD_RE = re.compile(r"^\d+(st|nd|rd|th)$")
_NUM = re.compile(r"^\d+(\.\d+)?$")
_UNIT_NORM = {"quart": "qt", "inch": "in", "lbs": "lb"}


def norm(s: str) -> str:
    s = s.lower().replace("’", "").replace("'", "")
    s = re.sub(r"[^a-z0-9.+\- ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def tokens(s: str) -> list[str]:
    out = []
    for t in norm(s).split(" "):
        t = t.strip(".-+")
        if t and t not in STOP:
            out.append(t)
    return out


def compact(t: str) -> str:
    return t.replace("-", "").replace(".", "")


def _has_digit(t: str) -> bool:
    return any(c.isdigit() for c in t)


def _has_alpha(t: str) -> bool:
    return any(c.isalpha() for c in t)


def code_like(t: str) -> bool:
    if ORD_RE.match(t) or UNIT_RE.match(t):
        return False
    return (_has_digit(t) and _has_alpha(t) and len(t) >= 3) or bool(re.match(r"^\d{4,}$", t))


def _eligible(t: str) -> bool:
    return not (ORD_RE.match(t) or UNIT_RE.match(t) or UNIT_WORD.match(t))


@dataclass
class Features:
    toks: list[str] = field(default_factory=list)
    bag: set[str] = field(default_factory=set)
    codes: set[str] = field(default_factory=set)
    sizes: set[str] = field(default_factory=set)


def features(title: str) -> Features:
    f = Features(toks=tokens(title))
    for t in f.toks:
        c = compact(t)
        f.bag.add(c)
        if code_like(t):
            f.codes.add(c)
        m = UNIT_RE.match(t)
        if m:
            f.sizes.add(m.group(1) + _UNIT_NORM.get(m.group(2), m.group(2)))
    for a, b in zip(f.toks, f.toks[1:]):
        if _NUM.match(a) and UNIT_WORD.match(b):
            f.sizes.add(a + _UNIT_NORM.get(b, b))
            continue
        if not (_eligible(a) and _eligible(b)):
            continue
        if _has_digit(a) or _has_digit(b):
            j = compact(a + b)
            if _has_digit(j) and _has_alpha(j) and len(j) <= 14:
                f.codes.add(j)
    return f


def near_code(a: str, b: str) -> bool:
    """Same length, differ in one position (two for long codes): WH-1000XM4 vs XM5, V11 vs V15, 10280 vs 10281."""
    if a == b or len(a) != len(b) or len(a) < 3:
        return False
    limit = 2 if len(a) >= 8 else 1
    return sum(x != y for x, y in zip(a, b)) <= limit


def unit_of(size: str) -> str:
    return re.sub(r"^[\d.]+", "", size)
