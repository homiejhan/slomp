"""Keyword search: a search's results, narrowed to the deals that say the words typed.

A search is a city and what you are shopping for. Keywords narrow what it finds: "lego", "air fryer", "nike shoes".
They are looked for in what a card shows of a deal: its title, the store or seller, the brand, the category its
source files it under, and for a sale its name, its offer, its code and its city. Nothing is looked up anew: the
same deals are found, and the ones that do not say the words are left out.

How words are matched:

- Every word typed must be found (and "a", "the", "for" and the like are not asked for).
- Case, accents and punctuation don't matter, and an apostrophe is not a break: "kohls" finds "Kohl's", "loreal"
  finds "L'Oréal", "t-shirt" finds "T-Shirt".
- A word of four letters or more is found at the start of a word: "head" finds "Headphones", "lego" finds
  "LEGOLAND". A shorter one must be the whole word, so "car" does not find "Cart" or "Card", and "tv" finds "TV".
- A plural finds its singular and the other way round: "shoes" finds "Shoe", "battery" finds "Batteries", "tv"
  finds "TVs". Only a whole word counts there, so "lens" does not find "Lenovo".
- A word written joined or apart is the same word: "tshirt" finds "T-Shirt", and "ear buds" finds "Earbuds".

With keywords and no industry chosen, every industry is searched. Online deals are narrowed before the best of each
industry are taken, so a search reaches past the ones a page would otherwise show.

The published site does its searches in the browser (static/engine.js, "keyword search"), so this rule is written
twice. It is kept this small so the two can be the same; tests/test_search.py runs both on the same deals.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Iterable, Optional

FILLER = frozenset({"a", "an", "and", "or", "the", "for", "of", "in", "on", "at", "to", "with"})
MAX_WORDS = 8               # words asked for in one search; more are ignored
MAX_CHARS = 100             # of the text typed
STARTS = 4                  # a word this long is found at the start of a word; a shorter one must be the whole word


def fold(text) -> str:
    """Text as it is compared: lowercase, accents off, apostrophes dropped, anything else that is not a letter or a
    digit a space."""
    t = unicodedata.normalize("NFKD", str(text or "")).lower()
    t = re.sub(r"[̀-ͯ]", "", t)
    t = re.sub(r"['’‘`]", "", t)
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


def singulars(word: str) -> tuple[str, ...]:
    """What a plural may be the plural of: "batteries" -> battery, batterie; "boxes" -> box, boxe; "shoes" -> sho,
    shoe; "tvs" -> tv. Not every one is a word; one that is not finds nothing."""
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y", word[:-1]
    if len(word) > 3 and word.endswith("es"):
        return word[:-2], word[:-1]
    if len(word) > 2 and word.endswith("s") and not word.endswith("ss"):
        return (word[:-1],)
    return ()


def words(q) -> list[str]:
    """The words a search asks for, in the order typed: folded, without the filler words, each once."""
    out: list[str] = []
    for w in fold(str(q or "")[:MAX_CHARS]).split():
        if w not in FILLER and w not in out:
            out.append(w)
    return out[:MAX_WORDS]


def said(item: dict) -> str:
    """What a card shows of a deal, as one line: a weekly ad's item, a promotion, a regular deal, an online deal or a
    sale, as the API gives each."""
    store, product, regular = item.get("store"), item.get("product"), item.get("regular")
    parts = [item.get("title"), item.get("name"), item.get("merchant"), item.get("seller"), item.get("store_name"),
             item.get("brand"), item.get("category"), item.get("offer"), item.get("code"), item.get("city"),
             store.get("name") if isinstance(store, dict) else None,
             product.get("brand") if isinstance(product, dict) else None,
             product.get("model") if isinstance(product, dict) else None,
             regular.get("days_text") if isinstance(regular, dict) else None,
             *(item.get("conditions") or [])]
    return " ".join(str(p) for p in parts if p)


def same(a: str, b: str) -> bool:
    """One word and its plural are the same word."""
    return a == b or a in singulars(b) or b in singulars(a)


def found(word: str, text_words: Iterable[str]) -> bool:
    """Whether one word asked for is among a deal's words: as one of them, its plural or its singular, or, when it
    is long enough, as the start of one."""
    starts = len(word) >= STARTS
    return any(same(word, t) or (starts and t.startswith(word)) for t in text_words)


def matches(item: dict, asked: list[str]) -> bool:
    """Whether a deal says every word asked for. No words asked: every deal does."""
    if not asked:
        return True
    have = fold(said(item)).split()
    joined = [a + b for a, b in zip(have, have[1:])]            # "t shirt" as one word, for "tshirt"
    for i, w in enumerate(asked):
        if found(w, have) or any(same(w, j) for j in joined):
            continue
        # ... and two words asked for as one, for a deal that writes them so: "ear buds" finds "Earbuds"
        pairs = ([asked[i - 1] + w] if i else []) + ([w + asked[i + 1]] if i + 1 < len(asked) else [])
        if not any(found(p, have) for p in pairs):
            return False
    return True


def query(q) -> Optional[dict]:
    """How a search's keywords were read, for the answer: the text and the words asked for. None with no words."""
    asked = words(q)
    return {"q": " ".join(str(q or "")[:MAX_CHARS].split()), "words": asked} if asked else None


# --- an answer narrowed -------------------------------------------------------------------------------------------
def local(payload: dict, asked: list[str]) -> dict:
    """/api/v1/local's answer with only the deals that say the words."""
    if not asked:
        return payload
    out = dict(payload)
    for key in ("deals", "promotions", "unconfirmed", "regulars"):
        out[key] = [d for d in payload.get(key, []) if matches(d, asked)]
    out["counts"] = {key: len(out[key]) for key in ("deals", "promotions", "unconfirmed", "regulars")}
    return out


def online(payload: dict, asked: list[str], limit: int) -> dict:
    """/api/v1/online's answer with only the deals that say the words: the best `limit` of each industry among
    those, so `payload` should hold every deal kept and not just a page of them."""
    if not asked:
        return payload
    out = dict(payload)
    out["deals"] = {i: [d for d in deals if matches(d, asked)][:limit] for i, deals in payload.get("deals", {}).items()}
    out["counts"] = {i: len(deals) for i, deals in out["deals"].items()}
    return out


def sales(payload: dict, asked: list[str]) -> dict:
    """/api/v1/sales' answer with only the sales that say the words."""
    if not asked:
        return payload
    out = dict(payload)
    out["sales"] = [s for s in payload.get("sales", []) if matches(s, asked)]
    out["counts"] = {"sales": len(out["sales"]), "stores": len({s.get("store") or s.get("store_name") for s in out["sales"]})}
    return out
