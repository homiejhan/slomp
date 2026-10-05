"""Verification of regular deals: 200 live tests on searches in the Austin, Houston and Dallas areas.

    slomp verify --iteration 1 --plan regulars [--key answer-key.json]
    python -m slomp.verify.regulars_run --judge 1 labels.json      # merge the blind judge's answers
    python -m slomp.verify.regulars_run --audit                    # every deal near the three cities, not a sample
    python -m slomp.verify.regulars_run --audit-labels a.json b.json   # the cards a judge marked in an audit

R-SRC evidence fidelity 45, R-X other source 25, R-DAY schedule 30, R-GEO vicinity 30, R-IND industry 20 and R-TXT
faithful summary 20 (both by a blind judge), R-REC recall 30 (against an answer key researched without sight of
Slomp's data). A test that can't be made is recorded as inconclusive and replaced; a category that runs out of
subjects hands its remaining tests to R-SRC.
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
from ..local import LocalResult
from ..models import LocalDeal
from ..reference import city
from ..service import SlompService
from . import regular_checks as rc
from .checks import FAIL, INCONCLUSIVE, PASS
from .runner import REPORTS, WORK, summarize

PLAN: list[tuple[str, int]] = [
    ("R-SRC evidence fidelity", 45), ("R-X other source", 25), ("R-DAY schedule", 30), ("R-GEO vicinity", 30),
    ("R-IND industry (blind judge)", 20), ("R-TXT faithful summary (blind judge)", 20), ("R-REC recall", 30),
]
AREAS = {
    "austin": ["austin", "round-rock", "cedar-park", "san-marcos", "georgetown", "pflugerville", "leander", "kyle"],
    "houston": ["houston", "sugar-land", "katy", "pasadena", "the-woodlands", "pearland", "spring", "league-city"],
    "dallas": ["dallas", "plano", "irving", "frisco", "arlington", "fort-worth", "garland", "mckinney"],
}
CORE = ["dining", "entertainment", "fashion", "home", "health", "grocery"]   # the main city: every industry with regular deals
SUBURB = ["dining", "entertainment"]
DEFAULT_KEY = WORK / "recall_key.json"
RECALL_MI = 50.0             # a metro is wider than one city's 25 miles: Fort Worth is 31 miles from Dallas


class RegularsRun:
    def __init__(self, iteration: int, n_tests: int = 200, seed: Optional[int] = None, key: Optional[Path] = None):
        self.iteration = iteration
        self.seed = seed if seed is not None else 1000 * iteration + 11
        self.rng = random.Random(self.seed)
        self.scale = n_tests / 200
        self.key = key or DEFAULT_KEY
        self.svc = SlompService()
        self.run_id = f"regulars{iteration:02d}-{datetime.now():%Y%m%d%H%M}"
        self.tests: list[dict] = []
        self.judge_items: list[dict] = []
        self.local: list[LocalResult] = []
        self.area: dict[str, str] = {}
        self.queries: list[tuple[str, list[str], float]] = []
        self.statewide: dict = {}
        self.now = datetime.now(timezone.utc)

    # -- running Slomp like a user ------------------------------------------------------------------------------
    async def run_slomp(self) -> None:
        t = time.time()
        rset = await self.svc.regulars.all(refresh=True)              # read every page now, not from the cache
        self.statewide = {"regular_deals": len(rset.regulars), "by_status": dict(Counter(r.status for r in rset.regulars)),
                          "by_origin": dict(Counter(r.origin for r in rset.regulars)),
                          "left_out": dict(rset.excluded.most_common()),
                          "sources_failing": [s["name"] for s in rset.sources if not s.get("ok", True)]}
        print(f"  {len(rset.regulars)} regular deals statewide {self.statewide['by_status']} ({time.time() - t:.0f}s)", flush=True)
        for area, ids in AREAS.items():
            suburbs = self.rng.sample(ids[1:], 3)
            for cid, inds, radius in [(ids[0], CORE, 25.0)] + list(zip(suburbs, [SUBURB] * 3, [25.0, 10.0, 50.0])):
                self.area[cid] = area
                self.queries.append((cid, inds, radius))
        for cid, inds, radius in self.queries:
            t = time.time()
            res = await self.svc.local(cid, inds, radius, use_cache=False)
            self.local.append(res)
            print(f"  {cid} {inds} {radius:g} mi: {len(res.regulars)} regular deals ({time.time() - t:.0f}s)", flush=True)

    # -- subjects -----------------------------------------------------------------------------------------------
    def subjects(self, unique: bool = True, want: Callable[[LocalDeal], bool] = lambda d: True) -> list[tuple[LocalResult, LocalDeal]]:
        """Regular deals spread across the searches: round-robin over cities, random within each. `unique` keeps
        one search per deal, since the same deal near two cities has the same evidence."""
        per_city = []
        for res in self.local:
            ds = [d for d in res.regulars if want(d)]
            self.rng.shuffle(ds)
            per_city.append([(res, d) for d in ds])
        out, seen = [], set()
        while any(per_city):
            for lst in per_city:
                if lst:
                    res, d = lst.pop()
                    if not unique or d.id not in seen:
                        seen.add(d.id)
                        out.append((res, d))
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
        L = lambda res, d: f"[{res.city.id}] {d.merchant}: {d.title[:64]} ({d.regular['status']})"     # noqa: E731

        async def cross(s):
            res, d = s
            v, det = await rc.regular_cross(http, d)
            return v, det, L(res, d)

        async def sched(s):
            res, d = s
            v, det = rc.regular_schedule(d, res)
            return v, det, L(res, d)

        async def geo(s):
            res, d = s
            v, det = await asyncio.to_thread(rc.regular_vicinity, d, res.city.lat, res.city.lon, res.radius_mi)
            return v, det, f"[{res.city.id}] {d.merchant}"

        async def src(s):
            res, d = s
            v, det = await rc.regular_source(http, d)
            return v, det, L(res, d)

        short = await self.run_category("R-X other source", q["R-X other source"], self.subjects(), cross)
        # Half the schedule tests go to deals with hours, an end date or a monthly rule: that is where the logic is.
        tricky = self.subjects(False, lambda d: bool(d.regular["time_text"] or d.regular["until"] or d.regular["monthly"]))
        half = q["R-DAY schedule"] // 2
        short += await self.run_category("R-DAY schedule", half, tricky, sched)
        short += await self.run_category("R-DAY schedule", q["R-DAY schedule"] - half, self.subjects(False), sched)
        seen, places = set(), []
        for res, d in self.subjects(False):
            if (res.city.id, d.merchant) not in seen:
                seen.add((res.city.id, d.merchant))
                places.append((res, d))
        short += await self.run_category("R-GEO vicinity", q["R-GEO vicinity"], places, geo)
        short += self.judge_industry(q["R-IND industry (blind judge)"])
        short += await self.judge_text(q["R-TXT faithful summary (blind judge)"])
        short += await self.recall(q["R-REC recall"])
        await self.run_category("R-SRC evidence fidelity", q["R-SRC evidence fidelity"] + short, self.subjects(), src)

    def judge_industry(self, quota: int) -> int:
        """Spread over the industries shown, so entertainment and retail are judged as well as dining."""
        by_ind: dict[str, list] = {}
        for res, d in self.subjects():
            shown = next(i for i in res.industries if i in d.industries)
            by_ind.setdefault(shown, []).append((res, d, shown))
        picked = 0
        while picked < quota and any(by_ind.values()):
            for shown in list(by_ind):
                if by_ind[shown] and picked < quota:
                    res, d, _ = by_ind[shown].pop()
                    tid = f"R-IND-{len(self.tests):03d}"
                    self.tests.append({"id": tid, "category": "R-IND industry (blind judge)", "verdict": "pending",
                                       "subject": f"[{res.city.id}] {d.merchant}: {d.title[:64]}",
                                       "detail": {"shown_under": shown, "slomp_industries": d.industries}})
                    self.judge_items.append({"qid": tid, "kind": "industry", "title": d.title, "store": d.merchant})
                    picked += 1
        return max(0, quota - picked)

    async def judge_text(self, quota: int) -> int:
        picked = 0
        for res, d in self.subjects():
            if picked >= quota:
                break
            passage = await rc.source_passage(self.svc.http, d)
            if len(passage) < 80:
                continue
            r = d.regular
            tid = f"R-TXT-{len(self.tests):03d}"
            card = {"place": d.merchant, "offer": d.title, "runs": " · ".join(x for x in (r["days_text"], r["time_text"]) if x),
                    "until": r["until"], "conditions": d.terms.conditions}
            self.tests.append({"id": tid, "category": "R-TXT faithful summary (blind judge)", "verdict": "pending",
                               "subject": f"[{res.city.id}] {d.merchant}: {d.title[:64]} ({r['status']})",
                               "detail": {"card": card, "source": rc.lead(d)["url"]}})
            self.judge_items.append({"qid": tid, "kind": "summary", "card": card, "source_text": passage})
            picked += 1
        return max(0, quota - picked)

    async def recall(self, quota: int) -> int:
        """Each metro's answer-key deals against that metro's main city, every industry, 50 miles."""
        if not self.key.exists():
            print(f"  no answer key at {self.key}: recall tests skipped", flush=True)
            return quota
        key = json.loads(self.key.read_text())
        by_metro: dict[str, list] = {}
        for item in key:
            by_metro.setdefault(item.get("metro", ""), []).append(item)
        for items in by_metro.values():
            self.rng.shuffle(items)
        found: dict[str, list[LocalDeal]] = {}
        held: dict[str, list[tuple]] = {}
        rset = await self.svc.regulars.all()
        for area, ids in AREAS.items():
            c = city(ids[0])
            res = next(r for r in self.local if r.city.id == c.id)
            found[area], _ = await self.svc.regulars.near(c, list(ind.IDS), RECALL_MI, res.window_start, res.window_end,
                                                          Counter())
            shown = {d.id for d in found[area]}
            held[area] = []
            for r in rset.regulars:               # known and in the metro, but with no date to show this week
                store = None if f"regular:{r.id}" in shown else self.svc.regulars.place(r, c)
                if store and store.distance_mi <= RECALL_MI:
                    held[area].append((r.brand, r.offer, set(r.schedule.days), r.schedule.monthly))
        done, today = 0, datetime.now().date()
        while done < quota and any(by_metro.get(a) for a in AREAS):
            for area in AREAS:
                if done >= quota or not by_metro.get(area):
                    continue
                item = by_metro[area].pop()
                v, det = rc.regular_recall(item, found[area], self.svc.regulars.venues, today, held[area])
                if v == FAIL and item.get("url") and await self.svc.http.turns_away_ai(item["url"]):
                    det["rule"] = "the page that states it turns away AI assistants; Slomp's registry does not use such pages"
                self.tests.append({"id": f"R-REC-{len(self.tests):03d}", "category": "R-REC recall", "verdict": v,
                                   "subject": f"[{AREAS[area][0]}] {item['brand']}: {str(item.get('offer', ''))[:64]}",
                                   "detail": det})
                done += v != INCONCLUSIVE
        return max(0, quota - done)

    # -- reporting ----------------------------------------------------------------------------------------------
    def save(self) -> Path:
        REPORTS.mkdir(parents=True, exist_ok=True)
        WORK.mkdir(parents=True, exist_ok=True)
        shown = [d for r in self.local for d in r.regulars]
        report = {"plan": "regulars", "iteration": self.iteration, "seed": self.seed, "run_id": self.run_id,
                  "run_at": self.now.isoformat(), "queries": self.queries,
                  "slomp": {"statewide": self.statewide,
                           "searches": [{"city": r.city.id, "area": self.area[r.city.id], "industries": r.industries,
                                         "radius_mi": r.radius_mi, "regulars": len(r.regulars),
                                         "by_status": dict(Counter(d.regular["status"] for d in r.regulars))}
                                        for r in self.local]},
                  "tests": self.tests, "summary": summarize(self.tests),
                  "quality": {"shown": len(shown), "distinct": len({d.id for d in shown}),
                              "confirmed_share": round(sum(d.regular["status"] == "confirmed" for d in shown) / max(1, len(shown)), 3),
                              "with_a_stated_discount": round(sum(bool(d.terms.pct) for d in shown) / max(1, len(shown)), 3)}}
        path = REPORTS / f"regulars-{self.iteration:02d}.json"
        path.write_text(json.dumps(report, indent=1, default=str))
        (WORK / f"regulars-{self.iteration:02d}-judge-packet.json").write_text(json.dumps(
            {"industries": [{"id": i.id, "name": i.name, "description": i.description} for i in ind.INDUSTRIES],
             "items": self.judge_items}, indent=1))
        return path


def merge_judge(iteration: int, labels_path: Path) -> dict:
    """Industry items pass when the industry Slomp showed the deal under is among the judge's; summary items pass
    when the judge found the card faithful to the source text."""
    path = REPORTS / f"regulars-{iteration:02d}.json"
    report = json.loads(path.read_text())
    labels = {x["qid"]: x for x in json.loads(labels_path.read_text())["labels"]}
    for t in report["tests"]:
        got = labels.get(t["id"])
        if t["verdict"] != "pending" or not got:
            continue
        if t["id"].startswith("R-IND"):
            t["detail"]["judge_industries"] = sorted(got.get("industries") or [])
            t["verdict"] = PASS if t["detail"]["shown_under"] in t["detail"]["judge_industries"] else FAIL
        else:
            t["detail"]["judge"] = {"faithful": got.get("faithful"), "problem": got.get("problem", "")}
            t["verdict"] = PASS if got.get("faithful") is True else FAIL if got.get("faithful") is False else INCONCLUSIVE
    report["summary"] = summarize(report["tests"])
    path.write_text(json.dumps(report, indent=1, default=str))
    return report["summary"]


AUDIT_PART = 90          # cards per judge packet: one judge reads about this many well


async def audit(radius_mi: float = 50.0) -> dict:
    """Every regular deal within `radius_mi` of the three main cities through the evidence, schedule and branch tests,
    and every card that cites a page into judge packets. A sample of 20 cannot say how often a card is wrong; this
    can. The first audit, after run 1, found 16 cards that left out a condition or a detail, and led to the finding
    that 1 mapped branch in 12 is no longer in its chain's own locator."""
    svc = SlompService()
    WORK.mkdir(parents=True, exist_ok=True)
    tally = {"R-SRC": Counter(), "R-DAY": Counter(), "R-GEO": Counter()}
    seen, items, index = set(), [], []
    try:
        await svc.regulars.all(refresh=True)
        for ids in AREAS.values():
            res = await svc.local(ids[0], CORE, radius_mi, use_cache=False)
            places = set()
            for d in res.regulars:
                where = f"[{res.city.id}] {d.merchant}: {d.title[:70]}"
                v, det = rc.regular_schedule(d, res)
                tally["R-DAY"][v] += 1
                if v == FAIL:
                    print(f"R-DAY fail {where} | {det.get('issues')}", flush=True)
                if d.merchant not in places:
                    places.add(d.merchant)
                    v, det = await asyncio.to_thread(rc.regular_vicinity, d, res.city.lat, res.city.lon, res.radius_mi)
                    tally["R-GEO"][v] += 1
                    if v == FAIL:
                        print(f"R-GEO fail {where} | {det.get('address')} | {det.get('why')}", flush=True)
                if d.id in seen:
                    continue
                seen.add(d.id)
                v, det = await rc.regular_source(svc.http, d)
                tally["R-SRC"][v] += 1
                if v == FAIL:
                    print(f"R-SRC fail {where} | {det.get('why')} | {det.get('url')}", flush=True)
                passage = await rc.source_passage(svc.http, d) if rc.lead(d) else ""
                if len(passage) >= 80:
                    r = d.regular
                    qid = f"A-{len(items):03d}"
                    card = {"place": d.merchant, "offer": d.title, "until": r["until"], "conditions": d.terms.conditions,
                            "runs": " · ".join(x for x in (r["days_text"], r["time_text"]) if x)}
                    items.append({"qid": qid, "kind": "summary", "card": card, "source_text": passage})
                    index.append({"qid": qid, "id": d.id, "status": r["status"], "url": rc.lead(d)["url"], "card": card})
    finally:
        await svc.aclose()
    inds = [{"id": i.id, "name": i.name, "description": i.description} for i in ind.INDUSTRIES]
    parts = [items[i:i + AUDIT_PART] for i in range(0, len(items), AUDIT_PART)]
    for n, part in enumerate(parts, 1):
        (WORK / f"regulars-audit-judge-packet-{n}.json").write_text(json.dumps({"industries": inds, "items": part}, indent=1))
    (WORK / "regulars-audit-index.json").write_text(json.dumps(index, indent=1))
    out = {"deals": len(seen), "judge_packets": len(parts), "cards_for_the_judge": len(items),
           **{k: dict(v) for k, v in tally.items()}}
    print(json.dumps(out, indent=1))
    print(f"judge packets: {WORK}/regulars-audit-judge-packet-N.json (the prompt is in JUDGE-REGULARS.md)")
    return out


def audit_labels(paths: list[Path]) -> int:
    """Print the cards a judge marked unfaithful in an audit, with what it said."""
    index = {x["qid"]: x for x in json.loads((WORK / "regulars-audit-index.json").read_text())}
    labels = [x for p in paths for x in json.loads(p.read_text())["labels"]]
    marked = [x for x in labels if x.get("faithful") is False]
    for x in marked:
        it = index.get(x["qid"], {})
        card = it.get("card", {})
        print(f"{x['qid']} [{it.get('status')}] {card.get('place')}: {str(card.get('offer'))[:90]}\n"
              f"    runs {card.get('runs')!r}, conditions {card.get('conditions')}\n    judge: {x.get('problem')}\n    {it.get('url')}")
    print(f"{len(labels)} cards judged, {len(marked)} marked")
    return 0


async def run(iteration: int, n_tests: int, seed: Optional[int], key: Optional[Path]) -> dict:
    it = RegularsRun(iteration, n_tests, seed, key)
    print(f"regular deals, run {iteration} (seed {it.seed}): running Slomp", flush=True)
    try:
        await it.run_slomp()
        print("running tests", flush=True)
        await it.run_tests()
    finally:
        path = it.save()
        await it.svc.aclose()
    s = summarize(it.tests)
    print(f"wrote {path}")
    print(json.dumps(s, indent=1))
    return s


def main(iteration: int, n_tests: int = 200, seed: Optional[int] = None, key: Optional[Path] = None) -> int:
    asyncio.run(run(iteration, n_tests, seed, key))
    return 0


if __name__ == "__main__":
    if len(sys.argv) >= 4 and sys.argv[1] == "--judge":
        print(json.dumps(merge_judge(int(sys.argv[2]), Path(sys.argv[3])), indent=1))
    elif len(sys.argv) >= 2 and sys.argv[1] == "--audit":
        asyncio.run(audit())
    elif len(sys.argv) >= 3 and sys.argv[1] == "--audit-labels":
        audit_labels([Path(p) for p in sys.argv[2:]])
    else:
        main(int(sys.argv[1]) if len(sys.argv) > 1 else 1)
