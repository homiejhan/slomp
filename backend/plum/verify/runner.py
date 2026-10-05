"""One verification iteration: sample cities and industries, run Plum like a user, then run 200 live tests.

    plum verify --iteration 3                         # runs everything except the blind industry judge
    python -m plum.verify.runner --judge 3 labels.json  # merges the judge's labels and finalizes the report

Per iteration (200 tests): local fidelity 30, retailer page 10, window 15, vicinity 20, industry 20, terms/math 10,
recall 15;
online fidelity 25, merchant link 15, comparisons 20, industry 10, ranking/quality 10. A test that can't be made
(source down, blocked, not covered) is recorded as inconclusive and replaced by another subject of the same kind;
a category that runs out of subjects hands its remaining tests to that side's fidelity tests.
"""
from __future__ import annotations

import asyncio
import json
import random
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from .. import industries as ind
from ..local import LocalResult
from ..models import LocalDeal, OnlineDeal
from ..online import OnlineResult
from ..reference import cities
from ..service import PlumService
from . import checks
from .checks import FAIL, INCONCLUSIVE, PASS

REPO = Path(__file__).resolve().parents[3]
REPORTS = REPO / "docs" / "verification"
WORK = Path.home() / ".cache" / "plum" / "verify"

PLAN: list[tuple[str, str, int]] = [
    ("local", "L-FID source fidelity", 30), ("local", "L-RET retailer page", 10), ("local", "L-WIN time window", 15),
    ("local", "L-GEO vicinity", 20),
    ("local", "L-IND industry (blind judge)", 20), ("local", "L-MATH terms and math", 10), ("local", "L-REC recall", 15),
    ("online", "O-FID source fidelity", 25), ("online", "O-MER merchant link", 15),
    ("online", "O-CMP cross-site comparison", 20), ("online", "O-IND industry (blind judge)", 10),
    ("online", "O-RANK ranking and quality", 10),
]
RADIUS = 25.0


def sample_queries(rng: random.Random, n_large: int = 3, n_mid: int = 3, n_small: int = 4) -> list[tuple[str, list[str]]]:
    """Cities stratified by size; industries spread so every one appears at least once."""
    allc = list(cities())
    large = [c for c in allc if (c.population or 0) >= 200_000]
    mid = [c for c in allc if 20_000 <= (c.population or 0) < 200_000]
    small = [c for c in allc if (c.population or 0) < 20_000]
    picked = rng.sample(large, n_large) + rng.sample(mid, n_mid) + rng.sample(small, n_small)
    inds = list(ind.IDS)
    rng.shuffle(inds)
    plan: list[list[str]] = [[] for _ in picked]
    for k, i in enumerate(inds):
        plan[k % len(picked)].append(i)
    for p in plan:
        while len(p) < 2:
            extra = rng.choice(ind.IDS)
            if extra not in p:
                p.append(extra)
    return [(c.id, p) for c, p in zip(picked, plan)]


class Iteration:
    def __init__(self, iteration: int, n_tests: int = 200, seed: Optional[int] = None):
        self.iteration = iteration
        self.seed = seed if seed is not None else 1000 * iteration + 7
        self.rng = random.Random(self.seed)
        self.scale = n_tests / 200
        self.svc = PlumService()
        self.run_id = f"it{iteration:02d}-{datetime.now():%Y%m%d%H%M}"
        self.tests: list[dict] = []
        self.judge_items: list[dict] = []
        self.local: list[LocalResult] = []
        self.online: Optional[OnlineResult] = None
        self.now = datetime.now(timezone.utc)

    # -- running Plum like a user ------------------------------------------------------------------------------
    async def run_plum(self) -> None:
        self.queries = sample_queries(self.rng)
        for cid, inds in self.queries:
            t = time.time()
            res = await self.svc.local(cid, inds, RADIUS, use_cache=False)
            self.local.append(res)
            print(f"  local {cid} {inds}: {len(res.deals)} deals, {len(res.promotions)} promotions, "
                  f"{len(res.unconfirmed)} unconfirmed ({time.time() - t:.0f}s)", flush=True)
        online_inds = sorted({i for _, inds in self.queries for i in inds if i != "dining"})
        t = time.time()
        self.online = await self.svc.online(online_inds, limit=25, use_cache=False)
        print(f"  online {online_inds}: {sum(len(v) for v in self.online.deals.values())} deals "
              f"({time.time() - t:.0f}s)", flush=True)

    # -- subjects -----------------------------------------------------------------------------------------------
    def local_subjects(self, flipp_only: bool = True, mapped_only: bool = False) -> list[tuple[LocalResult, LocalDeal]]:
        """Deals spread across cities: round-robin over cities, random order within each."""
        per_city = []
        for res in self.local:
            ds = [d for d in res.all_deals() if (not flipp_only or d.item_id) and
                  (not mapped_only or d.store_status == "nearby")]
            self.rng.shuffle(ds)
            per_city.append([(res, d) for d in ds])
        out = []
        while any(per_city):
            for lst in per_city:
                if lst:
                    out.append(lst.pop())
        return out

    def online_subjects(self) -> list[tuple[str, OnlineDeal]]:
        per_ind = []
        for i, lst in (self.online.deals.items() if self.online else []):
            xs = [(i, d) for d in lst]
            self.rng.shuffle(xs)
            per_ind.append(xs)
        out, seen = [], set()
        while any(per_ind):
            for lst in per_ind:
                if lst:
                    i, d = lst.pop()
                    if d.id not in seen:
                        seen.add(d.id)
                        out.append((i, d))
        return out

    # -- the tests ----------------------------------------------------------------------------------------------
    async def run_category(self, name: str, quota: int, subjects: list, test: Callable) -> int:
        """Run `test` over subjects until `quota` conclusive results; returns the shortfall."""
        done = 0
        for k, subj in enumerate(subjects):
            if done >= quota:
                break
            try:
                verdict, detail, label = await test(subj)
            except Exception as e:                      # a test crash is the harness's problem: record it
                verdict, detail, label = INCONCLUSIVE, {"why": f"test error: {type(e).__name__}: {e}"}, "?"
            self.tests.append({"id": f"{name.split()[0]}-{len(self.tests):03d}", "category": name, "subject": label,
                               "verdict": verdict, "detail": detail})
            if verdict != INCONCLUSIVE:
                done += 1
        return max(0, quota - done)

    async def run_tests(self) -> None:
        http, flipp = self.svc.http, self.svc.flipp
        q = {name: max(1, round(n * self.scale)) for _, name, n in PLAN}
        L = lambda d: f"{d.merchant}: {d.title[:70]}"     # noqa: E731

        async def fid(s):
            res, d = s
            if not d.item_id:                                # a restaurant promotion: re-read its post
                v, det = await checks.online_fidelity(http, _as_online(d))
                return v, det, f"[{res.city.id}] promo {L(d)}"
            v, det = await checks.local_fidelity(http, d, res.city.tz)
            return v, det, f"[{res.city.id}] {L(d)}"

        async def win(s):
            res, d = s
            v, det = await checks.local_window(http, d, res.city.tz, res.window_start, res.window_end)
            return v, det, f"[{res.city.id}] {L(d)}"

        async def geo(s):
            res, d = s
            v, det = await asyncio.to_thread(checks.local_vicinity, d, res.city.lat, res.city.lon, res.radius_mi)
            return v, det, f"[{res.city.id}] {d.merchant}"

        async def math(s):
            res, d = s
            v, det = await checks.local_math(http, d)
            return v, det, f"[{res.city.id}] {L(d)}"

        async def ret(s):
            res, d = s
            v, det = await checks.local_retailer(http, d)
            return v, det, f"[{res.city.id}] {L(d)}"

        async def rec(s):
            res, industry = s
            v, det = await checks.local_recall(http, res, industry, self.rng, flipp)
            return v, det, f"[{res.city.id}] {industry}"

        short_local = 0
        short_local += await self.run_category("L-WIN time window", q["L-WIN time window"], self.local_subjects(), win)
        short_local += await self.run_category("L-GEO vicinity", q["L-GEO vicinity"],
                                               self.local_subjects(flipp_only=False, mapped_only=True), geo)
        short_local += await self.run_category("L-MATH terms and math", q["L-MATH terms and math"],
                                               self.local_subjects(), math)
        retail_subjects = [(res, d) for res, d in self.local_subjects() if d.retailer_url and
                           not any(b in d.retailer_url for b in checks.RETAILER_BLOCKED)]
        short_local += await self.run_category("L-RET retailer page", q["L-RET retailer page"], retail_subjects, ret)
        recall_subjects = [(res, i) for res in self.local for i in res.industries if i != "dining"] * 3
        self.rng.shuffle(recall_subjects)
        short_local += await self.run_category("L-REC recall", q["L-REC recall"], recall_subjects, rec)
        short_local += self.judge_local(q["L-IND industry (blind judge)"])
        await self.run_category("L-FID source fidelity", q["L-FID source fidelity"] + short_local,
                                self.local_subjects(flipp_only=False), fid)

        O = lambda d: f"{d.source}: {d.title[:70]}"      # noqa: E731

        async def ofid(s):
            i, d = s
            v, det = await checks.online_fidelity(http, d)
            return v, det, f"[{i}] {O(d)}"

        async def omer(s):
            i, d = s
            v, det = await checks.online_merchant(http, d)
            return v, det, f"[{i}] {O(d)}"

        async def ocmp(s):
            d, k = s
            v, det = await checks.online_comparison(http, d, k)
            return v, det, f"{d.comparisons[k].site} for {d.title[:60]}"

        async def orank(s):
            i, d = s
            v, det = checks.online_ranking(d, self.online.deals[i], self.now)
            return v, det, f"[{i}] {O(d)}"

        short_online = 0
        short_online += await self.run_category("O-MER merchant link", q["O-MER merchant link"],
                                                self.online_subjects(), omer)
        cmp_subjects = [(d, k) for _, d in self.online_subjects() for k in range(len(d.comparisons))]
        short_online += await self.run_category("O-CMP cross-site comparison", q["O-CMP cross-site comparison"],
                                                cmp_subjects, ocmp)
        short_online += await self.run_category("O-RANK ranking and quality", q["O-RANK ranking and quality"],
                                                self.online_subjects(), orank)
        short_online += self.judge_online(q["O-IND industry (blind judge)"])
        await self.run_category("O-FID source fidelity", q["O-FID source fidelity"] + short_online,
                                self.online_subjects(), ofid)

    # -- blind industry judge -------------------------------------------------------------------------------------
    def judge_local(self, quota: int) -> int:
        subj = self.local_subjects(flipp_only=False)
        picked = 0
        for res, d in subj:
            if picked >= quota:
                break
            asked = [i for i in res.industries if i in d.industries]
            if not asked:
                continue
            tid = f"L-IND-{len(self.tests):03d}"
            self.tests.append({"id": tid, "category": "L-IND industry (blind judge)", "verdict": "pending",
                               "subject": f"[{res.city.id}] {d.merchant}: {d.title[:70]}",
                               "detail": {"shown_under": asked[0], "plum_industries": d.industries,
                                          "rule": d.industry_rule}})
            self.judge_items.append({"qid": tid, "title": d.title, "store": d.merchant})
            picked += 1
        return max(0, quota - picked)

    def judge_online(self, quota: int) -> int:
        picked = 0
        for i, d in self.online_subjects():
            if picked >= quota:
                break
            tid = f"O-IND-{len(self.tests):03d}"
            self.tests.append({"id": tid, "category": "O-IND industry (blind judge)", "verdict": "pending",
                               "subject": f"[{i}] {d.source}: {d.title[:70]}",
                               "detail": {"shown_under": i, "plum_industries": d.industries, "rule": d.industry_rule}})
            self.judge_items.append({"qid": tid, "title": d.title, "store": d.seller})
            picked += 1
        return max(0, quota - picked)

    # -- reporting ----------------------------------------------------------------------------------------------
    def quality(self) -> dict:
        """Coverage and strength of evidence, beyond pass/fail."""
        local = [d for r in self.local for d in r.all_deals() if d.item_id]
        firm = [d for d in local if d.terms.basis == "store_regular"]
        online = self.online.all_deals() if self.online else []
        n = max(1, len(online))
        return {
            "local_deals": len(local),
            "local_firm_basis_share": round(len(firm) / max(1, len(local)), 3),
            "local_unconfirmed_store_share": round(sum(d.store_status == "unmapped" for d in local) / max(1, len(local)), 3),
            "local_queries_with_no_results": sum(1 for r in self.local if not r.all_deals()),
            "online_deals": len(online),
            "online_with_product_identity": sum(1 for d in online if d.product.key),
            "online_with_2plus_other_sites": sum(1 for d in online if len(d.comparisons) >= 2),
            "online_store_checked": sum(1 for d in online if d.store_check),
            "online_flagged_changed": sum(1 for d in online if any(c.startswith(("store price now", "out of stock"))
                                                                   for c in d.conditions)),
            "online_basis_share": {b: round(sum(d.basis == b for d in online) / n, 3)
                                   for b in ("market", "store_regular", "editor_compare", "history", "list")},
        }

    def save(self) -> Path:
        REPORTS.mkdir(parents=True, exist_ok=True)
        WORK.mkdir(parents=True, exist_ok=True)
        report = {"iteration": self.iteration, "seed": self.seed, "run_id": self.run_id,
                  "run_at": self.now.isoformat(), "queries": self.queries,
                  "plum": {"local": [{"city": r.city.id, "industries": r.industries, "deals": len(r.deals),
                                      "promotions": len(r.promotions), "unconfirmed": len(r.unconfirmed),
                                      "excluded": dict(r.excluded)} for r in self.local],
                           "online": {k: len(v) for k, v in (self.online.deals.items() if self.online else [])}},
                  "tests": self.tests}
        report["summary"] = summarize(self.tests)
        report["quality"] = self.quality()
        path = REPORTS / f"iteration-{self.iteration:02d}.json"
        path.write_text(json.dumps(report, indent=1, default=str))
        (WORK / f"iteration-{self.iteration:02d}-judge-packet.json").write_text(json.dumps(
            {"instructions": JUDGE_INSTRUCTIONS, "industries": [{"id": i.id, "name": i.name, "description": i.description}
                                                               for i in ind.INDUSTRIES],
             "items": self.judge_items}, indent=1))
        (WORK / f"iteration-{self.iteration:02d}-results.json").write_text(json.dumps(
            {"local": [r.to_dict() for r in self.local], "online": self.online.to_dict() if self.online else None},
            default=str))
        return path


JUDGE_INSTRUCTIONS = ("For each item, list every industry from the fixed list that a shopper browsing that industry "
                      "would reasonably expect to find this product or offer in. Use only the item's title and store. "
                      "Return JSON: {\"labels\": [{\"qid\": ..., \"industries\": [ids...]}]}.")


def _as_online(d: LocalDeal) -> OnlineDeal:
    return OnlineDeal(id=d.id, source="promo", source_url=d.source_url, title=d.title, seller=d.merchant, price=0.0,
                      industries=d.industries, industry_rule=d.industry_rule)


def summarize(tests: list[dict]) -> dict:
    by = defaultdict(Counter)
    for t in tests:
        by[t["category"]][t["verdict"]] += 1
    cats = {}
    for c, cnt in sorted(by.items()):
        concl = cnt[PASS] + cnt[FAIL]
        cats[c] = {"pass": cnt[PASS], "fail": cnt[FAIL], "inconclusive": cnt[INCONCLUSIVE], "pending": cnt["pending"],
                   "pass_rate": round(cnt[PASS] / concl, 3) if concl else None}
    tot = Counter(t["verdict"] for t in tests)
    concl = tot[PASS] + tot[FAIL]
    return {"conclusive": concl, "pass": tot[PASS], "fail": tot[FAIL], "inconclusive": tot[INCONCLUSIVE],
            "pending": tot["pending"], "pass_rate": round(tot[PASS] / concl, 3) if concl else None,
            "by_category": cats}


def merge_judge(iteration: int, labels_path: Path) -> dict:
    path = REPORTS / f"iteration-{iteration:02d}.json"
    report = json.loads(path.read_text())
    labels = {x["qid"]: set(x.get("industries") or []) for x in json.loads(labels_path.read_text())["labels"]}
    for t in report["tests"]:
        if t["verdict"] == "pending" and t["id"] in labels:
            want = t["detail"]["shown_under"]
            t["detail"]["judge_industries"] = sorted(labels[t["id"]])
            t["verdict"] = PASS if want in labels[t["id"]] else FAIL
    report["summary"] = summarize(report["tests"])
    path.write_text(json.dumps(report, indent=1, default=str))
    return report["summary"]


async def run(iteration: int, n_tests: int, seed: Optional[int]) -> dict:
    it = Iteration(iteration, n_tests, seed)
    print(f"iteration {iteration} (seed {it.seed}): running Plum", flush=True)
    try:
        await it.run_plum()
        print("running tests", flush=True)
        await it.run_tests()
    finally:
        path = it.save()
        await it.svc.aclose()
    s = summarize(it.tests)
    print(f"wrote {path}")
    print(json.dumps(s, indent=1))
    return s


def main(iteration: int, n_tests: int = 200, seed: Optional[int] = None) -> int:
    asyncio.run(run(iteration, n_tests, seed))
    return 0


if __name__ == "__main__":
    if len(sys.argv) >= 4 and sys.argv[1] == "--judge":
        print(json.dumps(merge_judge(int(sys.argv[2]), Path(sys.argv[3])), indent=1))
    else:
        main(int(sys.argv[1]) if len(sys.argv) > 1 else 0)
