"""D3: PDF text token counts and the 20,000-token cap. Not product code."""

import json
import statistics
from multiprocessing import Pool
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "data" / "extract" / "corpus.jsonl"
PDF_DIR = ROOT / "data" / "pdfs"
COUNTS = ROOT / "data" / "extract" / "paper_tokens.jsonl"
REPORT = ROOT / "data" / "extract" / "token_report.json"

CAP = 20_000
INSTRUCTION_TOKENS = 1_200
OUTPUT_LIKELY = 1_200
OUTPUT_CAP = 2_500
INPUT_USD_PER_M = 0.40
CACHED_INPUT_USD_PER_M = 0.10
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

    error = None
    pages = 0
    text = ""
    try:
        doc = pymupdf.open(pdf_path)
        pages = doc.page_count
        text = "\n".join(page.get_text("text") for page in doc)
        doc.close()
        abstract_tokens = count_tokens(abstract or "")
        pdf_tokens = count_tokens(text)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        abstract_tokens = 0
        pdf_tokens = 0
    room = max(0, CAP - abstract_tokens)
    pdf_kept = min(pdf_tokens, room)
    return {
        "arxiv_id": arxiv_id,
        "pages": pages,
        "abstract_tokens": abstract_tokens,
        "pdf_tokens": pdf_tokens,
        "pdf_tokens_kept": pdf_kept,
        "document_tokens_raw": abstract_tokens + pdf_tokens,
        "document_tokens_capped": abstract_tokens + pdf_kept,
        "tokens_dropped": pdf_tokens - pdf_kept,
        "capped": pdf_tokens > room,
        "cut_policy": "front_kept_tail_dropped" if pdf_tokens > room else None,
        "empty_text": error is None and pdf_tokens == 0,
        "error": error,
    }


def percentile(values, p):
    ordered = sorted(values)
    if not ordered:
        return None
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * p
    lo = int(rank)
    hi = min(lo + 1, len(ordered) - 1)
    weight = rank - lo
    return round(ordered[lo] * (1 - weight) + ordered[hi] * weight)


def summary(values):
    return {
        "min": min(values),
        "median": round(statistics.median(values)),
        "p90": percentile(values, 0.90),
        "p95": percentile(values, 0.95),
        "max": max(values),
        "sum": sum(values),
    }


def usd(tokens, rate):
    return round(tokens / 1_000_000 * rate, 2)


def build_report(rows):
    capped = [row for row in rows if row["capped"]]
    failures = [row["arxiv_id"] for row in rows if row["error"]]
    empty = [row["arxiv_id"] for row in rows if row["empty_text"]]
    n = len(rows)
    doc = sum(row["document_tokens_capped"] for row in rows)
    instruction = n * INSTRUCTION_TOKENS
    input_tokens = doc + instruction
    raw_doc = sum(row["document_tokens_raw"] for row in rows)
    raw_input = raw_doc + instruction

    def bill(input_tokens, output_each, calls):
        out = calls * output_each
        return {
            "calls": calls,
            "input_tokens": input_tokens if calls == n else round(input_tokens * calls / n),
            "output_tokens": out,
            "input_usd": usd(input_tokens if calls == n else input_tokens * calls / n, INPUT_USD_PER_M),
            "output_usd": usd(out, OUTPUT_USD_PER_M),
            "total_usd": round(
                usd(input_tokens if calls == n else input_tokens * calls / n, INPUT_USD_PER_M)
                + usd(out, OUTPUT_USD_PER_M),
                2,
            ),
        }

    likely_calls = n
    retry_calls = round(n * 1.35)
    return {
        "papers": n,
        "encoding": "o200k_base",
        "model": "gpt-4.1-mini",
        "document_cap_tokens": CAP,
        "cut_policy": "front_kept_tail_dropped",
        "extract_failures": failures,
        "empty_text": empty,
        "abstract_tokens": summary([row["abstract_tokens"] for row in rows]),
        "pdf_tokens": summary([row["pdf_tokens"] for row in rows]),
        "document_tokens_before_cap": summary([row["document_tokens_raw"] for row in rows]),
        "document_tokens_after_cap": summary([row["document_tokens_capped"] for row in rows]),
        "over_cap": len(capped),
        "tokens_dropped": sum(row["tokens_dropped"] for row in rows),
        "capped_papers": [
            {
                "arxiv_id": row["arxiv_id"],
                "abstract_tokens": row["abstract_tokens"],
                "pdf_tokens": row["pdf_tokens"],
                "pdf_tokens_kept": row["pdf_tokens_kept"],
                "tokens_dropped": row["tokens_dropped"],
                "cut_policy": row["cut_policy"],
            }
            for row in sorted(capped, key=lambda row: row["tokens_dropped"], reverse=True)
        ],
        "rates_usd_per_million": {
            "input": INPUT_USD_PER_M,
            "cached_input": CACHED_INPUT_USD_PER_M,
            "output": OUTPUT_USD_PER_M,
            "embedding_text_embedding_3_small": EMBED_USD_PER_M,
        },
        "assumptions": {
            "instruction_tokens_per_call": INSTRUCTION_TOKENS,
            "likely_output_tokens": OUTPUT_LIKELY,
            "output_cap_tokens": OUTPUT_CAP,
            "instruction_note": "Instruction size is the planned prompt, not a measured prompt. D0 replaces it.",
        },
        "extraction_cost_usd": {
            "capped_likely_output": bill(input_tokens, OUTPUT_LIKELY, likely_calls),
            "capped_output_at_cap": bill(input_tokens, OUTPUT_CAP, likely_calls),
            "capped_likely_plus_35pct_retry": bill(input_tokens, OUTPUT_LIKELY, retry_calls),
            "uncapped_likely_output": bill(raw_input, OUTPUT_LIKELY, likely_calls),
        },
        "embedding_capped_text_usd": usd(doc, EMBED_USD_PER_M),
        "cached_instruction_savings_usd": round(
            n * INSTRUCTION_TOKENS / 1_000_000 * (INPUT_USD_PER_M - CACHED_INPUT_USD_PER_M),
            2,
        ),
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
                    print(f"tokens {i}/{len(jobs)}", flush=True)
    rows = list(done.values())
    report = build_report(rows)
    REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    cost = report["extraction_cost_usd"]
    print(
        json.dumps(
            {
                "papers": report["papers"],
                "failures": len(report["extract_failures"]),
                "empty": len(report["empty_text"]),
                "over_cap": report["over_cap"],
                "pdf_tokens": report["pdf_tokens"],
                "document_before": report["document_tokens_before_cap"],
                "document_after": report["document_tokens_after_cap"],
                "likely_usd": cost["capped_likely_output"]["total_usd"],
                "cap_output_usd": cost["capped_output_at_cap"]["total_usd"],
                "retry_usd": cost["capped_likely_plus_35pct_retry"]["total_usd"],
                "uncapped_usd": cost["uncapped_likely_output"]["total_usd"],
            },
            indent=2,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
