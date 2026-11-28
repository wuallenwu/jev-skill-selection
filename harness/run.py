"""Config-driven runner: (model, condition, library_size, seed) -> Harbor trials on Modal -> append-only results rows.

Runs inside a detached Modal function, so it survives a laptop disconnect. Resumable: a run_id that already has a
non-error row is skipped; errored runs are retried and get a new row (rows are never rewritten).

launch:  uv run modal run --detach harness/run.py --model deepseek-v4-flash --conditions none,oracle \
             --library 1k --tasks pilot --runs 3 --results pilot
fetch:   uv run modal volume get --force jev-jobs results/<results>.jsonl results/
"""
import hashlib, json, os, shutil, subprocess, sys, threading, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import modal

ROOT = Path(__file__).resolve().parents[1]
LIB_ROOT = Path("/vol/skills")  # SkillsMP dirs on the jev-data volume
JOBS = Path("/jobs")

image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("git")
    .add_local_dir(ROOT / "external/harbor", "/src/harbor", copy=True, ignore=[".git", "**/node_modules", "apps", "docs*"])
    .run_commands("pip install '/src/harbor[modal]' pyyaml")
    .add_local_dir(ROOT / "data", "/root/data", ignore=["raw"])
    .add_local_dir(ROOT / "harness", "/root/harness", ignore=["__pycache__"])
)
app = modal.App("jev-runner", image=image)
jobs_vol = modal.Volume.from_name("jev-jobs", create_if_missing=True)
data_vol = modal.Volume.from_name("jev-data")
lib1k_vol = modal.Volume.from_name("jev-lib1k", create_if_missing=True)  # normalized 1K library for full-list runs
LIB1K = Path("/lib1k")


def run_id(model, condition, size, seed, task, run_idx) -> str:
    size = "-" if condition in ("none", "oracle") else size  # size-free conditions are shared across sizes
    return hashlib.sha1(f"{model}|{condition}|{size}|{seed}|{task}|{run_idx}".encode()).hexdigest()[:16]


_FM = __import__("re").compile(r"^---\n(.*?)\n---", __import__("re").DOTALL)  # the regex terminus-2 uses


def _index_entry(sid: str) -> dict:
    global _INDEX
    if "_INDEX" not in globals():
        _INDEX = json.loads((LIB_ROOT / "_metadata/index_deduped.json").read_text())["skills"]
    return _INDEX.get(sid, {})


def normalize_skill_md(d: Path, sid: str) -> None:
    """Make terminus-2 see every skill: uppercase SKILL.md, LF endings, no BOM, parseable name/description frontmatter.
    ~340 library skills ship skill.md and some use CRLF; terminus-2 silently skips those."""
    import yaml
    f = next((p for p in d.iterdir() if p.name.lower() == "skill.md"), None)
    assert f is not None, f"{sid}: no SKILL.md"
    text = f.read_text(errors="replace").lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n")
    m = _FM.match(text)
    try:
        fm = yaml.safe_load(m.group(1)) if m else None
    except yaml.YAMLError:
        fm = None
    if not (isinstance(fm, dict) and fm.get("name") and fm.get("description")):
        e = _index_entry(sid)
        head = yaml.safe_dump({"name": str(e.get("name") or sid.split("/")[-1]), "description": str(e.get("description") or "")}, sort_keys=False)
        text = f"---\n{head}---\n" + (text[m.end():] if m else text)
    f.unlink()
    (d / "SKILL.md").write_text(text)


def materialize(cond, task, skill_ids, dest: Path) -> dict:
    """Copy the chosen skill dirs into dest/<dirname>; return {dirname: skill_id}."""
    from harness import conditions as C
    dest.mkdir(parents=True, exist_ok=True)
    m = {}
    if cond == "oracle":  # the task's own curated dirs, exactly as shipped
        for d in sorted((C.DATA / f"harbor_tasks/{task}/solution/skills").iterdir()):
            if not (d / "SKILL.md").is_file():  # e.g. seismic tasks ship a licenses/ dir next to the skills
                continue
            name = f"sb__{task}__{d.name}"
            shutil.copytree(d, dest / name)
            m[name] = f"own:{d.name}"
        return m
    for sid in skill_ids:
        name = C.skill_dirname(sid)
        shutil.copytree(C.skill_source(sid, task, LIB_ROOT), dest / name)
        normalize_skill_md(dest / name, sid)
        m[name] = sid
    return m


def _tree_hash(root: Path) -> str:
    h = hashlib.sha256()
    for f in sorted(p for p in root.rglob("*") if p.is_file() and p.name != "MANIFEST.json"):
        h.update(str(f.relative_to(root)).encode()); h.update(f.read_bytes())
    return h.hexdigest()


@app.function(volumes={"/vol": data_vol, "/lib1k": lib1k_vol}, timeout=3600, memory=8192)
def lib1k(action: str = "build") -> dict:
    """build: materialize the 1K library (normalized) onto jev-lib1k. verify: check nobody modified it."""
    sys.path.insert(0, "/root")
    from harness import conditions as C
    man = LIB1K / "MANIFEST.json"
    if action == "verify":
        m = json.loads(man.read_text())
        return {"ok": _tree_hash(LIB1K) == m["tree_hash"], **{k: m[k] for k in ("n", "library_hash")}}
    ids = C.library("1k")
    lib_hash = hashlib.sha256("\n".join(ids).encode()).hexdigest()
    if man.exists() and json.loads(man.read_text()).get("library_hash") == lib_hash:
        return {k: v for k, v in json.loads(man.read_text()).items() if k != "dirmap"} | {"rebuilt": False}
    for p in LIB1K.iterdir():
        shutil.rmtree(p) if p.is_dir() else p.unlink()
    dmap = materialize("full-list", None, ids, LIB1K)
    m = {"n": len(ids), "library_hash": lib_hash, "dirmap": dmap, "tree_hash": _tree_hash(LIB1K)}
    man.write_text(json.dumps(m)); lib1k_vol.commit()
    return {k: v for k, v in m.items() if k != "dirmap"} | {"rebuilt": True}


def one_trial(spec: dict, cfg: dict, meta: dict) -> dict:
    import yaml
    from harness import conditions as C, trajectory as T
    model = cfg["models"][spec["model"]]
    prov = cfg["providers"][model["provider"]]
    rid, task, cond = spec["run_id"], spec["task"], spec["condition"]
    t0 = time.time()
    row = {"run_id": rid, "task_id": task, "domain": C.tasks()[task]["domain"], "agent_model": spec["model"], "model_id": model["id"],
           "provider": model["provider"], "condition": cond, "library_size": spec["size"], "seed": spec["seed"], "run_idx": spec["run_idx"],
           "k": cfg["k"], "curated_skills": C.curated(task), "agent": cfg["agent"], **meta}
    try:
        sel = C.select(cond, task, spec["size"], spec["run_idx"], spec["seed"], cfg["k"])
        row["skills_selected"] = sel if cond != "full-list" else f"<library {spec['size']}: {len(sel)}>"
        if cond == "jev":
            row.update(spec.get("jev_meta") or {})
        sdir = Path(f"/tmp/skills/{rid}")
        shutil.rmtree(sdir, ignore_errors=True)
        # Bound sandbox life so a dead orchestrator can't leave sandboxes billing for Harbor's 24 h default.
        env_kwargs = {"app_name": cfg.get("modal_app", "jev-harbor"), "sandbox_idle_timeout_secs": 1800, "sandbox_timeout_secs": 4 * 3600}
        agent = {"name": cfg["agent"], "model_name": f"openai/{model['id']}", "base_url": prov["base_url"], "model_api_key_name": prov["key_env"]}
        if cond == "full-list":
            # Harbor's per-trial upload can't take 1K skills (one exec with every path > ARG_MAX), so mount the
            # prebuilt library. shortcut: the mount is read-write and shared; lib1k("verify") after the runs checks it.
            dmap = json.loads((LIB1K / "MANIFEST.json").read_text())["dirmap"]
            env_kwargs["volumes"] = {"/app/skills": "jev-lib1k"}
        else:
            dmap = materialize(cond, task, sel, sdir) if sel else {}
            if dmap:
                agent["skills"] = [str(sdir)]
        job = {"job_name": rid, "jobs_dir": str(JOBS / "trials"), "n_attempts": 1, "n_concurrent_trials": 1,
               # "limit" reserves 0.125 cores/128 MB and bursts to the task's cpus/memory, so Modal bills ~actual usage
               # instead of the full reservation while the agent waits on the LLM.
               "environment": {"type": "modal", "kwargs": env_kwargs, "cpu_enforcement_policy": cfg["resource_policy"],
                               "memory_enforcement_policy": cfg["resource_policy"]},
               "agents": [agent], "tasks": [{"path": f"/root/data/harbor_tasks/{task}"}]}
        jdir = JOBS / "trials" / rid
        shutil.rmtree(jdir, ignore_errors=True)  # a retried errored run starts clean; its old row stays in results
        yml = Path(f"/tmp/{rid}.yaml"); yml.write_text(yaml.safe_dump(job))
        p = subprocess.run(["harbor", "run", "-c", str(yml), "--yes", "--quiet"], capture_output=True, text=True, timeout=4 * 3600)
        res = next(jdir.glob("*/result.json"), None)
        if res is None:
            raise RuntimeError(f"harbor produced no trial result (exit {p.returncode}): {p.stderr[-500:]}")
        r = json.loads(res.read_text())
        ar, exc = r.get("agent_result") or {}, r.get("exception_info")
        reward = ((r.get("verifier_result") or {}).get("rewards") or {}).get("reward")
        tr = T.parse(res.parent / "agent")
        opened = [dmap.get(d, d) for d in tr["skills_opened_dirs"]]
        n_in, n_out = ar.get("n_input_tokens") or 0, ar.get("n_output_tokens") or 0
        row.update({
            "passed": reward == 1.0, "reward": reward,
            "error": f"{exc.get('exception_type')}: {exc.get('exception_message', '')[:300]}" if exc else None,
            "skills_listed_n": len(tr["skills_listed"]),
            "skills_unlisted": sorted(set(dmap) - set(tr["skills_listed"])),  # copied in but not shown to the agent
            "curated_present": (set(dmap) <= set(tr["skills_listed"])) if cond == "oracle" else None,
            "skills_opened": opened, "skills_used": [dmap.get(d, d) for d in tr["skills_used_dirs"]],
            "recall_selected": C.recall(sel, task) if sel and cond != "full-list" else None,
            "recall_opened": min(1.0, len({s for s in opened if s in C.curated(task) or s.startswith("own:")}) / len(C.curated(task))) if cond != "none" else None,
            "agent_tokens_in": n_in, "agent_tokens_cached": ar.get("n_cache_tokens") or 0, "agent_tokens_out": n_out,
            "agent_cost_usd": round(n_in * model["usd_in"] / 1e6 + n_out * model["usd_out"] / 1e6, 6),  # our price table, not LiteLLM's
            "selector_cost_usd": (spec.get("jev_meta") or {}).get("jev_cost_usd", 0.0),
            "agent_sec": _dur(r.get("agent_execution")), "trial_started_at": r.get("started_at"), "trial_finished_at": r.get("finished_at"),
            "harbor_trial_dir": str(res.parent.relative_to(JOBS)),
        })
        # Only agent-behaviour exceptions count as a (failed) task outcome; provider/infra errors are retried.
        row["status"] = status_of(exc, reward)
        if exc and row["status"] == "ok":
            row["passed"] = False
    except Exception as e:  # infra failure: record it; the run is retried on resume
        row.update({"status": "error", "error": f"{type(e).__name__}: {str(e)[:500]}", "passed": None})
    row["latency_sec"] = round(time.time() - t0, 1)
    row["logged_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    return row


OUTCOME_EXCEPTIONS = {"AgentTimeoutError", "ContextWindowExceededError", "AgentSafetyRefusalError", "NonZeroAgentExitCodeError"}


def is_ok(row: dict) -> bool:
    """A finished task outcome. Re-checks the error type so rows logged before status_of existed are judged the same way."""
    err = row.get("error") or ""
    return row.get("status") == "ok" and (not err or err.split(":")[0] in OUTCOME_EXCEPTIONS)


def status_of(exc: dict | None, reward) -> str:
    """ok = a real task outcome (pass or fail); error = infra/provider failure, retried on resume."""
    if exc:
        return "ok" if exc.get("exception_type") in OUTCOME_EXCEPTIONS else "error"
    return "ok" if reward is not None else "error"


def _dur(phase):
    try:
        from datetime import datetime
        return (datetime.fromisoformat(phase["finished_at"].replace("Z", "+00:00")) - datetime.fromisoformat(phase["started_at"].replace("Z", "+00:00"))).total_seconds()
    except Exception:
        return None


def read_rows(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()] if path.exists() else []


def spent(rows: list[dict]) -> dict:
    out = {}
    for r in rows:
        out[r["provider"]] = out.get(r["provider"], 0) + (r.get("agent_cost_usd") or 0)
        out["jev"] = out.get("jev", 0) + (r.get("selector_cost_usd") or 0)
    return out


@app.function(volumes={"/jobs": jobs_vol, "/vol": data_vol, "/lib1k": lib1k_vol}, secrets=[modal.Secret.from_name("jev-keys")],
              timeout=24 * 3600, cpu=8, memory=16384, nonpreemptible=True)  # preemption cancels every in-flight trial
def grid(specs: list[dict], cfg: dict, meta: dict, results: str, n_concurrent: int):
    sys.path.insert(0, "/root")
    (Path.home() / ".modal.toml").touch()  # Harbor's auth preflight; the container's own Modal credentials are used
    if any(cfg["models"][s["model"]]["provider"] == "mock" for s in specs):
        from harness import mock_llm
        mock_llm.serve(); os.environ["MOCK_API_KEY"] = "mock"
    if any(s["condition"] == "full-list" for s in specs):
        print("lib1k:", lib1k.remote("build"), flush=True); lib1k_vol.reload()
    out = JOBS / "results" / f"{results}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    rows = read_rows(out)
    done = {r["run_id"] for r in rows if is_ok(r)}
    todo = [s for s in specs if s["run_id"] not in done]
    print(f"{len(specs)} runs requested, {len(specs) - len(todo)} already done, {len(todo)} to run", flush=True)
    lock, stop = threading.Lock(), threading.Event()
    caps = {p: v["cap_usd"] for p, v in cfg["providers"].items()} | {"jev": cfg["jev_cap_usd"]}

    def work(spec):
        if stop.is_set():
            return
        row = one_trial(spec, cfg, meta)
        with lock:
            with out.open("a") as f:
                f.write(json.dumps(row) + "\n")
            rows.append(row)
            s = spent(rows)
            over = [p for p, v in s.items() if caps.get(p) and v >= caps[p]]
            if over and not stop.is_set():
                print(f"SPEND CAP HIT {over}: {s}; stopping new trials", flush=True); stop.set()
            jobs_vol.commit()
            print(f"[{len(rows)}] {row['condition']:<12} {row['task_id']:<40} status={row['status']} passed={row.get('passed')} "
                  f"cost=${row.get('agent_cost_usd', 0) or 0:.4f} {row.get('error') or ''}"[:220], flush=True)

    with ThreadPoolExecutor(n_concurrent) as ex:
        list(ex.map(work, todo))
    if any(s["condition"] == "full-list" for s in specs):
        v = lib1k.remote("verify"); print("lib1k integrity:", v, flush=True)
        assert v["ok"], "an agent modified the shared 1K library volume; full-list runs from this grid are suspect"
    print("spend so far:", spent(rows), flush=True)
    return spent(rows)


def build_specs(model, conditions, library, seed, task_names, runs):
    from harness import conditions as C
    specs = []
    for cond in conditions:
        assert cond in C.CONDITIONS, cond
        sizes = ["-"] if cond in C.SIZE_FREE else library
        for size in sizes:
            if cond == "full-list" and size != "1k":
                continue
            for task in task_names:
                for i in range(runs):
                    specs.append({"model": model, "condition": cond, "size": size, "seed": seed, "task": task, "run_idx": i,
                                  "run_id": run_id(model, cond, size, seed, task, i)})
    return specs


def git_meta():
    sha = lambda p: subprocess.run(["git", "-C", str(p), "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    import importlib.metadata as md
    return {"repo_sha": sha(ROOT), "harbor_sha": sha(ROOT / "external/harbor"), "skillsbench_sha": sha(ROOT / "external/skillsbench"),
            "harbor_version": md.version("harbor")}


@app.local_entrypoint()
def main(model: str, conditions: str, library: str = "1k", seed: int = 0, tasks: str = "all", runs: int = 0,
         results: str = "", n_concurrent: int = 32, dry_run: bool = False, resource_policy: str = "", modal_app: str = ""):
    import yaml
    sys.path.insert(0, str(ROOT))
    cfg = yaml.safe_load((ROOT / "harness/config.yaml").read_text())
    cfg["resource_policy"] = resource_policy or cfg["resource_policy"]
    cfg["modal_app"] = modal_app or cfg.get("modal_app", "jev-harbor")
    task_set = (ROOT / cfg["task_set"]).read_text().split()
    names = task_set if tasks == "all" else (ROOT / f"data/{tasks}.txt").read_text().split() if (ROOT / f"data/{tasks}.txt").exists() else tasks.split(",")
    assert set(names) <= set(task_set), f"not in the oracle-valid task set: {set(names) - set(task_set)}"
    specs = build_specs(model, conditions.split(","), library.split(","), seed, names, runs or cfg["runs"])
    results = results or f"{model}"
    print(f"{len(specs)} runs -> jev-jobs:results/{results}.jsonl")
    if dry_run:
        for s in specs[:5]:
            print(s)
        return
    print(grid.remote(specs, cfg, git_meta(), results, n_concurrent))
