"""Which skills each run gets. Pure functions over the committed data/ files, so selections can be replayed.

Conditions: none | oracle | degraded-25 | degraded-50 | degraded-75 | full-list | bm25 | embedding | skillret | jev
"""
import json, random
from functools import cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
CONDITIONS = ["none", "oracle", "degraded-25", "degraded-50", "degraded-75", "full-list", "bm25", "embedding", "skillret", "jev"]
DETERMINISTIC = {"bm25", "embedding", "skillret"}  # same pick for every run -> replay check
SIZE_FREE = {"none", "oracle"}                     # don't depend on library size


@cache
def tasks() -> dict:
    return json.loads((DATA / "tasks.json").read_text())


@cache
def library(size: str) -> list[str]:
    return json.loads((DATA / f"libraries/{size}.json").read_text())["ids"]


@cache
def picks(selector: str, size: str) -> dict:
    p = DATA / f"selections/{selector}_{size}.json"
    if not p.exists():
        raise FileNotFoundError(f"{p} missing: run the {selector} selector first")
    return json.loads(p.read_text())["top"]


def curated(task: str) -> list[str]:
    return tasks()[task]["qrels"]


def select(condition: str, task: str, size: str, run_idx: int, seed: int, k: int = 3) -> list[str]:
    """Skill IDs for one run. run_idx is 0-based."""
    if condition == "none":
        return []
    if condition == "oracle":
        return curated(task)
    if condition == "full-list":
        assert size == "1k", "full-list only fits in context at 1K"
        return library(size)
    if condition.startswith("degraded-"):
        p = int(condition.split("-")[1]) / 100
        rng = random.Random(f"{seed}|{task}|{size}|{run_idx}|{condition}")
        cur = rng.sample(curated(task), len(curated(task)))
        pool = sorted(set(library(size)) - set(tasks_curated_all()))
        out = []
        for _ in range(k):  # each slot: curated w.p. p (without replacement), else a random distractor
            out.append(cur.pop() if cur and rng.random() < p else rng.choice([s for s in pool if s not in out]))
        return out
    if condition in DETERMINISTIC:
        return picks(condition, size)[task][:k]
    if condition == "jev":
        return picks("jev", size)[task][run_idx][:k]  # one independent cached draw per run index
    raise ValueError(f"unknown condition {condition!r}")


@cache
def tasks_curated_all() -> frozenset:
    return frozenset(s for t in tasks().values() for s in t["qrels"])


def skill_source(skill_id: str, task: str, lib_root: Path) -> Path:
    """Where a skill's directory lives. Curated skills come from the converted task dirs."""
    if skill_id.startswith("sb/"):
        _, t, d = skill_id.split("/", 2)
        return DATA / f"harbor_tasks/{t}/solution/skills/{d}"
    return lib_root / skill_id  # e.g. /data/skills/skillsmp/<name> on the jev-data volume


def skill_dirname(skill_id: str) -> str:
    return skill_id.replace("/", "__")


def recall(selected: list[str], task: str) -> float:
    q = set(curated(task))
    return len(set(selected) & q) / len(q)
