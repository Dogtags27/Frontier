"""R2 settings and the arXiv id to object map. Credentials stay in .env."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env"
CORPUS = ROOT / "data" / "extract" / "corpus.jsonl"
INDEX = ROOT / "data" / "extract" / "r2_index.jsonl"


def load_env(path=ENV_FILE):
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def r2_key(arxiv_id):
    return f"papers/{arxiv_id}.pdf"


def object_url(env, arxiv_id):
    endpoint = env["R2_ENDPOINT"].rstrip("/")
    bucket = env["R2_BUCKET"]
    return f"{endpoint}/{bucket}/{r2_key(arxiv_id)}"


def write_index(env=None):
    env = env or load_env()
    INDEX.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with CORPUS.open(encoding="utf-8") as src, INDEX.open("w", encoding="utf-8") as dst:
        for line in src:
            rec = json.loads(line)
            aid = rec["arxiv_id"]
            row = {
                "arxiv_id": aid,
                "r2_key": r2_key(aid),
                "url": object_url(env, aid),
            }
            dst.write(json.dumps(row) + "\n")
            count += 1
    return count
