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
