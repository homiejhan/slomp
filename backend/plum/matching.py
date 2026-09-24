"""Product <-> listing entity resolution.

Order of evidence, strongest first:
  1. Shared valid GTIN                      -> exact
  2. Shared model code (WH-1000XM5, 10281)  -> +0.45
     Near-miss model code (XM4 vs XM5)      -> -0.35 (applies even if another code is shared)
  3. Word overlap (Jaccard on compacted tokens); weighted 0.5, or 0.95 when the product has no model code
  4. Accessory/bundle words, size clashes, brand mismatch, conflicting GTIN -> penalties
Blocking: an inverted index over product tokens keeps candidate sets small.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Iterable, Optional

from .identifiers import canonical_gtin, is_valid_gtin
from .models import Listing, MatchResult, Product, Tier
from .textfeatures import ACCESSORY, Features, compact, features, near_code, norm, tokens, unit_of

THRESHOLD_LIKELY = 0.55
THRESHOLD_CONFIDENT = 0.75


def _product_features(p: Product, cache: dict[str, Features]) -> Features:
    f = cache.get(p.id)
    if f is None:
        f = cache[p.id] = features(p.title)
    return f


_FCACHE: dict[str, Features] = {}


def match(product: Product, listing: Listing, fcache: Optional[dict[str, Features]] = None) -> MatchResult:
    fcache = _FCACHE if fcache is None else fcache
    reasons: list[str] = []
    pg = canonical_gtin(product.gtin)
    lg = canonical_gtin(listing.gtin) if listing.gtin else None
    if listing.gtin and not is_valid_gtin(listing.gtin):
        reasons.append("listing UPC fails its check digit, ignored")
    if pg and lg and pg == lg:
        return MatchResult(1.0, Tier.EXACT, ["UPC matches"])

    P = _product_features(product, fcache)
    f = features(listing.title)
    score = 0.0

    shared = [c for c in f.codes if c in P.codes]
    conflict = next((c for c in f.codes if c not in P.codes and any(near_code(c, p) for p in P.codes)), None)
    if shared:
        score += 0.45
        reasons.append(f"model code {sorted(shared)[0]} matches")
    if conflict:
        score -= 0.35
        reasons.append(f"different model ({conflict})")

    inter = len(f.bag & P.bag)
    union = len(f.bag | P.bag)
    jac = inter / union if union else 0.0
    score += (0.5 if P.codes else 0.95) * jac
    reasons.append(f"{round(jac * 100)}% of the words line up")

    acc = next((t for t in f.bag if t in ACCESSORY and t not in P.bag), None)
    if acc:
        score -= 0.6
        reasons.append(f"looks like an accessory or bundle ({acc})")

    clash = next((s for s in f.sizes if s not in P.sizes and any(unit_of(p) == unit_of(s) for p in P.sizes)), None)
    if clash:
        score -= 0.5
        reasons.append(f"size differs ({clash})")

    if listing.brand:
        brand_ok = compact(norm(listing.brand)) == compact(norm(product.brand))
    else:
        brand_ok = all(compact(b) in f.bag for b in tokens(product.brand))
    if not brand_ok:
        score = min(score, 0.3)
        reasons.append("brand doesn't match")

    if pg and lg and lg != pg:
        if shared and not conflict and jac >= 0.5:
            score -= 0.15
            reasons.append("different UPC, probably a color or size variant")
        else:
            score -= 0.4
            reasons.append("carries a different UPC")

    score = round(max(0.0, min(1.0, score)), 3)
    tier = Tier.CONFIDENT if score >= THRESHOLD_CONFIDENT else Tier.LIKELY if score >= THRESHOLD_LIKELY else Tier.REJECTED
    return MatchResult(score, tier, reasons)


class ProductIndex:
    """Inverted index for blocking: token -> product ids, plus GTIN and search-alias lookups."""

    def __init__(self, products: Iterable[Product]):
        self.products: dict[str, Product] = {}
        self.by_gtin: dict[str, str] = {}
        self.tok_index: dict[str, set[str]] = defaultdict(set)
        self.search_bags: dict[str, set[str]] = {}
        self.fcache: dict[str, Features] = {}
        for p in products:
            self.add(p)

    def add(self, p: Product) -> None:
        self.products[p.id] = p
        g = canonical_gtin(p.gtin)
        if g:
            self.by_gtin[g] = p.id
        f = _product_features(p, self.fcache)
        bag = set(f.bag)
        for a in p.aliases:
            bag.update(compact(t) for t in tokens(a))
        self.search_bags[p.id] = bag
        for t in bag:
            self.tok_index[t].add(p.id)

    def candidates(self, listing: Listing, limit: int = 25) -> list[Product]:
        g = canonical_gtin(listing.gtin) if listing.gtin else None
        if g and g in self.by_gtin:
            return [self.products[self.by_gtin[g]]]
        counts: dict[str, int] = defaultdict(int)
        for t in features(listing.title).bag:
            for pid in self.tok_index.get(t, ()):
                counts[pid] += 1
        ranked = sorted(counts.items(), key=lambda kv: -kv[1])[:limit]
        return [self.products[pid] for pid, _ in ranked]

    def resolve(self, listing: Listing) -> tuple[Optional[Product], Optional[MatchResult]]:
        best: tuple[Optional[Product], Optional[MatchResult]] = (None, None)
        for p in self.candidates(listing):
            m = match(p, listing, self.fcache)
            if best[1] is None or m.score > best[1].score:
                best = (p, m)
        if best[1] and best[1].tier == Tier.REJECTED:
            return (None, best[1])
        return best

    def find(self, query: str) -> tuple[Optional[Product], str]:
        """Search box: barcode first, then token/prefix/model-code scoring over titles and aliases."""
        q = query.strip()
        if not q:
            return None, "empty"
        digits = "".join(ch for ch in q if ch.isdigit())
        if len(digits) >= 8 and len(digits) == len(q.replace(" ", "").replace("-", "")):
            g = canonical_gtin(digits)
            if g is None:
                return None, "invalid barcode"
            pid = self.by_gtin.get(g)
            return (self.products[pid], "barcode") if pid else (None, "unknown barcode")
        f = features(q)
        qt = list(f.bag)
        best, best_score = None, 0.0
        for pid, bag in self.search_bags.items():
            sc = 0.0
            for t in qt:
                if t in bag:
                    sc += 1
                elif len(t) >= 3 and any(x.startswith(t) for x in bag):
                    sc += 0.6
            sc += 1.5 * len(f.codes & self.fcache[pid].codes)
            sc /= max(len(qt), 1)
            if sc > best_score:
                best, best_score = self.products[pid], sc
        return (best, "text") if best_score >= 0.5 else (None, "no match")
