# To-do before the poster

Split: **Allen = Jev**, **Friend = everything non-Jev** (agent runs, analysis, poster figures). **C** = Claude session (helps either).
Experiment IDs refer to `docs/experiments.md`.

## Shared setup
- [ ] Clone with `git clone --recurse-submodules`, `uv sync`, then `uv run python -m pytest -q tests` (9 pass). You need access to the Modal workspace `dguo3`. The SAIL key is already in the workspace secret `jev-keys`, so the friend **doesn't need their own key**. Every run spends the shared SAIL credit, so announce big runs first.
- [ ] Read `docs/decisions.md` and object to anything marked (proposed).
- [ ] Before and after each big run, check the bills: SAIL dashboard; `uv run modal billing report --for today --json` filtered to `jev-*`. The runner hard-stops at $450 per provider and $20 for Jev.

## Allen: Jev
- [x] TypeSafe key added.
- [x] **J0** Probe (jev-1.14.0; usage.input_tokens; most options get probability exactly 0, so ties are broken by stage-1 order): one request; confirm the 255-option and 32k-token limits, the `usage` token counts and the version string.
- [ ] **J1** `selection/jev.py` (pilot done: 10 tasks × 3 draws × both sizes, $0.10; full: `uv run python selection/jev.py run --size 1k --tasks all`, then `--size 35k`, ~$0.80): 1K chunking plus a final round; at 35K, rank the embedding top-100 (`data/selections/embedding_35k.json`). 3 independent draws per (task, size). Log every request and response. Write `data/selections/jev_{1k,35k}.json` as `{"top": {task: [d0, d1, d2]}, ...}` with per-draw cost and version.
- [ ] **J2** Jev offline recall (+ spread across draws), merged into `results/offline_recall_tasks84.csv`.
- [ ] **J3** Agent runs: `--conditions jev --library 1k,35k` once J1 exists (pilot on `--tasks pilot --runs 1` first).

## Daniel: keys (do first, ~2 min)
- [ ] Add your SAIL key and the Fireworks key to **your own** Modal secret, in a real terminal (hidden prompt):
  `SECRET=jev-keys-daniel scripts/setup_keys.sh SAIL2_API_KEY FIREWORKS_API_KEY`
  Use `SECRET=jev-keys-daniel`, never the default: the default replaces Allen's `jev-keys` secret, which wipes SAIL and TypeSafe.
  The runner loads both secrets, so `--model gemma-4-31b-sail2` (your SAIL) and `--model glm-5.3-fw` (Fireworks) just work.
- [ ] `scripts/check_keys.sh` (free) should print `SAIL2: key ok` and `Fireworks: key ok`.
- An agent (e.g. Claude Code) can do all of this from the repo. Point it at this file and `docs/experiments.md`. The only manual step is typing the keys into the prompt.

## Friend: non-Jev experiments (after Allen approves the full grid)
Launch: `uv run modal run --detach harness/run.py --model deepseek-v4-flash --conditions <...> --library <...> --tasks all --results <name>`.
Fetch the results and check them with `uv run python harness/sanity.py`; `analysis/pilot_report.py` gives pass rate, cost and time per cell.
- [ ] **Resume the pilots**: rerun the 3 pilot commands from `docs/experiments.md` with the same `--results` names. Only the errored runs get retried (~$1).
- [ ] **N1 full**: `--conditions none,oracle` (504 runs, ~$21).
- [ ] **N3 full**: `--conditions bm25,embedding,skillret --library 1k,35k` (1,512 runs, ~$64).
- [ ] **N2 full**: `--conditions degraded-25,degraded-50,degraded-75 --library 1k,35k` (1,512 runs, ~$64).
- [ ] **N4 full**: `--conditions full-list --library 1k` (252 runs, ~$45).
- [ ] **N6 large/small subset**: pick ~20–25 tasks where DeepSeek's oracle beats none; run GLM-5.3 (and Gemma 4 if approved) on `none,oracle` plus the top 2–3 selectors at 1K, 1 run each.
- [ ] **Error analysis**: failure modes by condition, using `skills_opened` / `skills_used` against `passed`, and timeouts per task. Pilot leads:
  - python-scala-translation times out under every condition.
  - organize-messy-files fails *with* skills: the agent nests the sorted folders inside the source dir.
- [ ] Audit ~30 random near-duplicate drops (the 0.8 cutoff in `selection/offline_sweep.py`).

## Friend: analysis + poster
- [ ] `analysis/make_all.py`: regenerates everything from `results/raw/*.jsonl` (use `harness.sanity.latest_ok` to dedupe retries).
  - Fig 1: pass rate vs. selection accuracy. Curve: none → degraded-25/50/75 → oracle. Selectors are points (recall_selected; full-list uses recall_opened).
  - Fig 2: total cost (agent + selector) vs. pass rate.
  - Fig 3: recall by domain, selectors × domains, with Jev highlighted (needs J2).
  - Table: pass rate and recall per condition, with 95% bootstrap CIs over tasks; paired per-task tests vs. no-skills.
- [ ] Poster draft. Findings so far:
  - SKILLRET ≈ the base embedder on task-instruction queries.
  - Jev's ceiling at 35K = 0.87 recall@100.
  - The full-list agent opens exactly the curated skills (pilot).
  - Oracle − none gap = +0.15 on the pilot.
  - Limitations: one agent harness, 84 tasks, oracle-pass ≠ non-flaky.

## Done
- [x] Recon, converter, oracle validation (84 tasks), libraries, offline recall (84 tasks, normalized), BM25 check, harness + tests, DeepSeek pilots N1–N4.
- [x] Small model: Qwen3.6 can't be used on SAIL (Flex-only). **Allen to decide**: Gemma 4 subset / Qwen on Fireworks / none.
