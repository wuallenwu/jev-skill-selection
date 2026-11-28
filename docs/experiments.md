# Experiments

Each setting has a **pilot** (checks the wiring, measures real tokens and cost) and a **full** run. Pilots run on `data/pilot.txt` (10 tasks, seed 0); full runs on `data/task_set.txt` (84 oracle-valid tasks). Agent = terminus-2. k = 3 skills. Full runs use 3 runs per task.
Costs are estimates until the pilots report. Re-project before each full run, and check the real bills (SAIL dashboard, `modal billing report`, TypeSafe console).

Launch pattern (detached, resumable, append-only):
```
uv run modal run --detach harness/run.py --model <model> --conditions <c1,c2> --library <1k|35k|1k,35k> \
    --tasks <pilot|all> --runs <n> --results <name>
uv run modal volume get --force jev-jobs results/<name>.jsonl results/raw/
uv run python harness/sanity.py results/raw/<name>.jsonl
```
Models: `deepseek-v4-flash` (main), `qwen3.6-35b-a3b` (small; swap in `gemma-4-31b` if its oracle gap is tiny), `glm-5.3` (large, subset only).

## Non-Jev

| # | Setting | Conditions | Pilot | Full (per model) | Notes |
|---|---|---|---|---|---|
| N1 | Baselines | `none,oracle` | 10 tasks × 3 runs, DeepSeek **and** Qwen (120 runs) | 84 × 3 = 504 runs | Sets the oracle − none gap = the range selectors can move within. **Gate: approval before any full run.** |
| N2 | Degraded oracle | `degraded-25,degraded-50,degraded-75` × `1k,35k` | 10 tasks × 1 run × 1K (30 runs) | 84 × 3 × 6 = 1,512 runs | Traces the accuracy → pass-rate curve (Fig 1) |
| N3 | Retrieval selectors | `bm25,embedding,skillret` × `1k,35k` | 10 tasks × 1 run × 1K (30 runs) | 84 × 3 × 6 = 1,512 runs | Picks are cached and deterministic, so the 3 runs measure agent variance only |
| N4 | Full list in prompt | `full-list`, 1K only | 3 tasks × 1 run | 84 × 3 = 252 runs | ~144K prompt tokens/turn → about $0.30–0.40 per DeepSeek run, so **~$100 at full scale**. Decide from the pilot whether to run all 3 runs |
| N5 | Offline recall (no agent) | all retrieval selectors × both sizes, k = 1/3/5/10 (+100) | done (`results/offline_recall.csv`) | restrict to the 84 tasks; add recall@k/min(k,\|curated\|) | ~free (embeddings cached) |
| N6 | Large model subset | GLM-5.3: `none,oracle` + top 2–3 selectors at 1K | 5 tasks × 1 run | ~20–25 tasks × 1 run | Tasks = where DeepSeek's oracle clearly beats none. ~$70 |

## Jev

| # | Setting | Pilot | Full | Notes |
|---|---|---|---|---|
| J0 | API probe | 1 tiny request | n/a | Confirm limits (255 options, 32k tokens/question), the `usage` token counts and the `model` version string. Pin the version |
| J1 | Precompute draws | 10 tasks × 1K × 3 draws (~30 calls) | 84 tasks × {1K, 35K} × 3 draws ≈ 504 calls, ~$2–3 | 1K: chunk into ≤255-option questions under 32k tokens, then a final round. 35K: one question over the embedding top-100. Log every request and response. Cache to `data/selections/jev_{1k,35k}.json` as `{task: [draw0, draw1, draw2]}` |
| J2 | Jev offline recall | from the J1 pilot | from J1 full | Recall@1/3/5/10 per draw, plus the spread across draws (variance). Ceiling at 35K = embedding recall@100 (0.856) |
| J3 | Jev agent runs | 10 tasks × 1K × 3 runs (30 runs) | 84 × 3 × {1K, 35K} = 504 runs per model | Run index r uses draw r; draws are shared across agent models. Selector cost goes in `selector_cost_usd` |
| J4 | Jev on GLM subset | — | same tasks as N6, 1K, 1 run | Only if budget allows |

## Order

1. N1 pilot → report → **approval**
2. J0 → J1 pilot → J2 pilot (≤ $1). Can run alongside step 1.
3. N2 / N3 / N4 / J3 pilots (~100 runs, a few $)
4. Full runs for DeepSeek: N1 → N3 → N2 → J1 full → J3 → N4
5. Second model; then N6/J4 on the subset
6. Analysis (Figs 1–3, table, paired tests) from the results tables

Budget guard: the runner stops new trials at $450/provider and $20 Jev (`harness/config.yaml`). SAIL credit is $500.
