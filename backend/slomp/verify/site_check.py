"""Does the published site answer like the server? (docs/DESIGN-static-site.md, section 7)

    python -m slomp.verify.site_check --out site --cases 60 [--seed 7] [--report report.json]

Builds the site, then answers the same searches twice, from the same data at the same moment: with the server
(SlompService.local, .online and .sales) and with the page's engine (engine.js, run with Node).

  * A city that is its own anchor reads the same ads either way, so every part must match: the same deals in the same
    order, with the same stores, distances, dates, terms and scores; the same regular deals with the same next dates;
    the same promotions; the same online deals; the same online stores' sales.
  * Any other city: regular deals, promotions, online deals and sales must still match. The server reads the weekly ads for
    the city's own ZIP and the page uses its anchor's, so those are measured instead: the share of the server's deals
    the page also shows, and the share of the page's deals the server also shows.
  * The home page's biggest deals (SlompService.top, engine.top), which depend on no city: the same nine in the same
    order.

The build's inputs differ from one server search's in two ways that are not the engine's doing, so the server here is
given the build's: the fine print the build read (the leading deals for every anchor and radius, where a search reads
its own leading deals), and the item search results the build collected (a search returns at most ~150 items per
merchant, chosen differently by ZIP, so the build searches a merchant at several anchors). What those choices cost is
counted separately: the leading deals of each search whose fine print the build had not read, and the items a city's
own search returned that the build's searches had not.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import subprocess
import sys
import tempfile
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from .. import industries as ind
from .. import service as service_mod
from ..local import DETAIL_TOP_N, LocalDeals
from ..reference import cities
from ..service import RADII, SlompService
from ..site import ANCHOR_MI, ONLINE_LIMIT, anchors, build, nearest_anchor

NODE = r"""
const fs = require("fs"), path = require("path");
const [site, casesPath] = process.argv.slice(1);
const engine = require(path.join(site, "engine.js"));
engine.configure({loader: p => Promise.resolve(JSON.parse(fs.readFileSync(path.join(site, "data", p), "utf8")))});
(async () => {
  const out = [];
  for (const c of JSON.parse(fs.readFileSync(casesPath, "utf8"))) {
    try { out.push(await engine.search(c)); } catch (e) { out.push({error: String((e && e.stack) || e)}); }
  }
  process.stdout.write(JSON.stringify(out));
})();
"""
NODE_TOP = r"""
const fs = require("fs"), path = require("path");
const [site, now] = process.argv.slice(1);
const engine = require(path.join(site, "engine.js"));
engine.configure({loader: p => Promise.resolve(JSON.parse(fs.readFileSync(path.join(site, "data", p), "utf8")))});
engine.top({now}).then(r => process.stdout.write(JSON.stringify(r)),
                       e => process.stdout.write(JSON.stringify({error: String((e && e.stack) || e), deals: []})));
"""
BIG = ("houston", "san-antonio", "dallas", "austin", "fort-worth", "el-paso", "lubbock", "amarillo", "corpus-christi",
       "laredo", "brownsville", "tyler", "waco", "beaumont", "midland", "abilene", "wichita-falls", "san-angelo")
SKIP = {"brand", "industry_rule"}          # Flipp deals: not shown, not shipped


def plan(n: int, seed: int, anchor_ids: set[str]) -> list[dict]:
    """Half the searches in anchor cities (the big ones, then a few small ones), half in other cities, weighted by
    population; industries and radius at random."""
    rng = random.Random(seed)
    every = list(cities())
    small = [c.id for c in every if c.id in anchor_ids and c.id not in BIG]
    others = [c for c in every if c.id not in anchor_ids]
    picks = [c for c in BIG if c in anchor_ids] + rng.sample(small, 4)
    weights = [max(c.population or 0, 500) for c in others]
    while len(picks) < n:
        c = rng.choices(others, weights)[0].id
        if c not in picks:
            picks.append(c)
    rng.shuffle(picks)
    out = []
    for k, cid in enumerate(picks[:n]):
        inds = rng.sample(ind.IDS, rng.choice((1, 1, 2, 3)))
        if k % 4 == 0 and "dining" not in inds:
            inds.append("dining")                     # promotions and most regular deals
        out.append({"city": cid, "industries": ",".join(inds), "radius_mi": rng.choice(RADII), "limit": ONLINE_LIMIT})
    return out


def _t(iso: str) -> float:
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()


def diff_deal(a: dict, b: dict, where: str, out: list[str]) -> None:
    for k in sorted(set(a) | set(b)):
        if k in SKIP and str(a.get("id", "")).startswith("flipp:"):
            continue
        va, vb = a.get(k), b.get(k)
        if k in ("valid_from", "valid_to") and va and vb:
            if abs(_t(va) - _t(vb)) > 0.001:
                out.append(f"{where} {k}: server {va} page {vb}")
        elif va != vb:
            out.append(f"{where} {k}: server {json.dumps(va)[:160]} page {json.dumps(vb)[:160]}")


def _rank(d: dict) -> tuple:
    """What a list is sorted by. Deals that tie on all of it may come in either order (both sorts are stable, but the
    server sorts again after each round of fine print, from the order the previous round left)."""
    if d.get("regular"):
        return d["starts_in_days"], -d["score"], d["merchant"], d["title"]
    return -d.get("score", 0), d.get("ends_in_days"), -((d.get("terms") or {}).get("savings") or 0), d["title"]


def diff_list(sv: list[dict], pg: list[dict], where: str, out: list[str]) -> None:
    si, pi = [d["id"] for d in sv], [d["id"] for d in pg]
    if si != pi:
        missing, extra = [i for i in si if i not in pi], [i for i in pi if i not in si]
        ties = not missing and not extra and [_rank(d) for d in sv] == [_rank(d) for d in pg]
        if not ties:
            out.append(f"{where}: {len(si)} server vs {len(pi)} page; missing {missing[:5]} extra {extra[:5]}" +
                       ("" if missing or extra else " (same deals, different order)"))
    by = {d["id"]: d for d in pg}
    for d in sv:
        if d["id"] in by:
            diff_deal(d, by[d["id"]], f"{where} {d['id']}", out)


EXACT_EXCLUDED = ("other industry", "same item in another ad", "nearest store beyond", "no store within",
                  "regular deal", "promotion")


def compare(case: dict, server: dict, page: dict, anchor: bool) -> dict:
    out: list[str] = []
    if "error" in page:
        return {"ok": False, "problems": ["page error: " + page["error"][:400]]}
    sl, pl = server["local"], page["local"]
    for k in ("industries", "radius_mi", "counts" if anchor else "", "beyond_radius" if anchor else ""):
        if k and sl.get(k) != pl.get(k):
            out.append(f"local {k}: server {json.dumps(sl.get(k))[:200]} page {json.dumps(pl.get(k))[:200]}")
    if abs(_t(sl["window"]["start"]) - _t(pl["window"]["start"])) > 0.001 or \
            abs(_t(sl["window"]["end"]) - _t(pl["window"]["end"])) > 0.001:
        out.append(f"window: server {sl['window']} page {pl['window']}")
    flipp = lambda L: [d for d in L["deals"] + L["promotions"] + L["unconfirmed"] if d["id"].startswith("flipp:")]  # noqa
    if anchor:
        for part in ("deals", "promotions", "unconfirmed"):
            diff_list(sl[part], pl[part], part, out)
        for k, v in sl["excluded"].items():
            if k.startswith(EXACT_EXCLUDED) and pl["excluded"].get(k) != v:
                out.append(f"excluded {k!r}: server {v} page {pl['excluded'].get(k)}")
    else:
        diff_list([d for d in sl["promotions"] if d["id"].startswith("promo:")],
                  [d for d in pl["promotions"] if d["id"].startswith("promo:")], "promotions (restaurants)", out)
    diff_list(sl["regulars"], pl["regulars"], "regulars", out)
    so, po = server.get("online"), page.get("online")
    if (so is None) != (po is None):
        out.append(f"online: server {'none' if so is None else 'some'}, page {'none' if po is None else 'some'}")
    elif so:
        for i in so["deals"]:
            diff_list(so["deals"][i], po["deals"].get(i, []), f"online {i}", out)
    ss, ps = server.get("sales"), page.get("sales")
    if (ss is None) != (ps is None):
        out.append(f"sales: server {'none' if ss is None else 'some'}, page {'none' if ps is None else 'some'}")
    elif ss:
        if [d["id"] for d in ss["sales"]] != [d["id"] for d in ps["sales"]]:
            out.append(f"sales: {len(ss['sales'])} server vs {len(ps['sales'])} page (or a different order)")
        by = {d["id"]: d for d in ps["sales"]}
        for d in ss["sales"]:
            if d["id"] in by:
                diff_deal(d, by[d["id"]], f"sales {d['id']}", out)
        for k in ("counts", "excluded", "stores", "industries"):
            if ss.get(k) != ps.get(k):
                out.append(f"sales {k}: server {json.dumps(ss.get(k))[:160]} page {json.dumps(ps.get(k))[:160]}")
    sids, pids = {d["id"] for d in flipp(sl)}, {d["id"] for d in flipp(pl)}
    return {"ok": not out, "problems": out, "server_ads": len(sids), "page_ads": len(pids), "both": len(sids & pids)}


async def run(out_dir: Path, n: int, seed: int, report: Path | None, anchor_mi: float, as_is: bool = False) -> int:
    os.environ.setdefault("SLOMP_REGULARS", str(Path(tempfile.gettempdir()) / "slomp-site-check-no-regulars.json"))
    service_mod.RESULT_TTL_S = 10 ** 9           # online results stay as the build read them
    svc = SlompService()
    posts = await svc.promos.posts()             # the build and the server read the same deal posts
    svc.promos.posts = lambda: _ready(posts)
    now = datetime.now(timezone.utc)
    t0 = time.time()
    seen: dict = {}
    summary = await build(out_dir, now=now, anchor_mi=anchor_mi, svc=svc, log=lambda m: print(m, flush=True),
                          inspect=seen)
    print(f"built in {time.time() - t0:.0f}s: {summary}", flush=True)
    read = {int(d["id"]) for f in (out_dir / "data" / "ads").glob("*.json") if f.name != "index.json"
            for d in json.loads(f.read_text())["deals"] if d.get("detailed")}
    lead_unread: Counter = Counter()

    async def detail_pass(self, deals, wanted):
        """The server's pass reads the fine print of its leading deals. Here it reads exactly what the build read (from
        the cache), so both sides work from the same records, and counts the leading deals the build hadn't read."""
        for i in wanted:
            for d in [d for d in deals if i in d.industries][:DETAIL_TOP_N]:
                if not d.detailed and d.item_id not in read:
                    lead_unread[d.item_id] += 1
        todo = [d for d in deals if d.item_id in read and not d.detailed]
        await self.read_details(todo)
        return len(todo)
    if not as_is:
        LocalDeals._detail_pass = detail_pass

    # Flipp's item search returns at most ~150 items per merchant, and which ones differs from ZIP to ZIP; the build
    # searches a merchant at several anchors and keeps every item any search returned. The server here gets those
    # results for the merchants the build searched; the items its own search finds that the build's didn't are counted.
    built_hits, own_hits = seen["ads"].hits, LocalDeals._merchant_hits
    hits_missed: set = set()

    async def merchant_hits(self, zip_code, merchants, ads_of=None):
        own = await own_hits(self, zip_code, merchants, ads_of)
        for m in merchants:
            if m in built_hits:
                hits_missed.update((m, i) for i in own.get(m, {}).keys() - built_hits[m].keys())
        return {m: built_hits[m] if m in built_hits else own.get(m, {}) for m in merchants}
    if not as_is:
        LocalDeals._merchant_hits = merchant_hits

    anchor_list = anchors(anchor_mi)
    anchor_ids = {a.id for a in anchor_list}
    cases = plan(n, seed, anchor_ids)
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
        json.dump([{**c, "now": now.isoformat()} for c in cases], fh)
    proc = subprocess.run(["node", "-e", NODE, str(out_dir), fh.name], capture_output=True, text=True, check=True)
    pages = json.loads(proc.stdout)
    results, n_ok = [], 0
    for c, page in zip(cases, pages):
        is_anchor = c["city"] in anchor_ids
        online_inds = [i for i in c["industries"].split(",") if ind.BY_ID[i].online]
        loc = await svc.local(c["city"], c["industries"], c["radius_mi"], now=now)
        onl = await svc.online(",".join(online_inds), c["limit"]) if online_inds else None
        sal = await svc.sales(",".join(online_inds), now=now) if online_inds else None
        server = {"local": loc.to_dict(), "online": onl.to_dict() if onl else None, "sales": sal}
        r = compare(c, json.loads(json.dumps(server, default=str)), page, is_anchor and not as_is)
        city = next(x for x in cities() if x.id == c["city"])
        a, mi = nearest_anchor(city, anchor_list)
        r.update(case=c, anchor=is_anchor, anchor_city=a.id, anchor_mi=round(mi, 1))
        n_ok += r["ok"]
        results.append(r)
        share = f"ads: server {r.get('server_ads', 0)}, page {r.get('page_ads', 0)}, both {r.get('both', 0)}"
        print(f"{'ok  ' if r['ok'] else 'DIFF'} {c['city']:24s} {c['industries']:32s} {c['radius_mi']:>4g} mi "
              f"{'anchor' if is_anchor else 'via ' + a.id + f' ({mi:.0f} mi)'}  {share}", flush=True)
        for p in r["problems"][:6]:
            print("      " + p, flush=True)
    # The home page's biggest deals: the same nine, in the same order, from the build's file and from the server.
    proc = subprocess.run(["node", "-e", NODE_TOP, str(out_dir), now.isoformat()], capture_output=True, text=True,
                          check=True)
    page_top = json.loads(proc.stdout)
    server_top = json.loads(json.dumps(await svc.top(now, wait=True), default=str))
    top_ids = ([d["id"] for d in server_top["deals"]], [d["id"] for d in page_top["deals"]])
    top_ok = top_ids[0] == top_ids[1] and server_top["stores"] == page_top.get("stores")
    print(f"{'ok  ' if top_ok else 'DIFF'} home page: {len(top_ids[0])} biggest deals"
          + ("" if top_ok else f"; server {top_ids[0]}, page {top_ids[1]} {page_top.get('error', '')}"), flush=True)
    await svc.aclose()
    non = [r for r in results if not r["anchor"]]
    if as_is:
        anc = [r for r in results if r["anchor"]]
        a_s, a_p, a_b = (sum(r.get(k, 0) for r in anc) for k in ("server_ads", "page_ads", "both"))
        if a_s:
            print(f"Weekly ads in anchor cities, against the server as it is: the page shows {a_b / a_s:.1%} of the "
                  f"server's {a_s} deals; {a_b / max(a_p, 1):.1%} of the page's {a_p} are among them.")
    s_ads, p_ads, both = (sum(r.get(k, 0) for r in non) for k in ("server_ads", "page_ads", "both"))
    print(f"\n{n_ok}/{len(results)} searches match. Anchor cities: {sum(r['ok'] for r in results if r['anchor'])}/"
          f"{sum(r['anchor'] for r in results)}. Other cities (regulars, promotions, online, sales): "
          f"{sum(r['ok'] for r in non)}/{len(non)}.")
    if s_ads:
        print(f"Weekly ads in other cities: the page shows {both / s_ads:.1%} of the {s_ads} deals the server finds "
              f"from each city's own ZIP; {both / max(p_ads, 1):.1%} of the page's {p_ads} are among them.")
    if not as_is:                                 # counted only where the server is given the build's inputs
        print(f"Leading deals whose fine print the build hadn't read: {len(lead_unread)}")
        print(f"Items a city's own search returned that the build's searches hadn't: {len(hits_missed)}")
    if report:
        report.write_text(json.dumps({"now": now.isoformat(), "summary": summary, "results": results,
                                      "top": {"ok": top_ok, "server": top_ids[0], "page": top_ids[1]},
                                      "lead_unread": len(lead_unread), "hits_missed": sorted(hits_missed)},
                                     indent=1, default=str))
    return 0 if top_ok and all(r["ok"] for r in results if r["anchor"]) else 1


async def _ready(value):
    return value


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", type=Path, default=Path("site"))
    ap.add_argument("--cases", type=int, default=60)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--anchor-mi", type=float, default=ANCHOR_MI)
    ap.add_argument("--report", type=Path, default=None)
    ap.add_argument("--as-is", action="store_true",
                    help="the server as it is, with its own fine print and item searches: what a user would see differ")
    args = ap.parse_args()
    return asyncio.run(run(args.out.resolve(), args.cases, args.seed, args.report, args.anchor_mi, args.as_is))


if __name__ == "__main__":
    sys.exit(main())
