"""Summarize every verification iteration: pass rates by iteration and by category, and quality metrics.

    python scripts/verification_summary.py
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

REPORTS = Path(__file__).resolve().parents[2] / "docs" / "verification"


def main() -> None:
    runs = sorted(REPORTS.glob("iteration-[0-9][0-9].json"))
    runs = [json.loads(p.read_text()) for p in runs if not p.name.endswith("-00.json")]
    runs = [r for r in runs if r["iteration"] >= 1]
    by_cat: dict[str, Counter] = defaultdict(Counter)
    print("| Iter | Passed | Rate | Inconclusive | Local | Online |")
    print("|---|---|---|---|---|---|")
    tot = Counter()
    for r in runs:
        s = r["summary"]
        local = sum(c["pass"] for k, c in s["by_category"].items() if k.startswith("L-"))
        local_n = sum(c["pass"] + c["fail"] for k, c in s["by_category"].items() if k.startswith("L-"))
        online = sum(c["pass"] for k, c in s["by_category"].items() if k.startswith("O-"))
        online_n = sum(c["pass"] + c["fail"] for k, c in s["by_category"].items() if k.startswith("O-"))
        print(f"| {r['iteration']} | {s['pass']}/{s['conclusive']} | {s['pass_rate']:.1%} | {s['inconclusive']} | "
              f"{local}/{local_n} | {online}/{online_n} |")
        tot.update({"pass": s["pass"], "conclusive": s["conclusive"], "inconclusive": s["inconclusive"]})
        for k, c in s["by_category"].items():
            by_cat[k].update({"pass": c["pass"], "fail": c["fail"], "inconclusive": c["inconclusive"]})
    print(f"| **All** | **{tot['pass']}/{tot['conclusive']}** | **{tot['pass'] / tot['conclusive']:.1%}** | "
          f"{tot['inconclusive']} | | |")
    print("\n| Category | Pass | Fail | Rate | Inconclusive |")
    print("|---|---|---|---|---|")
    for k, c in sorted(by_cat.items()):
        n = c["pass"] + c["fail"]
        print(f"| {k} | {c['pass']} | {c['fail']} | {c['pass'] / n:.1%} | {c['inconclusive']} |" if n else
              f"| {k} | 0 | 0 | n/a | {c['inconclusive']} |")
    print("\n| Iter | Local deals | Firm basis | Online deals | With identity | 2+ other sites | Store-checked | Flagged changed |")
    print("|---|---|---|---|---|---|---|---|")
    for r in runs:
        q = r.get("quality")
        if q:
            print(f"| {r['iteration']} | {q['local_deals']} | {q['local_firm_basis_share']:.0%} | {q['online_deals']} | "
                  f"{q['online_with_product_identity']} | {q['online_with_2plus_other_sites']} | {q['online_store_checked']} | "
                  f"{q['online_flagged_changed']} |")


if __name__ == "__main__":
    main()
