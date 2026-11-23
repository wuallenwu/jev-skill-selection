"""Oracle validation: run every converted task's reference solution via Harbor on Modal, inside a Modal
function so it survives a laptop disconnect. Job output lands in the `jev-jobs` Volume.

launch:  uv run modal run --detach harness/modal_oracle_sweep.py [--tasks a,b] [--job-name oracle-sweep-1]
fetch:   uv run modal volume get jev-jobs <job-name> jobs/
summary: uv run python harness/oracle_summary.py jobs/<job-name>
"""
import subprocess
from pathlib import Path
import modal

ROOT = Path(__file__).resolve().parents[1]
vol = modal.Volume.from_name("jev-jobs", create_if_missing=True)
image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("git")
    .add_local_dir(ROOT / "external/harbor", "/src/harbor", copy=True, ignore=[".git", "**/node_modules", "apps", "docs*"])
    .run_commands("pip install '/src/harbor[modal]'")
    .add_local_dir(ROOT / "data/harbor_tasks", "/tasks")
)
app = modal.App("jev-oracle-sweep", image=image)


@app.function(volumes={"/jobs": vol}, timeout=6 * 3600)
def sweep(job_name: str, tasks: str = "", n_concurrent: int = 32):
    # Harbor's preflight wants ~/.modal.toml or token env vars; inside Modal the client already uses
    # the container's own credentials, so an empty config passes the check without copying a token.
    (Path.home() / ".modal.toml").touch()
    cmd = ["harbor", "run", "-p", "/tasks", "-a", "oracle", "-e", "modal", "-n", str(n_concurrent),
           "--jobs-dir", "/jobs", "--job-name", job_name, "--yes", "--quiet"]
    for t in filter(None, tasks.split(",")):
        cmd += ["--include-task-name", t]
    print(" ".join(cmd), flush=True)
    r = subprocess.run(cmd)
    vol.commit()
    return r.returncode


@app.local_entrypoint()
def main(job_name: str = "oracle-sweep-1", tasks: str = "", n_concurrent: int = 32):
    print("exit code:", sweep.remote(job_name, tasks, n_concurrent))
