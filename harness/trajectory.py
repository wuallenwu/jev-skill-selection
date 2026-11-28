"""Parse terminus-2 ATIF trajectories: which skills the agent was shown, and which it opened."""
import json, re
from pathlib import Path

SKILLS_DIR = "/app/skills"
_LOC = re.compile(r"<location>" + re.escape(SKILLS_DIR) + r"/([^/<]+)/SKILL\.md</location>")
# A skill counts as opened when a command reads its SKILL.md (cat/head/less/sed/grep/python open/...).
_OPEN = re.compile(re.escape(SKILLS_DIR) + r"/([^/\s'\"]+)/SKILL\.md")
_USED = re.compile(re.escape(SKILLS_DIR) + r"/([^/\s'\"]+)/(?!SKILL\.md)\S")  # scripts/references inside a skill


def _steps(agent_dir: Path):
    for f in sorted(agent_dir.glob("trajectory*.json")):
        if ".summarization-" in f.name:  # summarizer sub-trajectories, not the agent loop
            continue
        yield from json.loads(f.read_text()).get("steps", [])


def parse(agent_dir: Path) -> dict:
    listed, opened, used = [], [], []
    for s in _steps(agent_dir):
        if s.get("source") == "user" and not listed:
            listed = _LOC.findall(s.get("message") or "")
        for c in s.get("tool_calls") or []:
            keys = (c.get("arguments") or {}).get("keystrokes") or ""
            opened += [d for d in _OPEN.findall(keys) if d not in opened]
            used += [d for d in _USED.findall(keys) if d not in used]
    return {"skills_listed": listed, "skills_opened_dirs": opened, "skills_used_dirs": used}
