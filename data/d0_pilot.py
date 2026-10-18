"""D0 pilot. --prepare builds compressed inputs. --run calls gpt-4.1-mini once per paper."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pymupdf

from compress_text import extraction_document, page_lines
from extract_client import interpret_response, post_completion, request_body, ssl_context
from extract_prompt import MODEL, PROMPT_VERSION, SYSTEM, numbered
from r2_config import ROOT, load_env

CORPUS = ROOT / "data" / "extract" / "corpus.jsonl"
PDF_DIR = ROOT / "data" / "pdfs"
PAPERS = ROOT / "data" / "extract" / "d0_papers.json"
OUT_DIR = ROOT / "data" / "extract" / "d0"
READY = OUT_DIR / "ready.json"


def load_corpus():
    rows = {}
    with CORPUS.open(encoding="utf-8") as fh:
        for line in fh:
            rec = json.loads(line)
            rows[rec["arxiv_id"]] = rec
    return rows


def count_tokens(enc, text):
    cleaned = text
    for token in enc.special_tokens_set:
        if token in cleaned:
            cleaned = cleaned.replace(token, " ")
    return len(enc.encode(cleaned, disallowed_special=()))


def prepare():
    import tiktoken

    enc = tiktoken.get_encoding("o200k_base")
    corpus = load_corpus()
    papers = json.loads(PAPERS.read_text(encoding="utf-8"))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    instruction_tokens = count_tokens(enc, SYSTEM)
    rows = []
    for paper in papers:
        aid = paper["arxiv_id"]
        rec = corpus[aid]
        doc = pymupdf.open(PDF_DIR / f"{aid}.pdf")
        pages = [page_lines(page) for page in doc]
        doc.close()
        sentences = extraction_document(rec.get("abstract") or "", pages)
        user = numbered(sentences)
        user_tokens = count_tokens(enc, user)
        payload = {
            "arxiv_id": aid,
            "title": rec["title"],
            "prompt_version": PROMPT_VERSION,
            "model": MODEL,
            "sentences": sentences,
            "instruction_tokens": instruction_tokens,
            "user_tokens": user_tokens,
            "input_tokens": instruction_tokens + user_tokens,
        }
        (OUT_DIR / f"{aid}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        rows.append(
            {
                "arxiv_id": aid,
                "title": rec["title"],
                "sentences": len(sentences),
                "instruction_tokens": instruction_tokens,
                "user_tokens": user_tokens,
                "input_tokens": instruction_tokens + user_tokens,
            }
        )
        print(f"{aid} sentences {len(sentences)} input {instruction_tokens + user_tokens}", flush=True)
    summary = {
        "prompt_version": PROMPT_VERSION,
        "model": MODEL,
        "instruction_tokens": instruction_tokens,
        "papers": rows,
        "input_tokens": sum(row["input_tokens"] for row in rows),
    }
    READY.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)
    return summary


def run_calls():
    if MODEL != "gpt-4.1-mini":
        raise SystemExit(f"refusing model {MODEL}")
    env = load_env()
    key = env.get("OPENAI_API_KEY", "")
    if not key:
        raise SystemExit("OPENAI_API_KEY is missing from .env")
    prepare()
    papers = json.loads(PAPERS.read_text(encoding="utf-8"))
    if len(papers) != 10:
        raise SystemExit(f"refusing to call: pilot list has {len(papers)} papers, expected 10")
    ctx = ssl_context()
    for paper in papers:
        aid = paper["arxiv_id"]
        payload = json.loads((OUT_DIR / f"{aid}.json").read_text(encoding="utf-8"))
        body_obj = request_body(payload["sentences"])
        if body_obj["model"] != "gpt-4.1-mini":
            raise SystemExit("refusing request model")
        try:
            raw = post_completion(payload["sentences"], key, ctx)
        except Exception as exc:
            detail = getattr(exc, "detail", str(exc))
            (OUT_DIR / f"{aid}.error.json").write_text(str(detail)[:2000], encoding="utf-8")
            raise SystemExit(f"API error on {aid}. Stopped. No further calls.") from exc
        interpreted = interpret_response(raw, payload["sentences"])
        result = {
            "arxiv_id": aid,
            "prompt_version": PROMPT_VERSION,
            "model": MODEL,
            **interpreted,
        }
        (OUT_DIR / f"{aid}.result.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(aid, "finish", interpreted["finish_reason"], "errors", len(interpreted["errors"]), "usage", interpreted["usage"], flush=True)


if __name__ == "__main__":
    if "--run" in sys.argv:
        run_calls()
    else:
        prepare()
