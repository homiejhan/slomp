"""Print a verification iteration's summary and every failing or inconclusive test, grouped by category.

    python scripts/triage.py 3 [--all]
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

REPORTS = Path(__file__).resolve().parents[2] / "docs" / "verification"


def main() -> None:
    n = int(sys.argv[1])
    show_all = "--all" in sys.argv
    r = json.loads((REPORTS / f"iteration-{n:02d}.json").read_text())
    s = r["summary"]
    print(f"iteration {n}: {s['pass']}/{s['conclusive']} passed ({s['pass_rate']}), {s['inconclusive']} inconclusive, "
          f"{s['pending']} pending")
    print("queries:", r["queries"])
    for cat, c in s["by_category"].items():
        print(f"  {cat:32s} pass {c['pass']:3d}  fail {c['fail']:3d}  inconclusive {c['inconclusive']:3d}  "
              f"pending {c['pending']:3d}  rate {c['pass_rate']}")
    why = Counter()
    for t in r["tests"]:
        if t["verdict"] == "inconclusive":
            why[(t["category"][:5], str(t["detail"].get("why", ""))[:70])] += 1
    print("\ninconclusive reasons:")
    for (cat, w), k in why.most_common(25):
        print(f"  {k:3d} {cat} {w}")
    print("\nfailures:")
    for t in r["tests"]:
        if t["verdict"] == "fail" or (show_all and t["verdict"] != "pass"):
            d = {k: v for k, v in t["detail"].items() if v not in (None, [], "")}
            print(f"- {t['id']} {t['subject'][:100]}\n    {json.dumps(d, default=str)[:600]}")


if __name__ == "__main__":
    main()
