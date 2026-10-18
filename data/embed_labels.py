"""Embed unique facet labels with text-embedding-3-small. No other model."""

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
OUT_DIR = ROOT / "data" / "extract" / "embeddings"
MODEL = "text-embedding-3-small"
URL = "https://api.openai.com/v1/embeddings"
BATCH = 256
GROUPS = {
    "problem": ("problems_addressed",),
    "method": ("techniques_used", "baselines_compared"),
    "dataset": ("datasets_evaluated",),
    "metric": ("scoring_measures",),
}


def labels_for(keys):
    found = []
    seen = set()
    with CLEAN.open(encoding="utf-8") as fh:
        for line in fh:
            facets = json.loads(line)["facets"]
            for key in keys:
                for item in facets.get(key) or []:
                    label = item["label"].strip()
                    folded = label.casefold()
                    if not folded or folded in seen:
                        continue
                    seen.add(folded)
                    found.append(label)
    return found


def embed_batch(texts, key, context, attempt=1):
    body = json.dumps({"model": MODEL, "input": texts}).encode("utf-8")
    req = urllib.request.Request(
        URL,
        data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=120, context=context) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        if exc.code in (429, 500, 503) and attempt < 6:
            time.sleep(min(2 ** attempt, 30))
            return embed_batch(texts, key, context, attempt + 1)
        raise SystemExit(f"embedding HTTP {exc.code}: {detail}") from None
    rows = sorted(payload["data"], key=lambda row: row["index"])
    return np.asarray([row["embedding"] for row in rows], dtype=np.float32), payload["usage"]["total_tokens"]


def main():
    if MODEL != "text-embedding-3-small":
        raise SystemExit(f"refusing model {MODEL}")
    key = load_env().get("OPENAI_API_KEY", "")
    if not key:
        raise SystemExit("OPENAI_API_KEY is missing from .env")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    context = ssl.create_default_context(cafile=certifi.where())
    total_tokens = 0
    summary = {}
    for name, keys in GROUPS.items():
        labels = labels_for(keys)
        vectors = []
        for start in range(0, len(labels), BATCH):
            batch, tokens = embed_batch(labels[start : start + BATCH], key, context)
            vectors.append(batch)
            total_tokens += tokens
            print(f"{name} {min(start + BATCH, len(labels))}/{len(labels)}", flush=True)
        matrix = np.vstack(vectors)
        np.save(OUT_DIR / f"{name}_vectors.npy", matrix)
        (OUT_DIR / f"{name}_labels.json").write_text(
            json.dumps(labels, ensure_ascii=False), encoding="utf-8"
        )
        summary[name] = {"labels": len(labels), "dimension": int(matrix.shape[1])}
    summary["model"] = MODEL
    summary["tokens"] = total_tokens
    summary["usd"] = round(total_tokens / 1_000_000 * 0.02, 4)
    (OUT_DIR / "label_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
