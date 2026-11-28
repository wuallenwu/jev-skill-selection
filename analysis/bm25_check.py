"""Why is our BM25 recall ~2x SkillRouter's? Re-run BM25 at 35K over name+description only (vs name|description|SKILL.md).

usage: uv run modal run analysis/bm25_check.py
"""
import json, re
import modal

vol = modal.Volume.from_name("jev-data")
app = modal.App("jev-bm25-check", image=modal.Image.debian_slim(python_version="3.12").pip_install("rank-bm25", "numpy"))


@app.function(volumes={"/data": vol}, timeout=3600, memory=16384)
def check() -> dict:
    import numpy as np
    from rank_bm25 import BM25Okapi
    tok = lambda s: re.findall(r"\w+", s.lower())
    docs = [json.loads(l) for l in open("/data/docs.jsonl")]
    tasks = json.load(open("/data/tasks.json"))
    out = {}
    for name, text in {"name+desc": lambda d: f"{d['name']} | {d['description']}",
                       "full": lambda d: f"{d['name']} | {d['description']} | {d['text']}"}.items():
        bm = BM25Okapi([tok(text(d)) for d in docs])
        rec = {k: [] for k in (3, 10)}
        for t, v in tasks.items():
            top = [docs[j]["id"] for j in np.argsort(-bm.get_scores(tok(v["query"])))[:10]]
            for k in rec:
                rec[k].append(len(set(top[:k]) & set(v["qrels"])) / len(v["qrels"]))
        out[name] = {f"R@{k}": round(sum(r) / len(r), 4) for k, r in rec.items()}
    return out


@app.local_entrypoint()
def main():
    print(check.remote())
