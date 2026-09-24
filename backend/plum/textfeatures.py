"""Turns a product title into comparable features: word bag, model codes, sizes."""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

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


@dataclass(frozen=True)
class Features:
    toks: tuple[str, ...] = ()
    bag: frozenset[str] = frozenset()
    codes: frozenset[str] = frozenset()
    sizes: frozenset[str] = frozenset()


@lru_cache(maxsize=8192)
def features(title: str) -> Features:
    """Pure function of the title, so it is cached by title (immutable result, safe to share)."""
    toks = tokens(title)
    bag: set[str] = set()
    codes: set[str] = set()
    sizes: set[str] = set()
    for t in toks:
        c = compact(t)
        bag.add(c)
        if code_like(t):
            codes.add(c)
        m = UNIT_RE.match(t)
        if m:
            sizes.add(m.group(1) + _UNIT_NORM.get(m.group(2), m.group(2)))
    for a, b in zip(toks, toks[1:]):
        if _NUM.match(a) and UNIT_WORD.match(b):
            sizes.add(a + _UNIT_NORM.get(b, b))
            continue
        if not (_eligible(a) and _eligible(b)):
            continue
        if _has_digit(a) or _has_digit(b):
            j = compact(a + b)
            if _has_digit(j) and _has_alpha(j) and len(j) <= 14:
                codes.add(j)
    return Features(tuple(toks), frozenset(bag), frozenset(codes), frozenset(sizes))


# Tokens shaped like model numbers that are really specs, sizes or counts: 1080p, 4k, 5000mah, 12pk, gen3, wifi7.
_SPEC = re.compile(r"\d{3,4}p|\d{1,2}k(?:uhd|hdr)?|\d+(?:hz|gb|tb|mb|mah|mm|cm|in|inch|ft|oz|lbs?|qt|ct|pk|pcs?|w|v|a|wh|"
                   r"x\d+)|(?:gen|ddr|usb|ipx?|wifi|pcie|hdmi|series|model|size|type|class|version|v)\d+|(?:19|20)\d\d")


@lru_cache(maxsize=8192)
def model_codes(title: str) -> frozenset[str]:
    """Tokens that identify one product: EM2FPAF32B, WH-1000XM6, DWHT10998, LEGO 10281. Unlike `features().codes`,
    no joined word pairs and no specs, so "12 mega rolls", "1080p" and "Wi-Fi 7" never make two products "the same"."""
    out = set()
    for t in tokens(title):
        c = compact(t)
        if _SPEC.fullmatch(c) or UNIT_RE.match(t) or ORD_RE.match(t):
            continue
        digits = sum(ch.isdigit() for ch in c)
        if (c.isdigit() and len(c) >= 5) or (_has_alpha(c) and digits >= 2 and len(c) >= 4):
            out.add(c)
    return frozenset(out)


def near_code(a: str, b: str) -> bool:
    """Same length, differ in one position (two for long codes): WH-1000XM4 vs XM5, V11 vs V15, 10280 vs 10281."""
    if a == b or len(a) != len(b) or len(a) < 3:
        return False
    limit = 2 if len(a) >= 8 else 1
    return sum(x != y for x, y in zip(a, b)) <= limit


def unit_of(size: str) -> str:
    return re.sub(r"^[\d.]+", "", size)
