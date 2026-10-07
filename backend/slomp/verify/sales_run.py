"""Verification of online stores' sales: 200 live tests (docs/DESIGN-online-stores.md, section 6).

    slomp verify --iteration 1 --plan sales
    python -m slomp.verify.sales_run --judge 1 labels.json      # merge the blind judge's answers

S-SRC source fidelity 50, S-END dates 30, S-STORE store 25, S-SHIP ships 20, S-MANY a sale 20 and S-IND industry 20
(the last three by a blind judge, given only the post), S-OFFER offer and code 20, S-QUAL quality 15. A test that
can't be made is recorded as inconclusive and replaced; a category that runs out of subjects hands its remaining
tests to S-SRC. Sales are the same for every city, so the searches are industry sets, read once at one moment.
"""
from __future__ import annotations

import asyncio
import json
import random
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from .. import industries as ind
from ..models import StoreSale
from ..sales import ONLINE_IDS, select
from ..service import SlompService
from . import sales_checks as sc
from .checks import FAIL, INCONCLUSIVE, PASS
from .runner import REPORTS, WORK, summarize

PLAN: list[tuple[str, int]] = [
    ("S-SRC source fidelity", 50), ("S-END dates", 30), ("S-STORE store", 25), ("S-SHIP ships (blind judge)", 20),
    ("S-MANY a sale (blind judge)", 20), ("S-IND industry (blind judge)", 20), ("S-OFFER offer and code", 20),
    ("S-QUAL quality", 15),
]
QUALITY = ("duplicates", "fresh", "order")


class SalesRun:
    def __init__(self, iteration: int, n_tests: int = 200, seed: Optional[int] = None):
        self.iteration = iteration
        self.seed = seed if seed is not None else 1000 * iteration + 13
        self.rng = random.Random(self.seed)
        self.scale = n_tests / 200
        self.svc = SlompService()
        self.run_id = f"sales{iteration:02d}-{datetime.now():%Y%m%d%H%M}"
        self.tests: list[dict] = []
        self.judge_items: list[dict] = []
        self.searches: list[tuple[list[str], list[StoreSale]]] = []
        self.now = datetime.now(timezone.utc)
        self.result = None

    # -- running Slomp like a user ------------------------------------------------------------------------------
    async def run_slomp(self) -> None:
        t = time.time()
        self.result = await self.svc.sales_result(use_cache=False)        # every source read now
        print(f"  {len(self.result.sales)} sales not ended, from {len(self.result.sources)} feeds "
              f"({time.time() - t:.0f}s)", flush=True)
        inds = list(ONLINE_IDS)
        self.rng.shuffle(inds)
        # each industry alone, then a few mixes, as people search
        queries = [[i] for i in inds] + [sorted(self.rng.sample(inds, k)) for k in (2, 3, 3, 4)]
        for q in queries:
            shown, _ = select(self.result, q, self.now)
            self.searches.append((q, shown))
            print(f"  {','.join(q)}: {len(shown)} sales at {len({s.store or s.store_name for s in shown})} stores",
                  flush=True)

    # -- subjects -----------------------------------------------------------------------------------------------
    def subjects(self, want: Callable[[StoreSale], bool] = lambda s: True) -> list[tuple[str, StoreSale]]:
        """Sales spread across the searches: round-robin over them, random within each, each sale once."""
        per = []
        for q, shown in self.searches:
            xs = [(q, s) for s in shown if want(s)]
            self.rng.shuffle(xs)
            per.append(xs)
        out, seen = [], set()
        while any(per):
            for lst in per:
                if lst:
                    q, s = lst.pop()
                    if s.id not in seen:
                        seen.add(s.id)
                        out.append((q, s))
        return out

    async def run_category(self, name: str, quota: int, subjects: list, test: Callable) -> int:
        done = 0
        for subj in subjects:
            if done >= quota:
                break
            try:
                verdict, detail, label = await test(subj)
            except Exception as e:                       # a crash is the harness's problem: record it
                verdict, detail, label = INCONCLUSIVE, {"why": f"test error: {type(e).__name__}: {e}"}, "?"
            self.tests.append({"id": f"{name.split()[0]}-{len(self.tests):03d}", "category": name, "subject": label,
                               "verdict": verdict, "detail": detail})
            done += verdict != INCONCLUSIVE
        return max(0, quota - done)

    # -- the tests ----------------------------------------------------------------------------------------------
    async def run_tests(self) -> None:
        http = self.svc.http
        q = {name: max(1, round(n * self.scale)) for name, n in PLAN}
        L = lambda s: f"{s.store_name}: {s.title[:80]} [{s.source}]"         # noqa: E731

        async def end(x):
            _, s = x
            v, det = await sc.sale_dates(http, s, self.now)
            return v, det, L(s)

        async def store(x):
            _, s = x
            v, det = await sc.sale_store(http, s)
            return v, det, L(s)

        async def offer(x):
            _, s = x
            v, det = sc.sale_offer(s)
            return v, det, L(s)

        async def src(x):
            _, s = x
            v, det = await sc.sale_source(http, s)
            return v, det, L(s)

        # Half the date tests go to sales whose end comes from the post's words: that is where the reading is.
        worded = self.subjects(lambda s: s.ends_how.startswith("the post says"))
        half = q["S-END dates"] // 2
        short = await self.run_category("S-END dates", half, worded, end)
        short += await self.run_category("S-END dates", q["S-END dates"] - half,
                                         self.subjects(lambda s: not s.ends_how.startswith("the post says")), end)
        short += await self.run_category("S-STORE store", q["S-STORE store"], self.subjects(), store)
        coded = self.subjects(lambda s: bool(s.code))
        short += await self.run_category("S-OFFER offer and code", q["S-OFFER offer and code"],
                                         coded[:q["S-OFFER offer and code"] // 2] + self.subjects(), offer)
        short += self.judge("S-SHIP ships (blind judge)", "ships", q["S-SHIP ships (blind judge)"])
        short += self.judge("S-MANY a sale (blind judge)", "many", q["S-MANY a sale (blind judge)"])
        short += self.judge("S-IND industry (blind judge)", "industry", q["S-IND industry (blind judge)"])
        short += self.quality(q["S-QUAL quality"])
        await self.run_category("S-SRC source fidelity", q["S-SRC source fidelity"] + short, self.subjects(), src)

    def judge(self, name: str, kind: str, quota: int) -> int:
        picked = 0
        for search, s in self.subjects():
            if picked >= quota:
                break
            tid = f"{name.split()[0]}-{len(self.tests):03d}"
            self.tests.append({"id": tid, "category": name, "verdict": "pending",
                               "subject": f"{s.store_name}: {s.title[:80]} [{s.source}]",
                               "detail": {"shown_under": [i for i in search if i in s.industries],
                                          "slomp_industries": s.industries, "sale": s.id}})
            item = {"qid": tid, "kind": kind, "title": s.title, "text": s.raw.get("text", "")[:500]}
            if kind == "ships":
                item["store"] = s.store_name
            self.judge_items.append(item)
            picked += 1
        return max(0, quota - picked)

    def quality(self, quota: int) -> int:
        picked = 0
        for q, shown in self.searches:
            for what in QUALITY:
                if picked >= quota:
                    return 0
                v, det = sc.quality(shown, self.now, what)
                self.tests.append({"id": f"S-QUAL-{len(self.tests):03d}", "category": "S-QUAL quality",
                                   "subject": f"{','.join(q)}: {what}", "verdict": v, "detail": det})
                picked += 1
        return max(0, quota - picked)

    # -- reporting ----------------------------------------------------------------------------------------------
    def save(self) -> Path:
        REPORTS.mkdir(parents=True, exist_ok=True)
        WORK.mkdir(parents=True, exist_ok=True)
        res = self.result
        every = res.sales if res else []
        report = {"plan": "sales", "iteration": self.iteration, "seed": self.seed, "run_id": self.run_id,
                  "run_at": self.now.isoformat(),
                  "slomp": {"sales": len(every), "stores": len({s.store or s.store_name for s in every}),
                            "by_source": dict(Counter(s.source for s in every)),
                            "with_a_code": sum(bool(s.code) for s in every),
                            "with_an_end": sum(bool(s.ends_at) for s in every),
                            "left_out": dict(res.excluded.most_common()) if res else {},
                            "feeds_failing": [x["name"] for x in (res.sources if res else []) if not x["ok"]],
                            "searches": [{"industries": q, "sales": len(shown),
                                          "stores": len({s.store or s.store_name for s in shown})}
                                         for q, shown in self.searches]},
                  "tests": self.tests, "summary": summarize(self.tests)}
        path = REPORTS / f"sales-{self.iteration:02d}.json"
        path.write_text(json.dumps(report, indent=1, default=str))
        (WORK / f"sales-{self.iteration:02d}-judge-packet.json").write_text(json.dumps(
            {"industries": [{"id": i.id, "name": i.name, "description": i.description} for i in ind.INDUSTRIES
                            if i.online], "items": self.judge_items}, indent=1))
        return path


def merge_judge(iteration: int, labels_path: Path) -> dict:
    """S-SHIP and S-MANY pass on the judge's yes; S-IND when the industry Slomp showed the sale under is among the
    judge's. "Unsure" is inconclusive."""
    path = REPORTS / f"sales-{iteration:02d}.json"
    report = json.loads(path.read_text())
    labels = {x["qid"]: x for x in json.loads(labels_path.read_text())["labels"]}
    for t in report["tests"]:
        got = labels.get(t["id"])
        if t["verdict"] != "pending" or not got:
            continue
        t["detail"]["judge"] = got
        if t["id"].startswith("S-IND"):
            judged = sorted(got.get("industries") or [])
            t["verdict"] = PASS if set(t["detail"]["shown_under"]) & set(judged) else FAIL
        else:
            answer = str(got.get("answer", "")).lower()
            t["verdict"] = PASS if answer == "yes" else FAIL if answer == "no" else INCONCLUSIVE
    report["summary"] = summarize(report["tests"])
    path.write_text(json.dumps(report, indent=1, default=str))
    return report["summary"]


async def run(iteration: int, n_tests: int, seed: Optional[int]) -> dict:
    it = SalesRun(iteration, n_tests, seed)
    print(f"online stores' sales, run {iteration} (seed {it.seed}): running Slomp", flush=True)
    try:
        await it.run_slomp()
        print("running tests", flush=True)
        await it.run_tests()
    finally:
        path = it.save()
        await it.svc.aclose()
    s = summarize(it.tests)
    print(f"wrote {path}")
    print(f"judge packet: {WORK}/sales-{iteration:02d}-judge-packet.json (the prompt is in JUDGE-SALES.md)")
    print(json.dumps(s, indent=1))
    return s


def main(iteration: int, n_tests: int = 200, seed: Optional[int] = None) -> int:
    asyncio.run(run(iteration, n_tests, seed))
    return 0


if __name__ == "__main__":
    if len(sys.argv) >= 4 and sys.argv[1] == "--judge":
        print(json.dumps(merge_judge(int(sys.argv[2]), Path(sys.argv[3])), indent=1))
    else:
        main(int(sys.argv[1]) if len(sys.argv) > 1 else 1)
