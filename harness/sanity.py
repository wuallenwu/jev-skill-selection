"""Automatic sanity checks over a results table. Exits non-zero (fails loudly) on any violation.

usage: uv run python harness/sanity.py results/<name>.jsonl [--allow-oracle-gap]
"""
import json, random, sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from harness import conditions as C
from harness.run import is_ok


def latest_ok(rows):
    """One row per run_id: the last non-error row (rows are append-only, retries add rows)."""
    by = {}
    for r in rows:
        if is_ok(r):
            by[r["run_id"]] = r
    return list(by.values())


def check(rows, require_oracle_gap=True) -> list[str]:
    errs, rows = [], latest_ok(rows)
    by_model = defaultdict(list)
    for r in rows:
        by_model[r["agent_model"]].append(r)
    for m, rs in by_model.items():
        cells = defaultdict(list)
        for r in rs:
            cells[(r["condition"], r["library_size"])].append(r)
        # 1. Oracle beats no-skills
        rate = lambda c: sum(r["passed"] for r in cells[c]) / len(cells[c])
        if require_oracle_gap and ("oracle", "-") in cells and ("none", "-") in cells and not rate(("oracle", "-")) > rate(("none", "-")):
            errs.append(f"{m}: oracle pass rate {rate(('oracle', '-')):.3f} <= no-skills {rate(('none', '-')):.3f}")
        # 2. Same task set in every condition
        sets = {c: frozenset(r["task_id"] for r in v) for c, v in cells.items()}
        if len(set(sets.values())) > 1:
            ref = max(sets.values(), key=len)
            errs += [f"{m} {c}: missing tasks {sorted(ref - s)[:5]}" for c, s in sets.items() if s != ref]
    # 3. Curated skills were actually in the container for oracle runs
    errs += [f"oracle run {r['run_id']} ({r['task_id']}): curated skills not listed to the agent" for r in rows
             if r["condition"] == "oracle" and r.get("curated_present") is not True]
    # 3b. Every skill we copied in was actually shown to the agent
    errs += [f"run {r['run_id']} ({r['condition']}, {r['task_id']}): {len(r['skills_unlisted'])} skills not listed, e.g. {r['skills_unlisted'][:3]}"
             for r in rows if r.get("skills_unlisted")]
    # 4. Replay 3 random deterministic-selector runs
    det = [r for r in rows if r["condition"] in C.DETERMINISTIC | {"degraded-25", "degraded-50", "degraded-75"}]
    for r in random.Random(0).sample(det, min(3, len(det))):
        again = C.select(r["condition"], r["task_id"], r["library_size"], r["run_idx"], r["seed"], r["k"])
        if again != r["skills_selected"]:
            errs.append(f"replay mismatch {r['run_id']}: {r['skills_selected']} != {again}")
    return errs


if __name__ == "__main__":
    rows = [json.loads(l) for l in Path(sys.argv[1]).read_text().splitlines() if l.strip()]
    errs = check(rows, require_oracle_gap="--allow-oracle-gap" not in sys.argv)
    print(f"{len(latest_ok(rows))} ok runs, {sum(r.get('status') == 'error' for r in rows)} error rows")
    for e in errs:
        print("FAIL:", e)
    sys.exit(1 if errs else 0)
