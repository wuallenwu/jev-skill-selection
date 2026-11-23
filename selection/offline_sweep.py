"""Build the 1K/35K skill libraries and run the offline recall sweep (BM25, Qwen3-Embedding-8B, SKILLRET) on Modal.

Everything runs inside remote functions, so `--detach` survives a laptop disconnect. Outputs land in the
`jev-data` volume under out/; fetch with `selection/fetch_outputs.sh`.

  modal run --detach selection/offline_sweep.py              # full sweep
  modal run selection/offline_sweep.py --test 200            # throughput test on 200 skills (no outputs)
"""
import hashlib, json, random, re
from pathlib import Path
import modal

ZIP_URL = "https://ucdavis.box.com/shared/static/7zr4wsaaydclt89rgt78n0di1fnned55.zip"
SEED, K_MAX, MAX_TOK = 0, 100, 8192
QWEN_PREFIX = "Instruct: Given a web search query, retrieve relevant passages that answer the query\nQuery:"
SKILLRET_PREFIX = "Instruct: Given a skill search query, retrieve relevant skills that match the query\nQuery: "
MODELS = {"embedding": ("Qwen/Qwen3-Embedding-8B", QWEN_PREFIX), "skillret": ("ThakiCloud/SKILLRET-Embedding-8B", SKILLRET_PREFIX)}

app = modal.App("jev-offline-sweep")
vol = modal.Volume.from_name("jev-data", create_if_missing=True)
cpu = modal.Image.debian_slim(python_version="3.12").apt_install("unzip", "curl").pip_install("pyyaml", "rank-bm25", "numpy")
gpu = modal.Image.debian_slim(python_version="3.12").pip_install("sentence-transformers==6.3.0", "transformers==5.24.0", "torch==2.15.0", "numpy").env({"HF_HOME": "/data/hf"})
V = {"/data": vol}


def frontmatter(text):
    import yaml
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", text, re.S)
    if not m:
        return {}, text
    try:
        fm = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        fm = {}
    return (fm if isinstance(fm, dict) else {}), m.group(2)


def sha(s):
    return hashlib.sha256(s.encode()).hexdigest()


def near(a, b):
    """Near-duplicate SKILL.md (whitespace/case-insensitive, first 5K chars)."""
    import difflib
    n = lambda s: re.sub(r"\s+", " ", s).strip().lower()[:5000]
    return difflib.SequenceMatcher(None, n(a), n(b)).ratio() >= 0.8


@app.function(image=cpu, volumes=V, timeout=3600)
def prep(bench: dict):
    """bench = {task: {"task_md": str, "skills": {dir: SKILL.md text}}} read locally from external/skillsbench/tasks."""
    import subprocess
    root = Path("/data/skills")
    if not (root / "_metadata/index_deduped.json").exists():
        import shutil, zipfile
        shutil.rmtree(root, ignore_errors=True)
        subprocess.run(f"curl -sSL -o /tmp/data.zip '{ZIP_URL}'", shell=True, check=True)
        with zipfile.ZipFile("/tmp/data.zip") as z:  # not `unzip`: it mangles the UTF-8 dir names on debian
            z.extractall("/data", [m for m in z.namelist() if m.startswith("skills/")])
        vol.commit()

    # Curated skills; identical or near-identical same-name copies across tasks collapse to one canonical ID (first task alphabetically).
    curated, by_hash, by_name, tasks = {}, {}, {}, {}
    for task in sorted(bench):
        fm, body = frontmatter(bench[task]["task_md"])
        qrels = []
        for d, text in sorted(bench[task]["skills"].items()):
            h = sha(text)
            if h not in by_hash:
                sfm, _ = frontmatter(text)
                name = str(sfm.get("name", d))
                same = [c for c in by_name.get(name.lower(), []) if near(curated[c]["text"], text)]
                by_hash[h] = same[0] if same else f"sb/{task}/{d}"
                if not same:
                    curated[by_hash[h]] = {"name": name, "description": str(sfm.get("description", "")), "text": text, "dir": d}
                    by_name.setdefault(name.lower(), []).append(by_hash[h])
            qrels.append(by_hash[h])
        tasks[task] = {"query": body.strip(), "qrels": sorted(set(qrels)), "domain": (fm.get("metadata") or {}).get("category")}
    cur_dirs = {c["dir"] for c in curated.values()}

    idx = json.load(open(root / "_metadata/index_deduped.json"))["skills"]
    pool, dropped = {}, {"missing_skill_md": 0, "curated_hash": 0, "skillsbench_url": 0, "curated_dir_name": 0, "curated_near_dup": 0}
    for key, e in idx.items():
        p = next((f for f in (root / key).glob("*") if f.name.lower() == "skill.md"), None)  # ~340 ship as skill.md
        if p is None:
            dropped["missing_skill_md"] += 1; continue
        text = p.read_text(errors="replace")
        if sha(text) in by_hash:
            dropped["curated_hash"] += 1; continue
        if "benchflow-ai/skillsbench" in (e.get("github_url") or ""):
            dropped["skillsbench_url"] += 1; continue
        if key.split("/", 1)[1] in cur_dirs:
            dropped["curated_dir_name"] += 1; continue
        if any(near(curated[c]["text"], text) for c in by_name.get(str(e.get("name") or "").lower(), [])):
            dropped["curated_near_dup"] += 1; continue  # e.g. skillsmp/xlsx-8 == curated xlsx
        pool[key] = {"name": str(e.get("name") or key), "description": str(e.get("description") or ""), "text": text}

    pool_ids = sorted(pool)
    pool_hash = sha("\n".join(pool_ids))
    distract_1k = sorted(random.Random(SEED).sample(pool_ids, 1000 - len(curated)))
    libs = {"1k": sorted(curated) + distract_1k, "35k": sorted(curated) + pool_ids}
    meta = {"seed": SEED, "pool_hash": pool_hash, "n_curated": len(curated), "n_pool": len(pool), "dropped": dropped}
    assert len(libs["1k"]) == 1000 and len(set(libs["35k"])) == len(libs["35k"])
    assert all(q in curated for t in tasks.values() for q in t["qrels"])

    out = Path("/data/out"); out.mkdir(exist_ok=True)
    for size, ids in libs.items():
        json.dump({**meta, "size": size, "n": len(ids), "ids": ids}, open(out / f"library_{size}.json", "w"), indent=0)
    docs = {**curated, **pool}
    with open("/data/docs.jsonl", "w") as f:
        for i in libs["35k"]:
            f.write(json.dumps({"id": i, **{k: docs[i][k] for k in ("name", "description", "text")}}) + "\n")
    json.dump(tasks, open("/data/tasks.json", "w"))
    vol.commit()
    return meta


def load_docs():
    return [json.loads(l) for l in open("/data/docs.jsonl")]


def doc_text(d):
    return f"{d['name']} | {d['description']} | {d['text']}"


@app.function(image=cpu, volumes=V, timeout=3600, memory=16384)
def bm25(size: str):
    import numpy as np
    from rank_bm25 import BM25Okapi
    ids = set(json.load(open(f"/data/out/library_{size}.json"))["ids"])
    docs = [d for d in load_docs() if d["id"] in ids]
    tok = lambda s: re.findall(r"\w+", s.lower())  # shortcut: no stemming/stopwords, fine as a lexical baseline
    bm = BM25Okapi([tok(doc_text(d)) for d in docs])
    tasks = json.load(open("/data/tasks.json"))
    return {t: [docs[j]["id"] for j in np.argsort(-bm.get_scores(tok(v["query"])))[:K_MAX]] for t, v in tasks.items()}


@app.function(image=gpu, volumes=V, gpu="H100", timeout=4 * 3600)
def embed(selector: str, test: int = 0):
    import time, numpy as np, torch
    from sentence_transformers import SentenceTransformer
    name, prefix = MODELS[selector]
    m = SentenceTransformer(name, device="cuda", model_kwargs={"torch_dtype": torch.bfloat16})
    m.max_seq_length = MAX_TOK  # truncation keeps the EOS the last-token pooler reads (tokenizer post-processor)
    tk = m.tokenizer

    def run(texts):
        return m.encode(texts, batch_size=8, normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False).astype(np.float32)

    docs = load_docs()
    if test:
        sample = random.Random(1).sample(docs, test)
        n_tok = sum(min(len(tk(doc_text(d)).input_ids), MAX_TOK) for d in sample)
        t0 = time.time(); run([doc_text(d) for d in sample]); dt = time.time() - t0
        total = sum(len(doc_text(d)) for d in docs) / sum(len(doc_text(d)) for d in sample) * n_tok
        last = tk("hello").input_ids[-1]
        return {"selector": selector, "ends_with_eos": last in (tk.eos_token_id, tk.pad_token_id), "tok_per_s": n_tok / dt, "est_total_tok": total, "est_hours": total / (n_tok / dt) / 3600}

    tasks = json.load(open("/data/tasks.json"))
    cache = Path(f"/data/emb_{selector}.npy")
    if cache.exists():
        D = np.load(cache)
    else:
        D = run([doc_text(d) for d in docs]); np.save(cache, D); vol.commit()
    Q = run([prefix + v["query"] for v in tasks.values()])
    all_ids = [d["id"] for d in docs]
    out = {}
    for size in ("1k", "35k"):
        keep = set(json.load(open(f"/data/out/library_{size}.json"))["ids"])
        cols = np.array([i for i, x in enumerate(all_ids) if x in keep])
        S = Q @ D[cols].T
        out[size] = {t: [all_ids[cols[j]] for j in np.argsort(-S[r])[:K_MAX]] for r, t in enumerate(tasks)}
    return out


def recall(top, qrels, k):
    return len(set(top[:k]) & set(qrels)) / len(qrels)


@app.function(image=cpu, volumes=V, timeout=6 * 3600)
def sweep(bench: dict):
    meta = prep.remote(bench)
    print("prep", meta)
    emb = {s: embed.spawn(s) for s in MODELS}
    picks = {("bm25", s): v for s, v in zip(("1k", "35k"), bm25.map(["1k", "35k"]))}
    for s, call in emb.items():
        for size, v in call.get().items():
            picks[(s, size)] = v
    tasks = json.load(open("/data/tasks.json"))
    out = Path("/data/out")
    agg, rows = ["selector,library_size,k,recall,n_tasks"], ["selector,library_size,task_id,domain,n_curated,k,recall"]
    for (sel, size), top in sorted(picks.items()):
        json.dump({"selector": sel, "library_size": size, "pool_hash": meta["pool_hash"], "top": top}, open(out / f"selections_{sel}_{size}.json", "w"))
        for k in (1, 3, 5, 10, 100):
            rs = [recall(top[t], v["qrels"], k) for t, v in tasks.items()]
            agg.append(f"{sel},{size},{k},{sum(rs) / len(rs):.4f},{len(rs)}")
            rows += [f"{sel},{size},{t},{v['domain']},{len(v['qrels'])},{k},{r:.4f}" for (t, v), r in zip(tasks.items(), rs)]
    (out / "offline_recall.csv").write_text("\n".join(agg) + "\n")
    (out / "offline_recall_per_task.csv").write_text("\n".join(rows) + "\n")
    vol.commit()
    print("\n".join(agg))


def read_bench():
    tasks = Path(__file__).resolve().parents[1] / "external/skillsbench/tasks"
    return {t.name: {"task_md": (t / "task.md").read_text(),
                     "skills": {s.parent.name: s.read_text(errors="replace") for s in sorted(t.glob("environment/skills/*/SKILL.md"))}}
            for t in sorted(tasks.iterdir()) if (t / "task.md").exists()}


@app.local_entrypoint()
def main(test: int = 0):
    assert recall(["a", "b", "c"], ["b", "x"], 3) == 0.5 and recall(["a"], ["b"], 1) == 0.0
    assert near("Hello  World", "hello world") and not near("abc" * 50, "xyz" * 50)
    bench = read_bench()
    if test:
        print(prep.remote(bench))
        for r in embed.map(list(MODELS), kwargs={"test": test}):
            print(r)
    else:
        sweep.remote(bench)
