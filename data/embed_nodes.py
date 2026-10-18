"""Embed papers and claims with text-embedding-3-small. No other model.

Setup and reproducibility claims are skipped. Vectors are float32 .npy files
plus a sidecar of ids, so the text stays in the sentence and facet files.
"""

import http.client
import json
import ssl
import time
import urllib.error
import urllib.request
from pathlib import Path

import certifi
import numpy as np

from r2_config import ROOT, load_env

CLEAN = ROOT / "data" / "extract" / "facets_clean.jsonl"
CORPUS = ROOT / "data" / "extract" / "corpus.jsonl"
SENT_DIR = ROOT / "data" / "extract" / "sentences"
OUT = ROOT / "data" / "extract" / "embeddings"
MODEL = "text-embedding-3-small"
URL = "https://api.openai.com/v1/embeddings"
BATCH = 256
CLAIM_LISTS = {
    "research_question": "question",
    "claimed_contributions": "contribution",
    "reported_results": "result",
    "quantitative_findings": "quantitative",
    "ablation_findings": "ablation",
    "failure_cases": "failure",
    "stated_limits": "limit",
    "future_work": "future_work",
    "assumptions_and_guarantees": "assumption",
}


def embed_batch(texts, key, context, attempt=1):
    body = json.dumps({"model": MODEL, "input": texts}).encode("utf-8")
    req = urllib.request.Request(
        URL,
        data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=180, context=context) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        if exc.code in (429, 500, 503) and attempt < 6:
            time.sleep(min(2 ** attempt, 30))
            return embed_batch(texts, key, context, attempt + 1)
        raise SystemExit(f"embedding HTTP {exc.code}: {detail}") from None
    except (urllib.error.URLError, TimeoutError, ConnectionError, http.client.RemoteDisconnected) as exc:
        if attempt < 6:
            time.sleep(min(2 ** attempt, 30))
            return embed_batch(texts, key, context, attempt + 1)
        raise SystemExit(f"embedding connection failed: {exc}") from None
    rows = sorted(payload["data"], key=lambda row: row["index"])
    return np.asarray([row["embedding"] for row in rows], dtype=np.float32), payload["usage"]["total_tokens"]


def sentence(cache, arxiv_id, number):
    if arxiv_id not in cache:
        rows = {}
        with (SENT_DIR / f"{arxiv_id}.jsonl").open(encoding="utf-8") as fh:
            for line in fh:
                row = json.loads(line)
                rows[row["n"]] = row["original"]
        cache[arxiv_id] = rows
    return cache[arxiv_id].get(number, "")


def paper_text(rec, abstract):
    facets = rec["facets"]
    questions = "; ".join(item["label"] for item in facets["research_question"][:4])
    contributions = "; ".join(item["label"] for item in facets["claimed_contributions"][:4])
    return f"Title: {rec['title']}\nAbstract: {abstract}\nQuestions: {questions}\nContributions: {contributions}"


def claim_text(kind, label, original):
    return f"{kind}: {label}\n{original}"[:1000]


def write_vectors(name, ids, texts, key, context):
    finished = OUT / f"{name}_vectors.npy"
    id_path = OUT / f"{name}_ids.json"
    if finished.exists() and id_path.exists():
        existing = json.loads(id_path.read_text(encoding="utf-8"))
        if existing == ids:
            matrix = np.load(finished)
            print(f"{name} already done {len(ids)}", flush=True)
            return 0, int(matrix.shape[1])
    partial = OUT / f"{name}_partial.npy"
    done = 0
    if partial.exists() and (OUT / f"{name}_ids.json").exists():
        existing_ids = json.loads((OUT / f"{name}_ids.json").read_text(encoding="utf-8"))
        if existing_ids == ids[: len(existing_ids)]:
            done = len(existing_ids)
            vectors = [np.load(partial)]
            print(f"{name} resuming at {done}/{len(texts)}", flush=True)
        else:
            vectors = []
    else:
        vectors = []
    tokens = 0
    for start in range(done, len(texts), BATCH):
        batch, used = embed_batch(texts[start : start + BATCH], key, context)
        vectors.append(batch)
        tokens += used
        matrix = np.vstack(vectors)
        np.save(partial, matrix)
        (OUT / f"{name}_ids.json").write_text(
            json.dumps(ids[: start + len(batch)], ensure_ascii=False), encoding="utf-8"
        )
        print(f"{name} {start + len(batch)}/{len(texts)}", flush=True)
    matrix = np.vstack(vectors)
    np.save(OUT / f"{name}_vectors.npy", matrix)
    (OUT / f"{name}_ids.json").write_text(json.dumps(ids, ensure_ascii=False), encoding="utf-8")
    if partial.exists():
        partial.unlink()
    return tokens, int(matrix.shape[1])


def main():
    key = load_env().get("OPENAI_API_KEY", "")
    if not key:
        raise SystemExit("OPENAI_API_KEY is missing from .env")
    abstracts = {}
    with CORPUS.open(encoding="utf-8") as fh:
        for line in fh:
            rec = json.loads(line)
            abstracts[rec["arxiv_id"]] = rec.get("abstract") or ""
    cache = {}
    paper_ids, paper_texts = [], []
    claim_ids, claim_texts = [], []
    with CLEAN.open(encoding="utf-8") as fh:
        for line in fh:
            rec = json.loads(line)
            aid = rec["arxiv_id"]
            paper_ids.append(aid)
            paper_texts.append(paper_text(rec, abstracts.get(aid, "")))
            for key_name, kind in CLAIM_LISTS.items():
                for index, item in enumerate(rec["facets"].get(key_name) or []):
                    claim_ids.append(f"{aid}:{kind}:{index}")
                    claim_texts.append(claim_text(kind, item["label"], sentence(cache, aid, item["sentence_number"])))
            cache.pop(aid, None)
    context = ssl.create_default_context(cafile=certifi.where())
    paper_tokens, dim = write_vectors("paper", paper_ids, paper_texts, key, context)
    claim_tokens, _ = write_vectors("claim", claim_ids, claim_texts, key, context)
    summary = {
        "model": MODEL,
        "dimension": dim,
        "papers": len(paper_ids),
        "claims": len(claim_ids),
        "tokens": paper_tokens + claim_tokens,
        "usd": round((paper_tokens + claim_tokens) / 1_000_000 * 0.02, 4),
    }
    (OUT / "node_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
