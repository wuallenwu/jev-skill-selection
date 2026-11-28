"""Jev (TypeSafe) skill selector: precompute independent draws per (task, size) and cache them for the runner.

Two stages, after TypeSafe's skill-suggestion cookbook:
  1. rank: Choice over the candidates (1K: the whole library in chunks of <=250; 35K: the embedding top-100),
     each option = skill name -> description. Top FINALISTS overall go on.
  2. rerank: one Choice over the finalists, each option = description + the opening of SKILL.md.
The draw's ranking = stage-2 probabilities. Each draw shuffles the candidate order (fresh draw, spreads position bias).

usage:
  uv run python selection/jev.py prep --docs <docs.jsonl from the jev-data volume>   # -> data/skill_text.json.gz
  uv run python selection/jev.py run --size 1k --tasks pilot --draws 3                  # -> data/selections/jev_1k.json
  uv run python selection/jev.py recall --size 1k                                       # -> results/offline_recall_jev.csv
"""
import argparse, gzip, json, os, random, re, statistics, sys, time, urllib.error, urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
TEXT = DATA / "skill_text.json.gz"
LOG = ROOT / "results/raw/jev_requests.jsonl"
URL = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-1.14.0"   # pinned (docs/recon.md §8)
USD_PER_TOKEN = 0.042 / 1e6
CHUNK, FINALISTS, KEEP = 250, 20, 10   # 255-option cap; 250 x ~90 tokens stays under 32k/question
DESC, EXCERPT, QUERY = 300, 700, 8000  # chars

RANK = "Which of these skills would most help an agent complete this task? Several may be relevant; rank by how directly each one helps."
RERANK = "Which of these skills would most help an agent complete this task? Read what each one actually does, not just its name."


def load_env():
    for line in (ROOT / ".env").read_text().splitlines():
        k, _, v = line.partition("=")
        if k and v and k not in os.environ:
            os.environ[k] = v


def body(text: str) -> str:
    return re.sub(r"^﻿?---\r?\n.*?\r?\n---\r?\n", "", text, count=1, flags=re.S).strip()


def prep(docs: str):
    """Keep only the skills Jev can ever see: the 1K library + every task's 35K embedding top-100."""
    need = set(json.loads((DATA / "libraries/1k.json").read_text())["ids"])
    for ids in json.loads((DATA / "selections/embedding_35k.json").read_text())["top"].values():
        need |= set(ids[:100])
    out = {}
    for line in open(docs):
        d = json.loads(line)
        if d["id"] in need:
            out[d["id"]] = {"name": d["name"], "description": d["description"], "body": body(d["text"])[:EXCERPT]}
    missing = need - set(out)
    assert not missing, f"{len(missing)} ids not in {docs}: {sorted(missing)[:5]}"
    TEXT.write_bytes(gzip.compress(json.dumps(out, sort_keys=True).encode(), mtime=0))
    print(f"{len(out)} skills -> {TEXT}")


def keyed(ids: list[str], text: dict) -> dict[str, str]:
    """Option key = the skill's own name (ids like sb/<task>/<skill> would leak the task). Dedupe within a question."""
    keys = {}
    for sid in ids:
        base = text[sid]["name"].strip()[:64] or sid.rsplit("/", 1)[-1]
        k, n = base, 2
        while k in keys:
            k, n = f"{base} ({n})", n + 1
        keys[k] = sid
    return keys


def ask(state: dict, criteria: dict[str, str], instructions: str, meta: dict) -> tuple[dict, dict]:
    req = {"model": MODEL, "state": state, "questions": {"which": {"type": "choice", "instructions": instructions, "criteria": criteria}}}
    t0 = time.time()
    for attempt in range(5):
        try:
            r = urllib.request.Request(URL, json.dumps(req).encode(), {"Authorization": f"Bearer {os.environ['TYPESAFE_API_KEY']}",
                                                                   "Content-Type": "application/json"})
            resp = json.loads(urllib.request.urlopen(r, timeout=300).read())
            break
        except urllib.error.HTTPError as e:
            err = e.read().decode()[:500]
            if e.code not in (429, 500, 502, 503, 504) or attempt == 4:
                raise RuntimeError(f"TypeSafe {e.code}: {err}") from None
            time.sleep(2 ** attempt * 5)
    with open(LOG, "a") as f:
        f.write(json.dumps({**meta, "ts": t0, "sec": round(time.time() - t0, 2), "request": req, "response": resp}) + "\n")
    return resp["answers"]["which"]["probabilities"], resp


def draw(task: str, size: str, d: int, query: str, cands: list[str], text: dict) -> dict:
    rng_seed = f"jev|{task}|{size}|{d}"
    cands = cands[:]
    random.Random(rng_seed).shuffle(cands)
    state = {"task": query[:QUERY]}
    meta = {"task": task, "size": size, "draw": d}
    scored, tokens, versions = [], 0, set()
    chunks = [cands[i:i + CHUNK] for i in range(0, len(cands), CHUNK)]
    per_chunk = -(-FINALISTS // len(chunks))
    for ci, chunk in enumerate(chunks):
        keys = keyed(chunk, text)
        probs, resp = ask(state, {k: text[s]["description"][:DESC] for k, s in keys.items()}, RANK, meta | {"stage": "rank", "chunk": ci})
        tokens += resp["usage"]["input_tokens"]; versions.add(resp["model"])
        # Jev gives most options exactly 0; break ties by the (shuffled) option order, never by id
        pos = {k: i for i, k in enumerate(keys)}
        scored += sorted(((probs.get(k, 0.0), -pos[k], keys[k]) for k in keys), reverse=True)[:per_chunk]
    finalists = [s for *_, s in sorted(scored, reverse=True)[:FINALISTS]]
    keys = keyed(finalists, text)
    crit = {k: f"{text[s]['description'][:DESC * 2]} -- {text[s]['body']}" for k, s in keys.items()}
    probs, resp = ask(state, crit, RERANK, meta | {"stage": "rerank"})
    tokens += resp["usage"]["input_tokens"]; versions.add(resp["model"])
    ranked = [keys[k] for _, _, k in sorted((-probs.get(k, 0.0), i, k) for i, k in enumerate(keys))]  # ties -> stage-1 order
    n_pos = sum(probs.get(k, 0.0) > 1e-6 for k in keys)
    return {"ranked": ranked[:KEEP], "tokens": tokens, "cost": round(tokens * USD_PER_TOKEN, 6), "versions": sorted(versions),
            "shuffle_seed": rng_seed, "n_requests": len(chunks) + 1, "rerank_nonzero": n_pos}


def run(size: str, task_names: list[str], draws: int, workers: int):
    import yaml
    load_env()
    cap = yaml.safe_load((ROOT / "harness/config.yaml").read_text())["jev_cap_usd"]
    text = json.loads(gzip.decompress(TEXT.read_bytes()))
    tasks = json.loads((DATA / "tasks.json").read_text())
    if size == "1k":
        pool = lambda t: json.loads((DATA / "libraries/1k.json").read_text())["ids"]
    else:
        emb = json.loads((DATA / "selections/embedding_35k.json").read_text())["top"]
        pool = lambda t: emb[t][:100]
    out_p = DATA / f"selections/jev_{size}.json"
    out = json.loads(out_p.read_text()) if out_p.exists() else {"selector": "jev", "library_size": size, "model": MODEL, "top": {}, "draws": {}}
    spent = sum(x["cost"] for ds in out["draws"].values() for x in ds)
    todo = [(t, d) for t in task_names for d in range(draws) if len(out["draws"].get(t, [])) <= d]
    # ~4 rank + 1 rerank requests of <=30k tokens each per 1K draw; refuse to start if the worst case could pass the cap
    worst = len(todo) * (len(pool(task_names[0])) // CHUNK + 2) * 32_000 * USD_PER_TOKEN
    print(f"{len(todo)} draws to run; spent so far ${spent:.3f}; worst case +${worst:.2f}; cap ${cap}")
    if spent + worst > cap:
        sys.exit("would exceed the Jev cap; aborting")
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(workers) as ex:
        futs = {(t, d): ex.submit(draw, t, size, d, tasks[t]["query"], pool(t), text) for t, d in todo}
        for (t, d), f in futs.items():
            r = f.result()
            ds = out["draws"].setdefault(t, [])
            ds.extend([None] * (d + 1 - len(ds)))
            ds[d] = r
            out["top"][t] = [x["ranked"] for x in ds if x]
            out_p.write_text(json.dumps(out, indent=1))
            hit = len(set(r["ranked"][:3]) & set(tasks[t]["qrels"]))
            print(f"{t:40s} draw {d}: {hit}/{len(tasks[t]['qrels'])} curated in top-3  ${r['cost']:.4f}  {r['versions']}")
    print(f"total Jev spend in {out_p.name}: ${sum(x['cost'] for ds in out['draws'].values() for x in ds):.3f}")


def recall(size: str):
    """J2: recall@k per draw (raw and normalized by min(k, |curated|)), mean over tasks, plus the spread across draws."""
    tasks = json.loads((DATA / "tasks.json").read_text())
    keep = set((DATA / "task_set.txt").read_text().split())
    top = {t: v for t, v in json.loads((DATA / f"selections/jev_{size}.json").read_text())["top"].items() if t in keep}
    n_draws = min(len(v) for v in top.values())
    out = ROOT / "results/offline_recall_jev.csv"
    rows = [l for l in (out.read_text().splitlines()[1:] if out.exists() else []) if not l.startswith(f"jev,{size},")]
    for k in (1, 3, 5, 10):
        per_draw = []
        for d in range(n_draws):
            q = [tasks[t]["qrels"] for t in top]
            hits = [len(set(top[t][d][:k]) & set(c)) for t, c in zip(top, q)]
            per_draw.append((statistics.mean(h / len(c) for h, c in zip(hits, q)), statistics.mean(h / min(k, len(c)) for h, c in zip(hits, q))))
        rec, norm = zip(*per_draw)
        sd = statistics.stdev(rec) if len(rec) > 1 else 0.0
        rows.append(f"jev,{size},{k},{statistics.mean(rec):.4f},{statistics.mean(norm):.4f},{sd:.4f},{n_draws},{len(top)}")
    out.write_text("selector,library_size,k,recall,recall_norm,sd_across_draws,n_draws,n_tasks\n" + "\n".join(sorted(rows)) + "\n")
    print(out.read_text())


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["prep", "run", "recall"])
    ap.add_argument("--docs")
    ap.add_argument("--size", choices=["1k", "35k"], default="1k")
    ap.add_argument("--tasks", default="pilot", help="pilot | all | comma list")
    ap.add_argument("--draws", type=int, default=3)
    ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args()
    if a.cmd == "prep":
        prep(a.docs)
    elif a.cmd == "recall":
        recall(a.size)
    else:
        names = (DATA / "task_set.txt").read_text().split() if a.tasks == "all" else \
            (DATA / f"{a.tasks}.txt").read_text().split() if (DATA / f"{a.tasks}.txt").exists() else a.tasks.split(",")
        run(a.size, names, a.draws, a.workers)
