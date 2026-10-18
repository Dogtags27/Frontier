"""Measure no-cap token counts after each compression stage."""

import json
import statistics
import sys
from multiprocessing import Pool
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from compress_text import page_lines, stages_from_pages

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "data" / "extract" / "corpus.jsonl"
PDF_DIR = ROOT / "data" / "pdfs"
COUNTS = ROOT / "data" / "extract" / "compression_counts.jsonl"
REPORT = ROOT / "data" / "extract" / "compression_report.json"

STAGES = ["raw", "unwrap", "boilerplate", "no_references", "no_citations", "stopwords"]
INSTRUCTION_TOKENS = 1_200
OUTPUT_LIKELY = 1_200
OUTPUT_CAP = 2_500
INPUT_USD_PER_M = 0.40
OUTPUT_USD_PER_M = 1.60
EMBED_USD_PER_M = 0.02
WORKERS = 6

ENC = None


def init_worker():
    global ENC
    import tiktoken

    ENC = tiktoken.get_encoding("o200k_base")


def count_tokens(text):
    if not text or not text.strip():
        return 0
    cleaned = text
    for token in ENC.special_tokens_set:
        if token in cleaned:
            cleaned = cleaned.replace(token, " ")
    return len(ENC.encode(cleaned, disallowed_special=()))


def extract_one(job):
    arxiv_id, abstract, pdf_path = job
    import pymupdf

    try:
        doc = pymupdf.open(pdf_path)
        pages = [page_lines(page) for page in doc]
        raw = "\n".join(page.get_text("text") for page in doc)
        doc.close()
        texts = stages_from_pages(pages)
        texts["raw"] = raw
        abstract_tokens = count_tokens(abstract or "")
        pdf_tokens = {name: count_tokens(texts[name]) for name in STAGES}
        error = None
    except Exception as exc:
        abstract_tokens = 0
        pdf_tokens = {name: 0 for name in STAGES}
        error = f"{type(exc).__name__}: {exc}"
    return {
        "arxiv_id": arxiv_id,
        "abstract_tokens": abstract_tokens,
        "pdf_tokens": pdf_tokens,
        "error": error,
    }


def percentile(values, p):
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * p
    lo = int(rank)
    hi = min(lo + 1, len(ordered) - 1)
    weight = rank - lo
    return round(ordered[lo] * (1 - weight) + ordered[hi] * weight)


def bill(document_tokens, n, output_each, calls):
    scale = calls / n
    input_tokens = round((document_tokens + n * INSTRUCTION_TOKENS) * scale)
    output_tokens = calls * output_each
    input_usd = round(input_tokens / 1_000_000 * INPUT_USD_PER_M, 2)
    output_usd = round(output_tokens / 1_000_000 * OUTPUT_USD_PER_M, 2)
    return {
        "calls": calls,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "input_usd": input_usd,
        "output_usd": output_usd,
        "total_usd": round(input_usd + output_usd, 2),
    }


def build_report(rows):
    n = len(rows)
    stages = {}
    for name in STAGES:
        docs = [row["abstract_tokens"] + row["pdf_tokens"][name] for row in rows]
        pdfs = [row["pdf_tokens"][name] for row in rows]
        document_tokens = sum(docs)
        stages[name] = {
            "pdf_tokens": {
                "min": min(pdfs),
                "median": round(statistics.median(pdfs)),
                "p90": percentile(pdfs, 0.90),
                "max": max(pdfs),
                "sum": sum(pdfs),
            },
            "document_tokens_sum": document_tokens,
            "likely_usd": bill(document_tokens, n, OUTPUT_LIKELY, n)["total_usd"],
            "output_cap_usd": bill(document_tokens, n, OUTPUT_CAP, n)["total_usd"],
            "retry_35_usd": bill(document_tokens, n, OUTPUT_LIKELY, round(n * 1.35))["total_usd"],
            "embedding_usd": round(document_tokens / 1_000_000 * EMBED_USD_PER_M, 2),
            "detail": bill(document_tokens, n, OUTPUT_LIKELY, n),
        }
    raw_sum = stages["raw"]["pdf_tokens"]["sum"]
    for name in STAGES:
        kept = stages[name]["pdf_tokens"]["sum"]
        stages[name]["pdf_tokens_vs_raw"] = round(kept / raw_sum, 3) if raw_sum else None
    return {
        "papers": n,
        "encoding": "o200k_base",
        "document_cap": None,
        "failures": [row["arxiv_id"] for row in rows if row["error"]],
        "instruction_tokens_per_call": INSTRUCTION_TOKENS,
        "likely_output_tokens": OUTPUT_LIKELY,
        "stages": stages,
        "papers_references_shortened": sum(
            1
            for row in rows
            if row["pdf_tokens"]["no_references"] < row["pdf_tokens"]["boilerplate"] * 0.9
        ),
        "pipeline": [
            "unwrap: ligatures, line-break hyphens, collapsed whitespace",
            "boilerplate: arXiv stamp, bare page numbers, repeated running headers",
            "no_references: drop text after the last References or Bibliography heading in the final 55% of the paper",
            "no_citations: drop [12] and (Author et al., 2014) markers",
            "stopwords: basic English stopwords removed; not, no, nor, neither, never, none, without, cannot, and n't forms kept",
        ],
    }


def main():
    done = {}
    if COUNTS.exists():
        with COUNTS.open(encoding="utf-8") as fh:
            for line in fh:
                row = json.loads(line)
                done[row["arxiv_id"]] = row
    jobs = []
    with CORPUS.open(encoding="utf-8") as fh:
        for line in fh:
            rec = json.loads(line)
            aid = rec["arxiv_id"]
            if aid in done:
                continue
            jobs.append((aid, rec.get("abstract") or "", str(PDF_DIR / f"{aid}.pdf")))
    print(f"todo {len(jobs)} already {len(done)}", flush=True)
    if jobs:
        with COUNTS.open("a", encoding="utf-8") as fh, Pool(WORKERS, initializer=init_worker) as pool:
            for i, row in enumerate(pool.imap_unordered(extract_one, jobs, chunksize=4), 1):
                fh.write(json.dumps(row) + "\n")
                fh.flush()
                done[row["arxiv_id"]] = row
                if i % 25 == 0 or i == len(jobs):
                    print(f"compress {i}/{len(jobs)}", flush=True)
    report = build_report(list(done.values()))
    REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({
        name: {
            "pdf_sum": stage["pdf_tokens"]["sum"],
            "vs_raw": stage["pdf_tokens_vs_raw"],
            "median": stage["pdf_tokens"]["median"],
            "likely_usd": stage["likely_usd"],
        }
        for name, stage in report["stages"].items()
    }, indent=2), flush=True)


if __name__ == "__main__":
    main()
