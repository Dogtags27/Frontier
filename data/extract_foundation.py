"""Extract facets for one corpus layer. One paper per model call.

Each finished call is appended to that layer's jsonl and flushed, so a stop
keeps the lines already written. The other layer's file is not opened.

    python data/extract_foundation.py --layer foundation
    python data/extract_foundation.py --run --layer recent --workers 8

A paper already present for this prompt version is skipped, so a second --run
continues. A line that failed before a reply is not skipped.
"""

import json
import os
import sys
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pymupdf

from compress_text import extraction_document, page_lines
from extract_client import ALLOWED_MODEL, CallError, interpret_response, post_completion, ssl_context
from extract_prompt import MODEL, PROMPT_VERSION
from r2_config import ROOT, load_env

CORPUS = ROOT / "data" / "extract" / "corpus.jsonl"
PDF_DIR = ROOT / "data" / "pdfs"
DEFAULT_WORKERS = 8
MAX_ATTEMPTS = 5
LAYER = "foundation"
OUT_DIR = ROOT / "data" / "extract" / "foundation"
FACETS = OUT_DIR / "facets.jsonl"
FAILURES = OUT_DIR / "failures.jsonl"


def configure(layer):
    global LAYER, OUT_DIR, FACETS, FAILURES
    if layer not in {"foundation", "recent"}:
        raise SystemExit("layer must be foundation or recent")
    LAYER = layer
    OUT_DIR = ROOT / "data" / "extract" / layer
    FACETS = OUT_DIR / "facets.jsonl"
    FAILURES = OUT_DIR / "failures.jsonl"


def count_layers():
    foundation = 0
    recent = 0
    with CORPUS.open(encoding="utf-8") as fh:
        for line in fh:
            layer = json.loads(line).get("layer")
            if layer == "foundation":
                foundation += 1
            elif layer == "recent":
                recent += 1
    return foundation, recent


def iter_layer():
    """Yield one paper from the selected layer. The other layer is skipped."""
    with CORPUS.open(encoding="utf-8") as fh:
        for line in fh:
            rec = json.loads(line)
            if rec.get("layer") != LAYER:
                continue
            yield {
                "arxiv_id": rec["arxiv_id"],
                "title": rec.get("title") or "",
                "abstract": rec.get("abstract") or "",
            }


def repair_tail(path):
    """Drop a trailing partial line left by a killed process."""
    if not path.exists():
        return
    with path.open("rb+") as fh:
        fh.seek(0, os.SEEK_END)
        size = fh.tell()
        if size == 0:
            return
        fh.seek(-1, os.SEEK_END)
        if fh.read(1) == b"\n":
            return
        pos = size - 1
        while pos > 0:
            step = min(4096, pos)
            pos -= step
            fh.seek(pos)
            chunk = fh.read(step)
            idx = chunk.rfind(b"\n")
            if idx >= 0:
                fh.truncate(pos + idx + 1)
                return
        fh.truncate(0)


def completed_ids(path):
    """Ids whose latest line for this prompt version already has a reply."""
    found = set()
    if not path.exists():
        return found
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("prompt_version") != PROMPT_VERSION:
                continue
            aid = rec.get("arxiv_id")
            if aid and "facets" in rec:
                found.add(aid)
    return found


def append_jsonl(path, record, lock):
    payload = (json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8")
    with lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("ab") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())


def sentences_for(paper):
    path = PDF_DIR / f"{paper['arxiv_id']}.pdf"
    if not path.exists():
        raise FileNotFoundError(path.name)
    doc = pymupdf.open(path)
    try:
        pages = [page_lines(page) for page in doc]
    finally:
        doc.close()
    return extraction_document(paper["abstract"], pages)


def call_one(paper, api_key, context):
    sentences = sentences_for(paper)
    delay = 2
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            raw = post_completion(sentences, api_key, context)
            break
        except CallError as exc:
            if not exc.retryable or attempt == MAX_ATTEMPTS:
                raise
            time.sleep(exc.retry_after if exc.retry_after is not None else delay)
            delay = min(delay * 2, 30)
    interpreted = interpret_response(raw, sentences)
    return {
        "arxiv_id": paper["arxiv_id"],
        "title": paper["title"],
        "layer": LAYER,
        "prompt_version": PROMPT_VERSION,
        "model": MODEL,
        **interpreted,
    }


def extract_one(paper, api_key, context, lock, stop):
    aid = paper["arxiv_id"]
    if stop.is_set():
        return "stopped"
    try:
        record = call_one(paper, api_key, context)
    except CallError as exc:
        append_jsonl(
            FAILURES,
            {
                "arxiv_id": aid,
                "prompt_version": PROMPT_VERSION,
                "status": exc.status,
                "detail": exc.detail,
            },
            lock,
        )
        print(f"{aid} HTTP {exc.status}", flush=True)
        if not exc.retryable:
            stop.set()
        return "error"
    except FileNotFoundError as exc:
        append_jsonl(
            FAILURES,
            {"arxiv_id": aid, "prompt_version": PROMPT_VERSION, "status": "missing_pdf", "detail": str(exc)},
            lock,
        )
        print(f"{aid} missing pdf", flush=True)
        return "error"
    except Exception as exc:
        append_jsonl(
            FAILURES,
            {"arxiv_id": aid, "prompt_version": PROMPT_VERSION, "status": "error", "detail": f"{type(exc).__name__}: {exc}"},
            lock,
        )
        print(f"{aid} {type(exc).__name__}", flush=True)
        return "error"
    append_jsonl(FACETS, record, lock)
    usage = record["usage"]
    print(
        f"{aid} finish {record['finish_reason']} errors {len(record['errors'])} "
        f"prompt {usage.get('prompt_tokens')} completion {usage.get('completion_tokens')}",
        flush=True,
    )
    return "ok"


def tally(finished, ok, failed):
    for future in finished:
        status = future.result()
        if status == "ok":
            ok += 1
        elif status == "error":
            failed += 1
    return ok, failed


def run(workers):
    if MODEL != ALLOWED_MODEL:
        raise SystemExit(f"refusing model {MODEL}")
    key = load_env().get("OPENAI_API_KEY", "")
    if not key:
        raise SystemExit("OPENAI_API_KEY is missing from .env")
    repair_tail(FACETS)
    repair_tail(FAILURES)
    done = completed_ids(FACETS)
    context = ssl_context()
    lock = threading.Lock()
    stop = threading.Event()
    pending = 0
    skipped = 0
    ok = 0
    failed = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        inflight = set()
        for paper in iter_layer():
            if stop.is_set():
                break
            if paper["arxiv_id"] in done:
                skipped += 1
                continue
            inflight.add(pool.submit(extract_one, paper, key, context, lock, stop))
            pending += 1
            if len(inflight) >= workers:
                finished, inflight = wait(inflight, return_when=FIRST_COMPLETED)
                ok, failed = tally(finished, ok, failed)
        if inflight:
            finished, _ = wait(inflight)
            ok, failed = tally(finished, ok, failed)
    print(
        f"done ok {ok} failed {failed} skipped {skipped} submitted {pending} workers {workers}",
        flush=True,
    )


def plan(workers):
    foundation, recent = count_layers()
    done = len(completed_ids(FACETS))
    selected = foundation if LAYER == "foundation" else recent
    other = recent if LAYER == "foundation" else foundation
    print(f"model {MODEL}")
    print(f"prompt {PROMPT_VERSION}")
    print(f"layer {LAYER} papers {selected}")
    print(f"other layer left unread {other}")
    print(f"already written {done}")
    print(f"workers {workers}")
    print(f"facets {FACETS}")
    print("no API call")


if __name__ == "__main__":
    worker_count = DEFAULT_WORKERS
    layer = "foundation"
    if "--workers" in sys.argv:
        worker_count = int(sys.argv[sys.argv.index("--workers") + 1])
    if "--layer" in sys.argv:
        layer = sys.argv[sys.argv.index("--layer") + 1]
    if worker_count < 1:
        raise SystemExit("workers must be at least 1")
    configure(layer)
    if "--run" in sys.argv:
        run(worker_count)
    else:
        plan(worker_count)
