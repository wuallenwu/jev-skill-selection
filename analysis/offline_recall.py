"""Offline recall on the oracle-valid task set, from the per-task CSV. Adds recall normalized by min(k, |curated|)."""
import csv
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
tasks = set((ROOT / "data/task_set.txt").read_text().split())
acc = defaultdict(list)
for r in csv.DictReader(open(ROOT / "results/offline_recall_per_task.csv")):
    if r["task_id"] in tasks:
        k, n, rec = int(r["k"]), int(r["n_curated"]), float(r["recall"])
        acc[(r["selector"], r["library_size"], k)].append((rec, round(rec * n) / min(k, n)))  # recall is stored rounded; recover the hit count
out = ROOT / "results/offline_recall_tasks84.csv"
with open(out, "w") as f:
    f.write("selector,library_size,k,recall,recall_norm,n_tasks\n")
    for (s, size, k), v in sorted(acc.items()):
        assert all(0 <= b <= 1 + 1e-9 for _, b in v)
        f.write(f"{s},{size},{k},{sum(a for a, _ in v) / len(v):.4f},{sum(b for _, b in v) / len(v):.4f},{len(v)}\n")
print(out.read_text())
