# jev-skill-selection

CMU 11-768 project: how much of a skill selector's accuracy turns into agent task success?
Benchmark: SkillsBench (via Harbor on Modal). Distractors: SkillFlow's SkillsMP library.

- `external/`: pinned submodules (skillsbench, skill-flow, harbor). `git submodule update --init`
- `docs/recon.md`: Phase 0 findings. `docs/decisions.md`: choices not covered by the spec.
- Secrets: `scripts/setup_keys.sh` (prompts, writes `.env` + Modal secret `jev-keys`), then `scripts/check_keys.sh` (free checks: keys valid, model IDs exist).
