"""GTIN / UPC / EAN handling and identifier extraction from free text."""
from __future__ import annotations

import re
from typing import Optional

_GTIN_LENS = {8, 12, 13, 14}
_DIGIT_RUN = re.compile(r"(?<!\d)(\d{8}|\d{12,14})(?!\d)")
_MPN = re.compile(r"\b(?=[A-Z0-9/-]{4,20}\b)(?=[A-Z0-9/-]*\d)(?=[A-Z0-9/-]*[A-Z])[A-Z0-9][A-Z0-9/-]*\b")


def check_digit(body: str) -> int:
    """Modulo-10 check digit; weights 3,1,3,1... from the rightmost body digit."""
    total = 0
    for i, ch in enumerate(reversed(body)):
        total += int(ch) * (3 if i % 2 == 0 else 1)
    return (10 - total % 10) % 10


def make_gtin(body: str) -> str:
    if not body.isdigit():
        raise ValueError("GTIN body must be digits")
    return body + str(check_digit(body))


def is_valid_gtin(raw: Optional[str]) -> bool:
    d = re.sub(r"\D", "", raw or "")
    if len(d) not in _GTIN_LENS:
        return False
    return check_digit(d[:-1]) == int(d[-1])


def canonical_gtin(raw: Optional[str]) -> Optional[str]:
    """GTIN-14 form (zero padded) or None if invalid. Lets UPC-A and EAN-13 compare equal."""
    if not is_valid_gtin(raw):
        return None
    return re.sub(r"\D", "", raw or "").zfill(14)


def short_gtin(raw: Optional[str]) -> Optional[str]:
    """The GTIN at its printed length (UPC-A 12, EAN-13, GTIN-14) for APIs that reject the zero-padded form.

    Stripping every leading zero instead turns UPC 027242923508 into an 11-digit number that matches nothing.
    """
    g = canonical_gtin(raw)
    if g is None:
        return None
    s = g.lstrip("0")
    return s.zfill(12) if len(s) <= 12 else s.zfill(13) if len(s) == 13 else s


def extract_gtins(text: str) -> list[str]:
    """Valid GTINs hiding in a title/description/URL, canonicalised."""
    out = []
    for m in _DIGIT_RUN.finditer(text or ""):
        c = canonical_gtin(m.group(1))
        if c and c not in out:
            out.append(c)
    return out


def extract_mpns(text: str) -> list[str]:
    """Manufacturer-part-number-looking tokens (mixed letters+digits, 4-20 chars)."""
    return sorted({m.group(0) for m in _MPN.finditer((text or "").upper())})
