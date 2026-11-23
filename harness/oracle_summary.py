"""Summarize an oracle sweep job dir: one row per task (pass / fail / error), written as TSV to stdout.

usage: uv run python harness/oracle_summary.py jobs/<job-name> > docs/oracle_sweep.tsv
"""
import json, sys
from pathlib import Path

rows = []
for f in sorted(Path(sys.argv[1]).glob("*/result.json")):
    d = json.loads(f.read_text())
    exc = d.get("exception_info")
    reward = ((d.get("verifier_result") or {}).get("rewards") or {}).get("reward")
    status = "error" if exc else ("pass" if reward == 1.0 else "fail")
    why = (exc or {}).get("exception_type", "") + ": " + (exc or {}).get("exception_message", "")[:200].replace("\n", " ") if exc else ""
    rows.append((d["task_name"].split("/")[-1], status, reward, why))
print("task\tstatus\treward\terror")
for r in rows:
    print(*r, sep="\t")
n = len(rows)
print(f"# {n} tasks: " + ", ".join(f"{s}={sum(r[1] == s for r in rows)}" for s in ("pass", "fail", "error")), file=sys.stderr)
