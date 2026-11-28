# Decisions not covered by the spec

Each entry: decision — reason. Proposed ones are marked **(proposed)** until you confirm them at Phase 0 review.

## Repo
- External repos are git submodules under `external/`, pinned to the SHAs in `docs/recon.md` — reproducible versions without vendoring 2.9K files.
- The SkillsMP library (2.5 GB) is downloaded to `data/raw/` (gitignored), not committed.

## Benchmark
- **(proposed)** Task set = SkillsBench `tasks/` (87), minus SkillFlow's exclusions that are still in `tasks/`, minus tasks that fail to build on Modal. Re-check SkillFlow's 13 "Daytona sandbox error" exclusions on Modal instead of excluding them blindly. Never use `tasks-extra/`.
- **(proposed)** Convert tasks to Harbor format with our own script instead of using BenchFlow's `bench` CLI — the spec says Harbor, and Harbor has native skill injection.
- **(proposed)** Strip the skill COPY lines from `radar-vital-signs/environment/Dockerfile` during conversion, so the no-skills condition doesn't leak.
- Domain = `metadata.category` in the task frontmatter (8 values).

## Library
- **(proposed)** Remove every SkillsMP entry that duplicates a curated SkillsBench skill (same content hash as any curated SKILL.md, `github_url` pointing at skillsbench, or same dir name as a curated skill) before sampling distractors.
- **(proposed)** Skill ID = SkillsMP directory key (unique), not the frontmatter name (not unique). Curated skills get the ID `sb/<task>/<skill>`.
- **(proposed)** Use `index_deduped.json` (31,959) as the distractor pool so near-identical copies don't inflate the library. "35K" then means ~32K distractors plus 232 curated; report the actual count.

## Agent and providers
- **(proposed)** Agent = Harbor `terminus-2` for all models.
- **(proposed)** Provider per model: SAIL for Qwen3.6, DeepSeek V4 Flash and Gemma 4 (not serverless on Fireworks); Fireworks for GLM-5.3 (Kimi K3 isn't on SAIL); Baseten as the spare. Pin the dated IDs (e.g. `DeepSeek-V4-Flash-0731`).
- **(proposed)** Large model = GLM-5.3 (about 3× cheaper than Kimi K3 on Fireworks, and available on SAIL too).
- Cost computed from token counts × our own price table, because Harbor/LiteLLM cost is unreliable for non-LiteLLM providers.

## Selectors
- **(proposed)** Selector query = the task's `instruction.md` text.
- **(proposed)** Embedding/SKILLRET skill text = `"{name} | {description} | {SKILL.md body}"` (SKILLRET's eval format), truncated to 8192 tokens; SKILLRET query uses its skill-search instruction prefix explicitly.
- **(proposed)** Run Qwen3-Embedding-8B and SKILLRET-8B ourselves on a Modal GPU (SKILLRET isn't hosted anywhere; same infra keeps the two comparable).
- **(proposed)** Jev at 1K: chunk into ≤255-option Choices that fit within 32k tokens per question, then a final round over the chunk winners. Jev at 35K: one Choice over the embedding top-100. Rank by `probabilities`, take the top 3. Pin `jev-1.14.0`.
- Build check runs on Modal (`Image.from_dockerfile`), not local Docker — Apple Silicon needs amd64 emulation, which is slow and can fail for reasons Modal wouldn't. Workspace: the active `modal` profile.

## Budget
- Check the real bill after every paid step, not just estimates: Modal via `modal billing report --for today --json` filtered to our app names (the `dguo3` workspace is shared, so workspace totals include other people's apps); LLM providers via their usage dashboards/APIs plus our own token × price ledger. Phase 0 Modal build sweep: $0.26 (app `jev-build-check`).
- Hard stops: $450 per LLM provider (spec); SAIL credit is $500.

## Model plan (changes the spec; agreed 2026-11-21)
- Phase 3 pilot covers **both DeepSeek V4 Flash and Qwen3.6-35B-A3B** (10 tasks × no-skills/oracle × 3 runs each). The key metric is the oracle − no-skills gap (the range selectors can move within), alongside real tokens and cost per run.
- Full grid first on the model with the best gap per dollar (likely DeepSeek); second model if the budget allows. If Qwen's gap is tiny, swap in Gemma 4 31B. Nothing smaller than Qwen3.6: a model that can't use skills makes Fig 1 flat.
- **GLM-5.3 runs on a subset only:** ~20–25 tasks where the oracle clearly beats no-skills for the first model; 1 run; no-skills, oracle and the top 2–3 selectors at 1K. Estimated ~$70.
- Rough SAIL budget: pilots ~$10, DeepSeek grid ~$240, GLM subset ~$70, leaving ~$180 for Qwen/Gemma or reruns. Re-project from pilot token counts before Phase 4.

## Jev (agreed 2026-11-21)
- **Precompute and cache all Jev draws up front**: one independent draw per (task, library_size, run 1–3), about 480 calls (~$2–3). Each cache entry stores the full request/response, the reported model version, and a hash of the library. A stale hash fails loudly.
- The offline recall sweep and the agent runs use the same cached draws. Agent run *r* uses draw *r*.
- Draws are shared across agent models (paired comparison). One draw never serves more than one run index, so run-to-run variance is kept.
- Pin the Jev version for the whole cache (currently `jev-1.14.0`).
- Hard cap: **$20 total Jev spend**, tracked in the same ledger as the providers. Check actual usage against the TypeSafe console after the precompute.

## Harness (Phase 1)
- Converted tasks get `environment.skills_dir = "/app/skills"`, which is where BenchFlow deploys skills. Some tasks and oracle scripts assume that path (e.g. `civ6-adjacency-optimizer`, `dialogue-parser`, `pptx-reference-formatting`), so injected skills land there for every agent.
- Oracle validation needs the curated skills (several `solve.sh` scripts call skill scripts), but Harbor's oracle agent rejects `--skill`. So the converter copies the curated skills into `solution/skills/` and prepends one line to `solve.sh` that copies them to `/app/skills`. Harbor uploads `solution/` only for the oracle agent, so this can't leak into agent runs.
- The converter drops BenchFlow-only verifier fields (`type`, `service`, `hardening`, `pytest_plugins`) and `sandbox.bugswarm_image_tag`. The test scripts install their own pytest plugins.
- Converted tasks (`data/harbor_tasks/`, 522 MB) are gitignored. Regenerate them with `harness/convert_tasks.py`.
- Harbor runs inside a Modal function (detached), so long sweeps survive a laptop disconnect. Inside the container, an empty `~/.modal.toml` satisfies Harbor's auth preflight, and the container's own Modal credentials are used. We never copy a personal token into a workspace secret.
- Job outputs live in the Modal Volume `jev-jobs`. Fetch them with `modal volume get jev-jobs <job> jobs/` (`jobs/` is gitignored).
- **(proposed)** Task set = the 84 tasks whose oracle passes on Modal (83 clean, plus setup-fuzzing-py, whose verifier passes). This drops fix-build-agentops, reserves-at-risk-calc and fix-druid-loophole-cve. SkillFlow's exclusion list is replaced by this empirical check. It supersedes the earlier task-set proposal.
- Set Harbor's Modal app name to `jev-harbor` (`--ek app_name=jev-harbor`) so sandbox costs are attributable in `modal billing report`. Otherwise they bill under `__harbor__`.

## Library and offline selectors (Phase 2, 2026-11-23)
- Distractor pool = SkillsMP `index_deduped.json`, minus: entries whose SKILL.md matches a curated one by hash, `github_url` pointing at skillsbench, or directory name; **61 near-duplicates** (same frontmatter name as a curated skill and ≥0.8 difflib similarity on the first 5K normalized characters, e.g. `skillsmp/xlsx-8` = curated `xlsx`); and 2 skills with no SKILL.md. The SKILL.md filename is matched case-insensitively, because ~340 skills ship `skill.md`. Result: **31,869 distractors**. The 0.8 threshold was eyeballed and not audited by hand.
- Curated skills are deduplicated across tasks: identical or near-identical same-name copies collapse to one canonical ID, `sb/<first task alphabetically>/<dir>` (232 files → **199 curated skills**). Retrieving another task's copy of the same skill counts as a hit.
- Libraries: **1K = 199 curated + 801 distractors (seed 0)**; **35K = 32,068** (all curated + all distractors). ID lists and the pool hash are in `data/libraries/`.
- Query for every selector = the `task.md` body after the frontmatter.
- BM25: rank-bm25 Okapi with defaults; lowercase `\w+` tokens, no stemming; doc text `name | description | SKILL.md`.
- Embedders: sentence-transformers, bf16, max_seq 8192, normalized cosine, on one H100. The doc embeddings are computed once over the 35K library (the 1K library is a column subset) and cached in the `jev-data` Volume. Qwen3-Embedding uses its generic web-search instruction prefix; SKILLRET uses its skill-search prefix, passed explicitly.
- vLLM was dropped for embeddings (it broke with transformers 5 and crashed in its embedding scheduler). Pinned: sentence-transformers 6.3.0, transformers 5.24.0, torch 2.15.0.
- Recall@k = |top-k ∩ curated| / |curated|, so @3 can't reach 1 for tasks with more than 3 curated skills. **(proposed)** Also report recall@k / min(k, |curated|) in the analysis.
- Offline recall on the 84 oracle-valid tasks, with the normalized variant: `results/offline_recall_tasks84.csv` (`analysis/offline_recall.py`). Embedding recall@100 at 35K = 0.871, which is Jev's ceiling there.
- Cost: $7.33 on Modal (app `jev-offline-sweep`, including the throughput tests), under the $15 cap.

## Runner (Phase 1, 2026-11-27)
- One Harbor job per trial (one (task, condition, run)), driven from a generated job YAML. All of them run inside the detached Modal function `jev-runner.grid`, 32 at a time.
- `run_id` = hash of (model, condition, library size, seed, task, run index). no-skills and oracle use size "-", so they are shared across library sizes.
- Results go to the `jev-jobs` Volume at `results/<name>.jsonl`, append-only. Resume skips run_ids that already have a `status: ok` row. Errored runs are retried and get a new row, and analysis uses the last ok row per run_id.
- Agent cost = tokens × `harness/config.yaml` prices, not LiteLLM's numbers. The spend caps ($450 per provider, $20 Jev) are checked after every trial, and when one is hit the runner stops starting new trials. Up to 31 in-flight trials can overshoot.
- Skill copies are normalized before injection: uppercase `SKILL.md`, LF line endings, no BOM. If the frontmatter still doesn't parse, it is rewritten from the library index's name and description. terminus-2 otherwise **silently hides** skills with CRLF line endings, a lowercase `skill.md`, or broken frontmatter (found in the mock e2e: BM25 listed 2 of 3 skills).
- Oracle runs inject the task's own curated dirs unchanged, skipping non-skill dirs like the seismic tasks' `licenses/`. All 232 curated SKILL.md files parse.
- Full-list (1K): Harbor's per-trial skill upload breaks at 1K skills (a single exec over ARG_MAX), so the normalized 1K library is pre-built on the Volume `jev-lib1k` and mounted at `/app/skills`. The mount is read-write and shared (a shortcut): its tree hash is checked after every grid, and any change fails the grid. Tasks use `skills_dir = "/app/skills/"` with a trailing slash, because Modal mounts volumes as symlinks and `find` won't descend into a symlink.
- Full-list cost warning: the listing is ~144K prompt tokens per turn and takes ~2 min of sandbox time before the first turn. On DeepSeek without caching that is roughly $0.30–0.40 per run, so ~$100 for 252 runs. Measure in the pilot before committing.
- skills_opened = SKILL.md paths read in terminus-2 commands (`cat`/`head`/... on `/app/skills/<dir>/SKILL.md`). Running a skill's scripts is logged separately as skills_used. Recall for full-list uses skills_opened.
- Pilot task list: `data/pilot.txt`.
- Run status: only agent-behaviour exceptions (`AgentTimeoutError`, `ContextWindowExceededError`, `AgentSafetyRefusalError`, `NonZeroAgentExitCodeError`) count as a failed task outcome. Every other exception (provider 4xx/5xx, sandbox, cancellation) gives `status=error` and is retried. Found when Qwen's provider errors were logged as task failures.
- **Qwen3.6-35B-A3B can't be used on SAIL**: it is Flex-only, and Flex rejects synchronous requests (`supports: flex`). On Fireworks it would need a paid on-demand deployment. The spec's fallback, Gemma 4 31B, works on SAIL with sync requests, but at $0.40/$0.60 it is ~4× DeepSeek's price per run (≈ $0.22/run at the smoke run's token counts). **Small model choice is pending Allen's decision.**
- BM25 vs SkillRouter (R@10 0.32 on ~80K): our BM25 at 35K gets R@10 **0.64 over name|description|SKILL.md, but 0.42 over name+description only** (`analysis/bm25_check.py`). Indexing the full skill body accounts for most of the gap; SkillRouter's pool is 2.5× bigger. We keep the full-text BM25, since that is the stronger lexical baseline.
- The grid orchestrator is `nonpreemptible=True`. A Modal preemption during the N2/N3 pilot cancelled all in-flight trials, about $0.5 of wasted agent spend. Resume handled it: Modal restarted the function and retried only the runs without an ok row. Harbor's Modal sandboxes now get `sandbox_idle_timeout_secs=1800` and `sandbox_timeout_secs=4h`, because the default 24 h lifetime with no idle timeout lets orphans bill for a day.
- organize-messy-files fails under oracle (0/3) but passes with no skills (3/3). This is not a harness bug: the agent nests the sorted folders inside `/root/papers/all`, and 2 of the 3 oracle runs never opened a skill. Treat it as an agent-behaviour effect of having skills in the prompt and keep the task.

## Modal cost correction (2026-11-28)
- **Modal bills sandboxes at 3× the function rate**: $0.1419/core-h and $0.024/GiB-h (`modal billing rates`). My earlier "~$200 Modal for the grid" used function rates and was wrong.
- The pilots cost **$33.57 in `jev-harbor` sandboxes** for about 190 trials, including ~30 cancelled by preemption and the sandboxes they orphaned: ~$0.17/trial measured. From task requests (avg 2.0 cores, 4.1 GiB) and ~17–20 min/trial, a clean trial is **~$0.11–0.13**.
- Projected Modal sandbox cost of the full DeepSeek grid (4,284 runs): **~$460–550** (~$730 at the measured pilot rate). That is more than the SAIL agent cost (~$215). **The grid is on hold until Allen decides how to cover or cut it.**

## Full DeepSeek grid (2026-11-28)
- Ran as two spawned calls on the deployed `jev-runner` app (`--spawn`). `modal run --detach` grids died when the laptop slept at 22:22; they resumed with no lost rows.
- Final: 2,520/2,520 (none/oracle/embedding/jev/bm25/skillret) + 1,764/1,764 (degraded-25/50/75, full-list) completed rows. Modal ≈ $206 since the grid started; SAIL ≈ $244.
- **Full-list exclusion:** 9 of 252 full-list runs (drone-planning-control 3, fix-visual-stability 3, threejs-to-obj 2, jax-computing-basics 1) listed 0 of the 1,000 skills in the agent prompt. Cause not yet diagnosed (likely the 1,000-file listing step failing intermittently in those images). Excluded from full-list analysis (n = 243); every other condition has 0 runs with unlisted skills.
- bike-rebalance (no-network) needed tmux baked into its image; its first 6 errored rows were retried on the fixed image.
