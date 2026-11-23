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
