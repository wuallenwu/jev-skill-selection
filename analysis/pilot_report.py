"""Pilot report: pass rate, oracle gap, tokens, cost and time per run, and a projected cost for the full grid.

usage: uv run python analysis/pilot_report.py results/raw/pilot-n1-*.jsonl
"""
import json, statistics as st, sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from harness.sanity import latest_ok

# Full-grid runs per model (docs/experiments.md): 84 tasks x 3 runs
GRID = {"none/oracle": 2, "degraded (3 p x 2 sizes)": 6, "retrieval (3 selectors x 2 sizes)": 6, "jev (2 sizes)": 2}
RUNS_PER_CELL = 84 * 3

rows = [json.loads(l) for f in sys.argv[1:] for l in Path(f).read_text().splitlines() if l.strip()]
ok, errors = latest_ok(rows), [r for r in rows if r.get("status") == "error"]
cells = defaultdict(list)
for r in ok:
    cells[(r["agent_model"], r["condition"])].append(r)

print(f"{len(ok)} ok runs, {len(errors)} error rows\n")
print(f"{'model':<20}{'cond':<8}{'n':>4}{'pass':>7}{'tok_in':>10}{'cached':>8}{'tok_out':>9}{'$/run':>8}{'min/run':>9}")
for (m, c), rs in sorted(cells.items()):
    p = sum(r["passed"] for r in rs) / len(rs)
    tin = st.mean(r["agent_tokens_in"] for r in rs); tout = st.mean(r["agent_tokens_out"] for r in rs)
    cached = sum(r["agent_tokens_cached"] for r in rs) / max(1, sum(r["agent_tokens_in"] for r in rs))
    cost = st.mean(r["agent_cost_usd"] for r in rs); mins = st.mean((r.get("agent_sec") or 0) / 60 for r in rs)
    print(f"{m:<20}{c:<8}{len(rs):>4}{p:>7.2f}{tin:>10,.0f}{cached:>8.0%}{tout:>9,.0f}{cost:>8.3f}{mins:>9.1f}")

print("\nOracle gap and per-task pass rates")
for m in sorted({m for m, _ in cells}):
    if (m, "oracle") in cells and (m, "none") in cells:
        rate = lambda c: sum(r["passed"] for r in cells[(m, c)]) / len(cells[(m, c)])
        print(f"  {m}: oracle {rate('oracle'):.2f} - none {rate('none'):.2f} = gap {rate('oracle') - rate('none'):+.2f}")
        per = defaultdict(lambda: defaultdict(list))
        for c in ("none", "oracle"):
            for r in cells[(m, c)]:
                per[r["task_id"]][c].append(r["passed"])
        for t, v in sorted(per.items()):
            print(f"    {t:<40} none {sum(v['none'])}/{len(v['none'])}  oracle {sum(v['oracle'])}/{len(v['oracle'])}")

print("\nProjected full-grid agent cost per model (no caching discount; excludes full-list, see N4 pilot)")
for m in sorted({m for m, _ in cells}):
    rs = cells.get((m, "oracle"), []) + cells.get((m, "none"), [])
    if not rs:
        continue
    per_run = st.mean(r["agent_cost_usd"] for r in rs)
    total = sum(n * RUNS_PER_CELL for n in GRID.values()) * per_run
    hours = sum(n * RUNS_PER_CELL for n in GRID.values()) * st.mean((r.get("agent_sec") or 0) for r in rs) / 3600
    print(f"  {m}: {sum(n * RUNS_PER_CELL for n in GRID.values())} runs x ${per_run:.3f} = ${total:,.0f}; "
          f"{hours:,.0f} agent-hours (~{hours / 30:,.0f} h wall at 30 concurrent)")

if errors:
    print("\nErrors (latest per run_id may have been retried):")
    for r in errors[:10]:
        print(f"  {r['agent_model']} {r['condition']} {r['task_id']}: {(r.get('error') or '')[:160]}")
