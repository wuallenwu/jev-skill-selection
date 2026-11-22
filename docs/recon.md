# Phase 0 recon

Pinned versions (submodules in `external/`): SkillsBench `f860ecf` (2026-10-12), SkillFlow `6c2402d` (2026-09-24), Harbor `96c86af` (2026-11-20).
Paths below are relative to each repo.

## TL;DR / blockers

1. **Harbor cannot load SkillsBench tasks as-is.** SkillsBench v1.1 moved to the BenchFlow `task.md` format (frontmatter + `environment/`, `oracle/`, `verifier/`); Harbor wants `task.toml`, `instruction.md`, `tests/`, `solution/` (`harbor: src/harbor/models/task/paths.py:56-125`). `harbor tasks migrate` only handles Terminal-Bench. Phase 1 needs a ~50-line converter (frontmatter → `task.toml`, body → `instruction.md`, `verifier/`→`tests/`, `oracle/`→`solution/`, and rewrite the hard-coded `/verifier/` paths in all 87 `test.sh` to `/tests/`).
2. **The SkillsMP library contains SkillsBench's own curated skills.** 91 curated SKILL.md files are byte-identical in the corpus; 82 entries have `github_url` → `benchflow-ai/skillsbench`. These must be removed before sampling distractors, or "random distractor" can be a curated skill.
3. **DeepSeek V4 Flash and Qwen3.6-35B-A3B are not serverless on Fireworks** (on-demand deployment only). SAIL serves both serverless and cheaply → SAIL is the main provider for those.
4. **Jev caps a Choice at 255 options** → the 1K full library needs chunking; the 35K embedding top-100 shortlist fits in one request.

## 1. How skills get into task containers

- Layout: `tasks/<id>/environment/skills/<skill>/SKILL.md` (frontmatter `name`, `description`) + optional `scripts/`, `references/`, `assets/`. All 87 tasks have skills, 1–7 per task, 232 SKILL.md files, 196 distinct names.
- SkillsBench now injects at runtime (`bench eval create --skills-dir`); Dockerfiles say "do not COPY here". **Exception:** `radar-vital-signs/environment/Dockerfile:24-30` still COPYs skills into `~/.claude/skills`, `.codex`, `.agents`, etc. → must be stripped or the no-skills condition leaks. (`drone-planning-control` has it commented out.)
- **Harbor has native skill injection**, no Dockerfile changes needed: `--skill <dir>` (repeatable, `cli/jobs.py:770`) or `agents[].skills: [...]` in job YAML (`models/trial/config.py:101`). Each entry is a skill dir or a parent of skill dirs. At trial start Harbor uploads them to `/runtime/skills/<name>` (`trial/trial.py:1848`, default in `models/trial/paths.py:46`; overridable per task via `environment.skills_dir`). The agent must declare `capabilities.skills=True`.
- Skills are set per agent config, not per task → per-task skill sets (oracle, top-3) mean one Harbor job per (task, condition) or per group of tasks sharing a set. Fine for us: the runner already loops per task.
- Conditions map to: none = no `--skill`; oracle = `--skill tasks/<id>/environment/skills`; selector/degraded = a temp dir of the 3 chosen skill dirs.

## 2. Agent for open models over an OpenAI-compatible API

| Agent | Endpoint config | Native skills | Trajectory |
|---|---|---|---|
| **terminus-2** (pick) | LiteLLM; `--model openai/<id> --base-url ... --api-key-name ...` | yes: reads each SKILL.md frontmatter, appends `<available_skills>` (name, description, location) to first prompt (`agents/terminus_2.py:649-697`) | ATIF JSON |
| openhands-sdk | `LLM_API_KEY`/`LLM_BASE_URL` | yes, via `invoke_skill` tool | ATIF |
| mini-swe-agent | `MSWEA_API_KEY` | no | converted to ATIF |
| opencode / qwen-code | `OPENAI_*` | yes | ATIF |

**Pick terminus-2.** It runs open models through LiteLLM with nothing installed inside the container, and lists skills in an agent-neutral way. Its loop is just a bash tool, so behaviour is the same across models.

- Trajectory: `jobs/<job>/<trial>/agent/trajectory.json` (plus `trajectory.cont-N.json` after summarization). Schema `ATIF-v1.6`: `steps[].tool_calls[]{function_name:"bash_command", arguments.keystrokes}`, per-step `metrics{prompt_tokens, completion_tokens, cost_usd}`, `final_metrics{total_prompt_tokens, total_completion_tokens, total_cost_usd}`. Sample: `harbor: tests/golden/terminus_2/hello-world-timeout.trajectory.json`.
- **Parsing skills_opened:** regex over every `keystrokes` for paths under `/runtime/skills/<name>/`; count a skill opened when its `SKILL.md` is read (cat/head/less/sed/grep/python open). Also record files under it that were executed. Validate the regex on pilot trajectories.
- **Full-list (1K) risk:** terminus-2 builds `<available_skills>` with one `cat` exec per SKILL.md (`terminus_2.py:676`), so 1K skills means ~1K sequential Modal execs per trial, plus ~50–100K prompt tokens. Plan: generate the listing ourselves and pass it with `--extra-instruction-path`, with skills mounted at `/runtime/skills` so the agent can open them. Decide in Phase 1.

## 3. Modal via Harbor

- `src/harbor/environments/modal.py`; `-e modal` or `environment: {type: modal, kwargs: {...}}`. Auth: `~/.modal.toml` or `MODAL_TOKEN_ID/SECRET`.
- Builds with `Image.from_dockerfile(environment/)` (or `from_registry` if task sets `docker_image`); compose tasks go through DinD.
- Options: `secrets`, `volumes`, `region`, `sandbox_timeout_secs`, `sandbox_idle_timeout_secs`, CPU/mem limits honoured, GPU supported (forces network on). `network_mode` public/allowlist/none maps to Modal allowlists.

## 4. Tokens, cost, versions in Harbor output

- Per trial `result.json`: `agent_result.{n_input_tokens, n_cache_tokens, n_output_tokens, cost_usd}`, `agent_info.{name, version, model_info}`, `verifier_result.rewards`, timings, full config. Job dir has `lock.json` with the Harbor version.
- **Cost comes from LiteLLM's price map → likely 0/None for SAIL.** We compute cost ourselves from tokens × a price table in our config.
- Versions: record Harbor version and the submodule SHAs in each row.

## 5. Running

```
harbor run -p <converted_tasks> -a terminus-2 -m openai/<model> \
  --base-url <url> --api-key-name <ENV> -e modal -k 3 -n <conc> \
  --skill <dir> --include-task-name <id> [-c job.yaml]
```
YAML `JobConfig`: `jobs_dir, n_attempts, n_concurrent_trials, environment, agents[{name, model_name, base_url, model_api_key_name, skills, kwargs}], datasets[{path, task_names, exclude_task_names}]`.

## 6. Tasks and domains

- `tasks/`: 87 tasks; `tasks-extra/`: 14 that need credentials or don't fit the harness (excluded by SkillsBench by default).
- Domain = `metadata.category` in `task.md` (vocab in `taxonomy.yaml`): software-engineering 16; office-white-collar 14; natural-science 14; industrial-physical-systems 14; finance-economics 9; mathematics-or-formal-reasoning 8; cybersecurity 7; media-content-production 5.

## 7. SkillFlow: does it run as released?

- **Library:** not in the repo. `data/scripts/setup-data.sh` fetches a 963 MB Box zip (`curl -I` gives 404, but GET with `-L` works). Unzipped: `skills/skillsmp/<name>/SKILL.md`, 35,865 dirs (35,487 with a top-level SKILL.md), 2.5 GB. `skills/_metadata/index.json` (35,866 entries: name, description, github_url, content_hash, …), `index_deduped.json` (31,959), `duplicates.json` (469 groups).
- **Names are not unique**: dir keys are de-duplicated with `-N` suffixes; 25,465 distinct frontmatter names over 35,449 skills (`skill-creator` ×191). → Use dir key as skill ID, not frontmatter name.
- **Curated overlap:** see blocker 2.
- **Exclusion list:** `analysis/results/t12_generate_excluded_tasks.py` (`EXCLUDED_TASKS`), same 22 names in `benchmark/config/skillsbench/*/*.json`. 13 Daytona sandbox errors, 3 Docker build failures, 6 reproducibility issues (flaky Maven, CPU-timing, platform precision, vision API keys, …). **6 of the 22 have since moved to `tasks-extra/`**, so on the current 87 the list removes 16 → 71 tasks. Most "Daytona error" exclusions may not apply on Modal; see §9.
- **Harness:** a Harbor 0.1.43 wrapper on Daytona with Claude Code / Codex / Gemini CLI. Skills are injected by tarring into `/logs/agent/skills` (`skills/injector.py`). Not usable directly for terminus-2 + Modal + current Harbor; Harbor's native `--skill` replaces it. Its precomputed selector cache isn't shipped.
- **Reusable code:** `skill_flow/retriever/bm25.py` (rank-bm25, whitespace tokenizer), dense retriever (bge-base + FAISS), rerankers. We need Qwen3-Embedding-8B / SKILLRET, so only the BM25 bits and the corpus loader are worth reusing.
- **Runs?** `uv sync` OK. Tests: 923 pass if `test_qwen3_reranker.py` is deselected (it segfaults in the full run on macOS). `build-index` segfaults unless `OMP_NUM_THREADS=1 KMP_DUPLICATE_LIB_OK=TRUE` (torch/faiss OpenMP clash on macOS). Offline `search --no-rerank` works with no API key. The README's `from benchmark.agents import SkillAgent` is broken (ImportError).
- SkillFlow doesn't pin a SkillsBench commit. Its 87-task set differs from the current one.

## 8. Jev (TypeSafe)

- Package `typesafe-sdk` 0.7.5 (PyPI, import `typesafe_sdk`); `jev` 0.3.0 is an optional decorator layer. API `POST https://api.typesafe.ai/v1/systemone`, `Authorization: Bearer $TYPESAFE_API_KEY`.
- Request: `{model, state, questions:{id:{type:"choice", instructions, criteria:{option_name: description}}}}`. Response: `{model:"jev-1.14.0", answers:{id:{choice, confidence, probabilities:{opt:p}}}, usage:{input_tokens, output_tokens}}`.
- **No top-k:** take the top 3 by `probabilities`. The `model` field reports the exact version; log it and pin `jev-1.14.0` instead of `jev-latest`.
- **Limits:** 255 options per Choice; 64k tokens per request, 32k per question (state + one question); 262k with header `TypeSafe-Danger-Zone-Long-Context: true` (slower, less accurate); 32 MiB body; 400 `max_tokens_exceeded`; per-org rate limits visible only in the console. No per-option char limit documented.
- **No seed/temperature.** Determinism unverified; the docs warn about option-order bias. That fits the spec's "fresh selection per run".
- Price $0.042 / M input tokens, output free.
- Chunking plan, 1K: 1K options in chunks of ≤255 (4 Choices) → take the top few per chunk → a final Choice over the finalists. Token budget: ~1K names + descriptions ≈ 60–100K tokens total, so the chunks must also stay under 32k tokens each; may need ~8 chunks of ~125. 35K: a single Choice over the embedding top-100.
- TypeSafe has a skill-suggestion cookbook (rank, then re-check the top 3 with 700 chars of SKILL.md): https://docs.typesafe.ai/cookbooks/skill_suggestion.md.

## 9. Model IDs (verified from provider docs on 2026-11-21; not yet called)

| Role | Fireworks (`https://api.fireworks.ai/inference/v1`) | SAIL (`https://api.sailresearch.com/v1`) | Baseten (`https://inference.baseten.co/v1`) |
|---|---|---|---|
| small: Qwen3.6-35B-A3B | `accounts/fireworks/models/qwen3p6-35b-a3b` (**on-demand only**) | `Qwen/Qwen3.6-35B-A3B` (Flex tier only listed: $0.05/$0.40) | none |
| main: DeepSeek V4 Flash | `accounts/fireworks/models/deepseek-v4-flash` (**on-demand only**) | `deepseek-ai/DeepSeek-V4-Flash-0731` ($0.09/$0.18) | `deepseek-ai/DeepSeek-V4-Flash-0731` ($0.13/$0.26) |
| large: GLM-5.3 | `accounts/fireworks/models/glm-5p3` ($1.40/$4.40) | `zai-org/GLM-5.3` ($0.98/$3.08) | `zai-org/GLM-5.3` |
| large: Kimi K3 | `accounts/fireworks/models/kimi-k3` ($3.00/$15.00) | **no K3** (only `moonshotai/Kimi-K3.1-Pro`) | `moonshotai/Kimi-K3` |
| fallback: Gemma 4 31B | `accounts/fireworks/models/gemma-4-31b-it` (**on-demand only**) | `google/gemma-4-31B-it` ($0.40/$0.60) | none |
| embedder: Qwen3-Embedding-8B | `accounts/fireworks/models/qwen3-embedding-8b` ($0.10/M) | none | none |

Prices are $/M tokens in/out (SAIL ASAP tier). "SAIL" = Sail Research (commercial). SAIL context lengths were not checked. SAIL has a cheaper Flex tier that can queue up to 1 h.

**SKILLRET-Embedding-8B:** fine-tuned Qwen3-Embedding-8B, 4096-d, last-token pooling, cosine. The query prefix must be passed explicitly: `"Instruct: Given a skill search query, retrieve relevant skills that match the query\nQuery: "` (the repo's `prompt_name="query"` gives Qwen's generic web-search prompt). Docs have no prefix and use the format `"{name} | {description} | {skill_md}"` (`skillret/eval.py`). It is not served by any provider → run it ourselves (GPU on Modal), and embed with Qwen3-Embedding-8B on the same GPU for consistency.

## 10. Which tasks fail to build

Built on Modal with `Image.from_dockerfile` (the same path Harbor uses), 16 in parallel. Script: `scripts/recon/modal_build_tasks.py`; raw results: `docs/recon_builds.tsv`.

**84 / 87 build on Modal; 3 fail.** Slowest builds: lean4-proof 6.5 min, then adaptive-cruise-control, latex-formula-extraction and fix-druid-loophole-cve at about 6 min. Most take under 2 min.

| Task | Cause | Proposed fix (Phase 1, during conversion) |
|---|---|---|
| earthquake-phase-association | bit rot: unpinned setuptools ≥81 removed `pkg_resources`, which seisbench imports during the model-preload step | pin `setuptools<81` before the preload |
| seismic-phase-picking | same `pkg_resources` error (seisbench 0.10.2) | same |
| suricata-custom-exfil | Modal-specific: the builder can't set file capabilities (`cap_set_file failed` on `/usr/bin/dumpcap` from `wireshark-cli`) | `dnf --setopt=tsflags=nocaps install ...` (untested) |

So the seismic failures are not Modal-specific and would fail on any fresh build. SkillFlow's exclusion list already drops earthquake-phase-association ("Daytona error"); seismic-phase-picking and suricata-custom-exfil are new.

Not tested yet: whether each built image actually runs the oracle and passes its verifier. That is the first check in Phase 1 (oracle agent on Modal).

