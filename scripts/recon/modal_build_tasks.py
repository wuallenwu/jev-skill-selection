"""Build every SkillsBench task image on Modal (the real target arch) and record pass/fail.

usage: uv run --with modal python scripts/recon/modal_build_tasks.py OUT.tsv
"""
import sys, time, traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import modal

TASKS = Path(__file__).resolve().parents[2] / "external/skillsbench/tasks"
app = modal.App.lookup("jev-build-check", create_if_missing=True)


def build(task: Path):
    env = task / "environment"
    t = time.time()
    try:
        modal.Image.from_dockerfile(env / "Dockerfile", context_dir=env).build(app)
        return task.name, "ok", int(time.time() - t), ""
    except Exception as e:
        return task.name, "FAIL", int(time.time() - t), " ".join(traceback.format_exception_only(e)).strip()[-300:].replace("\t", " ").replace("\n", " ")


if __name__ == "__main__":
    out = open(sys.argv[1], "w")
    with ThreadPoolExecutor(16) as ex:
        for row in ex.map(build, sorted(p for p in TASKS.iterdir() if (p / "environment/Dockerfile").exists())):
            print(*row, sep="\t", file=out, flush=True)
            print(*row[:3])
