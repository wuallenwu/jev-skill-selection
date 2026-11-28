# To-do before the poster

Owner key: **A** = Allen, **T** = teammate, **C** = Claude session. Anyone can take an unowned item.

## Setup
- [ ] **A** Add the TypeSafe key: run `scripts/setup_keys.sh TYPESAFE_API_KEY` in a real terminal, then `scripts/check_keys.sh`. Ask TypeSafe about research credits.
- [ ] **T** `git clone --recurse-submodules`, `uv sync`, and run `uv run python -m pytest -q tests` (7 tests should pass). Modal access to the `dguo3` workspace is needed to launch runs.
- [ ] **A/T** Read `docs/decisions.md` and object to anything marked (proposed). Silence = accepted.

## Jev (independent of the agent runs; good teammate track)
- [ ] **T** J0: Jev probe script. One request; check limits, token counts, version. Read https://docs.typesafe.ai/cookbooks/skill_suggestion.md first.
- [ ] **T** J1: `selection/jev.py`. 1K chunking + final round; 35K over the embedding top-100. 3 independent draws per (task, size); log every request/response; write `data/selections/jev_{1k,35k}.json` as `{"top": {task: [d0, d1, d2]}, ...meta}` (the format `harness/conditions.py` expects), plus per-draw cost and model version.
- [ ] **T** J2: add Jev to the offline recall table, with the spread across draws.

## Agent runs (see `docs/experiments.md`)
- [ ] **C** N1 pilot (DeepSeek + Qwen, none/oracle, 10 tasks × 3) → pass rates, oracle gap, cost/run, projected full-grid cost. **Stop for approval.**
- [ ] **C** N2/N3/N4/J3 pilots.
- [ ] **A** Approve the full grid and the model plan after the pilot report.
- [ ] **C** Full runs in the order in `docs/experiments.md`; check SAIL + Modal bills after each.

## Loose ends
- [ ] **T** Audit ~30 random near-duplicate drops (the 0.8 similarity cutoff in `selection/offline_sweep.py`); report false positives/negatives.
- [x] **C** Restrict offline recall to the 84 tasks; add recall@k/min(k, |curated|) → `results/offline_recall_tasks84.csv`.
- [ ] **C** BM25 sanity check (name+description only; dups left in) to explain BM25 ≈ 2× SkillRouter's number.
- [ ] **A** Get the SkillFlow paper PDF from OpenReview (blocked for bots) for the comparison table.

## Analysis + poster
- [ ] **T/C** `analysis/make_all.py`: regenerates everything from `results/raw/*.jsonl`. Figs 1–3 + table with 95% bootstrap CIs over tasks + paired per-task tests vs no-skills.
- [ ] **T** Poster draft: question, setup diagram (library → selector → top-3 → agent on Modal), Figs 1–3, key findings (SKILLRET ≈ base embedder on task-instruction queries; Jev's 35K ceiling = 0.86 recall@100; full-list cost), limitations (one agent harness, 84 tasks, oracle-pass ≠ non-flaky).
