"""Convert SkillsBench (BenchFlow task.md format) tasks into Harbor tasks.

usage: python harness/convert_tasks.py [SRC_TASKS_DIR] [OUT_DIR]
defaults: external/skillsbench/tasks -> data/harbor_tasks
"""
import re, shutil, sys, tomllib
from pathlib import Path
import tomli_w, yaml

ROOT = Path(__file__).resolve().parents[1]
SKILLS_DIR = "/app/skills"  # where BenchFlow deploys skills; some tasks/oracles assume it

# Bare /verifier and /oracle path roots -> Harbor mounts. Leaves /logs/verifier alone.
PATH_RE = re.compile(r"(?<![\w./-])/(verifier|oracle)(?=[/\s\"');:]|$)", re.M)
MOUNT = {"verifier": "/tests", "oracle": "/solution"}

# Dockerfile fixes found by the Phase 0 Modal build sweep (docs/recon.md §10). Each must match exactly once.
DOCKERFILE_PATCHES = {
    # setuptools>=81 dropped pkg_resources, which seisbench imports
    "earthquake-phase-association": [('RUN pip install --no-cache-dir \\\n    "pandas==2.2.3"',
                                      'RUN pip install --no-cache-dir "setuptools<81" && pip install --no-cache-dir \\\n    "pandas==2.2.3"')],
    "seismic-phase-picking": [("RUN pip install --no-cache-dir seisbench==0.10.2 &&",
                               'RUN pip install --no-cache-dir "setuptools<81" seisbench==0.10.2 &&')],
    # Modal's builder can't set file capabilities (dumpcap from wireshark-cli)
    "suricata-custom-exfil": [("RUN dnf -y install \\", "RUN dnf -y --setopt=tsflags=nocaps install \\")],
}
SKILL_COPY_RE = re.compile(r"^COPY skills .*\n", re.M)  # baked-in skills would leak into no-skills runs


def convert(src: Path, out: Path) -> None:
    fm_text, body = src.joinpath("task.md").read_text().split("---\n", 2)[1:]
    fm = yaml.safe_load(fm_text)
    sb, ver, ag, orc = fm.get("sandbox", {}), fm.get("verifier", {}), fm.get("agent", {}), fm.get("oracle") or {}
    env = {k: sb[k] for k in ("build_timeout_sec", "os", "cpus", "memory_mb", "storage_mb", "gpus", "network_mode", "workdir") if k in sb}
    cfg = {
        "schema_version": "1.4",
        "task": {"name": f"skillsbench/{src.name}"},
        "metadata": fm.get("metadata", {}),
        "verifier": {k: ver[k] for k in ("timeout_sec", "env") if k in ver},
        "agent": {k: ag[k] for k in ("timeout_sec",) if k in ag},
        # trailing slash: Modal mounts volumes as symlinks and terminus-2's `find <skills_dir>` won't descend a symlink
        "environment": env | {"skills_dir": SKILLS_DIR + "/"},
        "solution": {"env": orc.get("env", {})},
    }
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(src / "environment", out / "environment", ignore=shutil.ignore_patterns("skills"))
    shutil.copytree(src / "verifier", out / "tests")
    shutil.copytree(src / "oracle", out / "solution")
    if (src / "environment/skills").is_dir():  # only the oracle agent sees solution/
        shutil.copytree(src / "environment/skills", out / "solution/skills")
    (out / "instruction.md").write_text(body.lstrip("\n"))
    (out / "task.toml").write_bytes(tomli_w.dumps(cfg).encode())

    for f in [*(out / "tests").rglob("*"), *(out / "solution").glob("*")]:
        if f.is_file() and f.suffix in ("", ".sh", ".py", ".toml", ".json", ".txt"):
            try:
                t = f.read_text()
            except UnicodeDecodeError:
                continue
            if PATH_RE.search(t):
                f.write_text(PATH_RE.sub(lambda m: MOUNT[m[1]], t))

    solve = out / "solution/solve.sh"
    lines = solve.read_text().split("\n", 1)
    prelude = f'mkdir -p {SKILLS_DIR} && cp -rn /solution/skills/. {SKILLS_DIR}/ 2>/dev/null || true\n'
    solve.write_text(lines[0] + "\n" + prelude + (lines[1] if len(lines) > 1 else "") if lines[0].startswith("#!") else prelude + solve.read_text())

    df = out / "environment/Dockerfile"
    d = SKILL_COPY_RE.sub("", df.read_text())
    for old, new in DOCKERFILE_PATCHES.get(src.name, []):
        assert d.count(old) == 1, f"{src.name}: patch target not found exactly once: {old!r}"
        d = d.replace(old, new)
    df.write_text(d)
    tomllib.loads((out / "task.toml").read_text())  # self-check: valid TOML


if __name__ == "__main__":
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "external/skillsbench/tasks"
    dst = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "data/harbor_tasks"
    tasks = sorted(p for p in src.iterdir() if (p / "task.md").exists())
    for t in tasks:
        convert(t, dst / t.name)
    print(f"converted {len(tasks)} tasks -> {dst}")
