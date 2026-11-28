"""All poster numbers and figures from the grid results. Re-run any time; reads only committed files.

usage: uv run --with matplotlib --with numpy python analysis/make_all.py [results/grid/*.jsonl ...]
writes: results/summary.csv, results/summary.md, results/figs/fig{1,2,3}_*.png, results/recall_buckets.csv

Stats: a cell's pass rate = mean over tasks of the per-task pass rate (runs averaged within task), so every task
weighs the same. 95% CIs: bootstrap over tasks (10k). Paired test vs no-skills: per-task difference, two-sided
sign-flip permutation test (10k).
"""
import collections, json, statistics, sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from harness.sanity import latest_ok  # noqa: E402

OUT, FIGS = ROOT / "results", ROOT / "results/figs"
RNG = np.random.default_rng(0)
B = 10_000
SELECTORS = ["jev", "embedding", "bm25", "skillret", "full-list"]
COLOR = dict(zip(SELECTORS, ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"]))  # validated, slots 1-5
LABEL = {"jev": "Jev", "embedding": "Qwen3-Emb", "bm25": "BM25", "skillret": "SKILLRET", "full-list": "Full list"}
# label offsets (points) for the crowded 1K cluster in Fig 1
OFFSET = {("jev", "1k"): (14, 24), ("skillret", "1k"): (16, 6), ("embedding", "1k"): (-70, 20), ("bm25", "1k"): (8, -12),
          ("jev", "35k"): (8, -2), ("skillret", "35k"): (-72, -8), ("embedding", "35k"): (-82, 10), ("bm25", "35k"): (-58, -4)}
INK, INK2, MUTED, GRID, AXIS = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"


def load(paths):
    rows = latest_ok([json.loads(l) for p in paths for l in open(p) if l.strip()])
    # full-list runs whose prompt listed none of the library are not a valid full-list condition (docs/decisions.md)
    return [r for r in rows if not (r["condition"] == "full-list" and (r.get("skills_listed_n") or 0) == 0)]


def cell_key(r):
    return (r["condition"], r["library_size"])


def per_task(rows, field="passed"):
    acc = collections.defaultdict(list)
    for r in rows:
        if r.get(field) is not None:
            acc[r["task_id"]].append(float(r[field]))
    return {t: sum(v) / len(v) for t, v in acc.items()}


def boot_ci(vals):
    v = np.asarray(vals)
    means = v[RNG.integers(0, len(v), (B, len(v)))].mean(1)
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def paired(a: dict, b: dict):
    """Mean of a-b over shared tasks, its bootstrap CI, and a sign-flip permutation p-value."""
    ts = sorted(set(a) & set(b))
    d = np.array([a[t] - b[t] for t in ts])
    flips = RNG.choice([-1, 1], (B, len(d)))
    p = float((np.abs((flips * d).mean(1)) >= abs(d.mean()) - 1e-12).mean())
    return float(d.mean()), boot_ci(d), p, len(ts)


def main(paths):
    rows = load(paths)
    cells = collections.defaultdict(list)
    for r in rows:
        cells[cell_key(r)].append(r)
    none = per_task(cells[("none", "-")])
    oracle = per_task(cells[("oracle", "-")])
    gap = statistics.mean(oracle.values()) - statistics.mean(none.values())

    order = [("none", "-"), ("degraded-25", "1k"), ("degraded-50", "1k"), ("degraded-75", "1k"),
             ("degraded-25", "35k"), ("degraded-50", "35k"), ("degraded-75", "35k")] + \
            [(s, z) for z in ("1k", "35k") for s in SELECTORS if (s, z) in cells] + [("oracle", "-")]
    summary = []
    for key in order:
        rs = cells[key]
        pt = per_task(rs)
        rec_field = "recall_opened" if key[0] == "full-list" else "recall_selected"
        rec = [r[rec_field] for r in rs if r.get(rec_field) is not None]
        opened_any = [bool(r.get("skills_opened")) for r in rs] if key[0] != "none" else []
        cost = [(r.get("agent_cost_usd") or 0) + (r.get("selector_cost_usd") or 0) for r in rs]
        m = statistics.mean(pt.values())
        lo, hi = boot_ci(list(pt.values()))
        row = {"condition": key[0], "library": key[1], "n_runs": len(rs), "n_tasks": len(pt), "pass": m, "ci_lo": lo, "ci_hi": hi,
               "recall": statistics.mean(rec) if rec else (0.0 if key[0] == "none" else float("nan")),
               "opened_any": statistics.mean(opened_any) if opened_any else float("nan"),
               "cost_per_run": statistics.mean(cost), "gap_closed": (m - statistics.mean(none.values())) / gap}
        if key[0] != "none":
            row["d_vs_none"], (row["d_lo"], row["d_hi"]), row["p_vs_none"], _ = paired(pt, none)
        summary.append(row)

    cols = ["condition", "library", "n_runs", "n_tasks", "pass", "ci_lo", "ci_hi", "d_vs_none", "d_lo", "d_hi", "p_vs_none",
            "gap_closed", "recall", "opened_any", "cost_per_run"]
    with open(OUT / "summary.csv", "w") as f:
        f.write(",".join(cols) + "\n")
        for r in summary:
            f.write(",".join(f"{r[c]:.4f}" if isinstance(r.get(c), float) else str(r.get(c, "")) for c in cols) + "\n")
    md = ["| Condition | Library | Pass rate [95% CI] | Δ vs none [95% CI] | p | Gap closed | Recall@3 | Opened a skill | $/run |",
          "|---|---|---|---|---|---|---|---|---|"]
    for r in summary:
        d = f"{r['d_vs_none']:+.3f} [{r['d_lo']:+.3f}, {r['d_hi']:+.3f}]" if "d_vs_none" in r else "—"
        p = f"{r['p_vs_none']:.4f}" if "p_vs_none" in r else "—"
        md.append(f"| {LABEL.get(r['condition'], r['condition'])} | {r['library']} | {r['pass']:.3f} [{r['ci_lo']:.3f}, {r['ci_hi']:.3f}] | {d} | {p} "
                  f"| {r['gap_closed']:.0%} | {r['recall']:.2f} | {r['opened_any']:.0%} | {r['cost_per_run']:.3f} |".replace("nan%", "—").replace("| nan |", "| — |"))

    # Selector head-to-heads (paired over tasks) at each size
    md += ["", "Paired differences between selectors (row − column), pass rate:", ""]
    for z in ("1k", "35k"):
        sels = [s for s in SELECTORS if (s, z) in cells]
        pts = {s: per_task(cells[(s, z)]) for s in sels}
        for i, a in enumerate(sels):
            for b in sels[i + 1:]:
                d, (lo, hi), p, n = paired(pts[a], pts[b])
                md.append(f"- {z}: {LABEL[a]} − {LABEL[b]} = {d:+.3f} [{lo:+.3f}, {hi:+.3f}], p = {p:.3f} (n = {n} tasks)")

    # Does a run's own recall predict its pass? Selector + degraded runs, bucketed by recall_selected.
    sel_runs = [r for r in rows if r["condition"] in SELECTORS[:4] or r["condition"].startswith("degraded")]
    buckets = collections.defaultdict(list)
    for r in sel_runs:
        x = r["recall_selected"]
        buckets["0" if x == 0 else "(0, 0.5)" if x < 0.5 else "[0.5, 1)" if x < 1 else "1"].append(r["passed"])
    with open(OUT / "recall_buckets.csv", "w") as f:
        f.write("recall_bucket,n_runs,pass\n")
        for k in ("0", "(0, 0.5)", "[0.5, 1)", "1"):
            f.write(f"{k},{len(buckets[k])},{statistics.mean(buckets[k]):.4f}\n")
    md += ["", "Pass rate by the run's own recall of curated skills (selector + degraded runs):", ""]
    md += [f"- recall {k}: {statistics.mean(buckets[k]):.3f} (n = {len(buckets[k])})" for k in ("0", "(0, 0.5)", "[0.5, 1)", "1")]
    md += ["", f"Oracle − none gap: {gap:+.3f}. 'Gap closed' = (cell − none) / gap. Excluded: full-list runs with 0 skills listed."]
    (OUT / "summary.md").write_text("\n".join(md) + "\n")
    print("\n".join(md))
    figures(summary, rows)


def style(ax, xlabel, ylabel):
    ax.set_xlabel(xlabel, color=INK2)
    ax.set_ylabel(ylabel, color=INK2)
    ax.grid(True, color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(AXIS)
    ax.tick_params(colors=MUTED)


def figures(summary, rows):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    FIGS.mkdir(parents=True, exist_ok=True)
    by = {(r["condition"], r["library"]): r for r in summary}
    marker = {"1k": "o", "35k": "^"}

    # Fig 1: pass rate vs selection accuracy
    fig, ax = plt.subplots(figsize=(7, 4.6), dpi=200)
    for z, ls in (("1k", "-"), ("35k", "--")):
        pts = [by[("none", "-")]] + [by[(f"degraded-{p}", z)] for p in (25, 50, 75)] + [by[("oracle", "-")]]
        ax.plot([p["recall"] for p in pts], [p["pass"] for p in pts], ls, color=MUTED, linewidth=2, zorder=1,
                label=f"Degraded oracle ({z.upper()})")
    for key in (("none", "-"), ("oracle", "-")):
        r = by[key]
        ax.errorbar(r["recall"], r["pass"], yerr=[[r["pass"] - r["ci_lo"]], [r["ci_hi"] - r["pass"]]], fmt="s", ms=8,
                    color=INK2, ecolor=INK2, elinewidth=1, capsize=0, zorder=3)
        ax.annotate({"none": "No skills", "oracle": "Oracle"}[key[0]], (r["recall"], r["pass"]), xytext=(8, -4),
                    textcoords="offset points", color=INK, fontsize=9)
    for s in SELECTORS:
        for z in ("1k", "35k"):
            if (s, z) not in by:
                continue
            r = by[(s, z)]
            ax.errorbar(r["recall"], r["pass"], yerr=[[r["pass"] - r["ci_lo"]], [r["ci_hi"] - r["pass"]]], fmt=marker[z], ms=8,
                        color=COLOR[s], mec="#fcfcfb", mew=2, ecolor=COLOR[s], elinewidth=1, alpha=0.9, capsize=0, zorder=4)
            dx, dy = OFFSET.get((s, z), (7, 4))
            ax.annotate(f"{LABEL[s]} {z.upper()}", (r["recall"], r["pass"]), xytext=(dx, dy), textcoords="offset points",
                        color=INK2, fontsize=8, arrowprops=dict(arrowstyle="-", color=AXIS, lw=0.6) if abs(dx) + abs(dy) > 14 else None)
    for s in SELECTORS:
        ax.plot([], [], "s", color=COLOR[s], label=LABEL[s])
    ax.plot([], [], "o", color=INK2, label="1K library")
    ax.plot([], [], "^", color=INK2, label="35K library")
    style(ax, "Selection accuracy (recall of curated skills in the 3 given; full list: in those opened)", "Task pass rate")
    ax.set_xlim(-0.03, 1.08)
    ax.legend(frameon=False, fontsize=7, loc="lower right", labelcolor=INK2, ncol=2)
    ax.set_title("Pass rate vs. selection accuracy (DeepSeek V4 Flash, 84 tasks, 95% CI)", color=INK, fontsize=10, loc="left")
    fig.tight_layout()
    fig.savefig(FIGS / "fig1_accuracy_vs_pass.png", facecolor="#fcfcfb")

    # Fig 2: pass rate per method at 1K, cost per run labelled (all but full list cost ~the same)
    keys = [("none", "-"), ("full-list", "1k"), ("bm25", "1k"), ("skillret", "1k"), ("embedding", "1k"), ("jev", "1k"), ("oracle", "-")]
    keys = [k for k in keys if k in by]
    fig, ax = plt.subplots(figsize=(7, 3.8), dpi=200)
    for i, k in enumerate(keys):
        r = by[k]
        col = COLOR.get(k[0], INK2)
        ax.barh(i, r["pass"], height=0.6, color=col, edgecolor="#fcfcfb", linewidth=2)
        ax.plot([r["ci_lo"], r["ci_hi"]], [i, i], color=INK, linewidth=1)
        ax.text(r["ci_hi"] + 0.01, i, f"{r['pass']:.2f}   ${r['cost_per_run']:.3f}/run", va="center", fontsize=8, color=INK2)
    ax.set_yticks(range(len(keys)), [{"none": "No skills", "oracle": "Oracle"}.get(k[0], LABEL.get(k[0], k[0])) for k in keys],
                  fontsize=8, color=INK2)
    style(ax, "Task pass rate (95% CI), 1K library", "")
    ax.grid(axis="y", visible=False)
    ax.set_xlim(0, 0.85)
    ax.set_title("Pass rate and cost per run (agent + selector)", color=INK, fontsize=10, loc="left")
    fig.tight_layout()
    fig.savefig(FIGS / "fig2_cost_vs_pass.png", facecolor="#fcfcfb")

    # Fig 3: offline recall@3 by domain (cached selections; Jev = mean over its 3 draws)
    tasks = json.loads((ROOT / "data/tasks.json").read_text())
    keep = set((ROOT / "data/task_set.txt").read_text().split())
    domains = sorted({tasks[t]["domain"] for t in keep})
    cols = [(s, z) for z in ("1k", "35k") for s in ("jev", "embedding", "bm25", "skillret")]
    mat = np.zeros((len(domains), len(cols)))
    for j, (s, z) in enumerate(cols):
        top = json.loads((ROOT / f"data/selections/{s}_{z}.json").read_text())["top"]
        for i, d in enumerate(domains):
            ts = [t for t in keep if tasks[t]["domain"] == d]
            draws = (lambda t: top[t]) if s == "jev" else (lambda t: [top[t]])
            mat[i, j] = statistics.mean(statistics.mean(len(set(x[:3]) & set(tasks[t]["qrels"])) / len(tasks[t]["qrels"])
                                                        for x in draws(t)) for t in ts)
    fig, ax = plt.subplots(figsize=(7.5, 4.4), dpi=200)
    from matplotlib.colors import LinearSegmentedColormap
    cmap = LinearSegmentedColormap.from_list("blue", ["#cde2fb", "#86b6ef", "#3987e5", "#1c5cab", "#0d366b"])
    im = ax.imshow(mat, cmap=cmap, vmin=0, vmax=1, aspect="auto")
    for i in range(len(domains)):
        for j in range(len(cols)):
            ax.text(j, i, f"{mat[i, j]:.2f}", ha="center", va="center", fontsize=7, color="#ffffff" if mat[i, j] > 0.55 else INK)
    ax.set_xticks(range(len(cols)), [f"{LABEL[s]}\n{z.upper()}" for s, z in cols], fontsize=7, color=INK2)
    n = collections.Counter(tasks[t]["domain"] for t in keep)
    ax.set_yticks(range(len(domains)), [f"{d} ({n[d]})" for d in domains], fontsize=7, color=INK2)
    ax.axvline(3.5, color="#fcfcfb", linewidth=3)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.tick_params(length=0)
    fig.colorbar(im, ax=ax, fraction=0.03, pad=0.02).outline.set_visible(False)
    ax.set_title("Offline recall@3 by domain (task count in parentheses)", color=INK, fontsize=10, loc="left")
    fig.tight_layout()
    fig.savefig(FIGS / "fig3_recall_by_domain.png", facecolor="#fcfcfb")
    print(f"figures -> {FIGS}")


if __name__ == "__main__":
    main(sys.argv[1:] or sorted(str(p) for p in (ROOT / "results/grid").glob("*.jsonl")))
