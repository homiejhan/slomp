"""Build slomp/data/branch_checks.json: mapped branches that the chain's own store locator no longer lists.

OpenStreetMap keeps a restaurant on the map long after it has closed. For chains whose own store locator is
republished by AllThePlaces (https://www.alltheplaces.xyz, CC-0), this compares the two: a mapped branch with no
locator branch within 0.75 miles is recorded as unlisted, and Slomp does not use it as "the nearest branch" for a
regular deal. A locator that looks incomplete (fewer branches near Texas than 80% of the mapped count: some scrapes
are partial) is not used at all.

    python scripts/build_branch_checks.py          # after scripts/build_stores.py
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from slomp.geo import miles  # noqa: E402
from slomp.sources import venues  # noqa: E402
from slomp.verify import atp  # noqa: E402
from slomp.verify.regular_checks import ATP_SPIDERS  # noqa: E402

NEAR_MI = 0.75
COMPLETE = 0.8


def main() -> None:
    chains, names = venues._chains(False)                  # every mapped branch, unlisted ones included
    out: dict[str, dict] = {}
    for name, spider in sorted(ATP_SPIDERS.items()):
        chain = venues.Venues().find(name)
        if not chain:
            continue
        chain = chains[chain.key]
        pts = atp._spider_points(spider)
        row = {"locator": spider, "mapped": len(chain.locations), "listed_near_texas": len(pts) if pts else 0}
        if not pts or len(pts) < COMPLETE * len(chain.locations):
            row["used"] = False                            # no data, or a partial scrape: nothing is concluded
        else:
            row["used"] = True
            row["unlisted"] = sorted(str(r[4]) for r in chain.locations
                                     if not any(miles(r[0], r[1], p[0], p[1]) <= NEAR_MI for p in pts))
        out[chain.name] = row
    runs = atp.recent_runs(3)
    doc = {"built": date.today().isoformat(),
           "source": "AllThePlaces (alltheplaces.xyz, CC-0), the chains' own store locators; runs " + ", ".join(runs),
           "about": "Mapped branches no locator branch is within 0.75 mi of (`unlisted`, by OpenStreetMap id). Slomp "
                    "does not show these as a deal's nearest branch. `used: false` means the locator data looked "
                    "incomplete and was ignored.",
           "chains": out}
    (ROOT / "slomp" / "data" / "branch_checks.json").write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
    used = {k: v for k, v in out.items() if v["used"]}
    print(f"{len(out)} chains with a locator; {len(used)} used; "
          f"{sum(len(v['unlisted']) for v in used.values())} of {sum(v['mapped'] for v in used.values())} mapped branches unlisted")
    print("not used:", ", ".join(f"{k} ({v['listed_near_texas']}/{v['mapped']})" for k, v in out.items() if not v["used"]))
    print("most unlisted:", ", ".join(f"{k} {len(v['unlisted'])}/{v['mapped']}" for k, v in
                                      sorted(used.items(), key=lambda kv: -len(kv[1]["unlisted"]))[:14]))


if __name__ == "__main__":
    main()
