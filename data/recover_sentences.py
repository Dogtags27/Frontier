"""Rebuild the original sentence for every sentence the extractor saw.

Compression only deletes words, so each surviving character is mapped back to
the pre-stopword text. The sentence split is the same function the extractor
used, so the numbers match. Output is one jsonl per paper. No model call.
"""

import json
import re
import sys
from multiprocessing import Pool
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pymupdf

from compress_text import (
    STOPWORDS,
    WORD,
    extraction_document,
    page_lines,
    split_sentences,
    stages_from_pages,
    strip_stopwords,
    unwrap,
)
from r2_config import ROOT

CORPUS = ROOT / "data" / "extract" / "corpus.jsonl"
PDF_DIR = ROOT / "data" / "pdfs"
OUT_DIR = ROOT / "data" / "extract" / "sentences"
REPORT = ROOT / "data" / "extract" / "sentence_report.json"
WORKERS = 6
HYPHEN_RUN = re.compile(r"(?:\s*-\s*){2,}")
MULTI_SPACE = re.compile(r"[ \t]{2,}")


def _resub(text, offsets, pattern, repl):
    parts, out_offsets, last = [], [], 0
    for match in pattern.finditer(text):
        parts.append(text[last : match.start()])
        out_offsets.extend(offsets[last : match.start()])
        parts.append(repl)
        out_offsets.extend([offsets[match.start()]] * len(repl))
        last = match.end()
    parts.append(text[last:])
    out_offsets.extend(offsets[last:])
    return "".join(parts), out_offsets


def strip_with_offsets(text):
    """strip_stopwords, plus the source index of every kept character."""
    chars, offsets = [], []
    for match in WORD.finditer(text):
        token = match.group(0)
        if token.isalpha() and token.lower() in STOPWORDS:
            continue
        chars.extend(token)
        offsets.extend(range(match.start(), match.end()))
    text = "".join(chars)
    text, offsets = _resub(text, offsets, HYPHEN_RUN, "-")
    text, offsets = _resub(text, offsets, MULTI_SPACE, " ")
    lead = len(text) - len(text.lstrip())
    trail = len(text.rstrip())
    return text[lead:trail], offsets[lead:trail]


def _locate(body, sentences):
    spans, pos = [], 0
    for sentence in sentences:
        found = body.find(sentence, pos)
        if found < 0:
            return None
        spans.append((found, found + len(sentence)))
        pos = found + len(sentence)
    return spans


def recover(abstract, pages):
    """Return (compressed sentences, original sentences). Lengths are equal."""
    stages = stages_from_pages(pages)
    abstract_original = unwrap([abstract]) if abstract else ""
    abstract_compressed, abstract_offsets = (
        strip_with_offsets(abstract_original) if abstract_original else ("", [])
    )
    pdf_compressed, pdf_offsets = strip_with_offsets(stages["no_citations"])
    if abstract_compressed != strip_stopwords(abstract_original):
        raise RuntimeError("abstract offset pass drifted from strip_stopwords")
    if pdf_compressed != stages["stopwords"]:
        raise RuntimeError("pdf offset pass drifted from strip_stopwords")

    pieces = []
    if abstract_compressed:
        pieces.append(("ABSTRACT", None, "ABSTRACT"))
        pieces.append((abstract_compressed, abstract_offsets, abstract_original))
    pieces.append(("PAPER", None, "PAPER"))
    pieces.append((pdf_compressed, pdf_offsets, stages["no_citations"]))

    compressed_body, original_body, source_index = "", "", []
    for text, offsets, source in pieces:
        if compressed_body:
            compressed_body += "\n"
            original_body += "\n"
            source_index.append(len(original_body) - 1)
        base = len(original_body)
        if offsets is None:
            source_index.extend(range(base, base + len(text)))
            original_body += source
        else:
            source_index.extend(base + offset for offset in offsets)
            original_body += source
        compressed_body += text

    compressed = split_sentences(compressed_body)
    expected = extraction_document(abstract, pages)
    if compressed != expected:
        raise RuntimeError(f"sentence list drifted ({len(compressed)} vs {len(expected)})")
    spans = _locate(compressed_body, compressed)
    if spans is None:
        raise RuntimeError("a sentence could not be located in the body")

    original, cursor = [], 0
    for _start, end in spans:
        stop = source_index[end - 1] + 1
        original.append(original_body[cursor:stop].strip())
        cursor = stop
    return compressed, original


def _one(job):
    arxiv_id, abstract, pdf_path = job
    try:
        doc = pymupdf.open(pdf_path)
        pages = [page_lines(page) for page in doc]
        doc.close()
        compressed, original = recover(abstract, pages)
    except Exception as exc:
        return {"arxiv_id": arxiv_id, "error": f"{type(exc).__name__}: {exc}"}
    out = OUT_DIR / f"{arxiv_id}.jsonl"
    with out.open("w", encoding="utf-8") as fh:
        for n, (comp, orig) in enumerate(zip(compressed, original)):
            fh.write(
                json.dumps({"n": n, "compressed": comp, "original": orig}, ensure_ascii=False) + "\n"
            )
    return {"arxiv_id": arxiv_id, "sentences": len(compressed), "error": None}


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    jobs = []
    with CORPUS.open(encoding="utf-8") as fh:
        for line in fh:
            rec = json.loads(line)
            jobs.append((rec["arxiv_id"], rec.get("abstract") or "", str(PDF_DIR / f"{rec['arxiv_id']}.pdf")))
    done = 0
    failures = []
    sentences = 0
    with Pool(WORKERS) as pool:
        for result in pool.imap_unordered(_one, jobs, chunksize=4):
            done += 1
            if result["error"]:
                failures.append(result)
                print(f"{result['arxiv_id']} {result['error']}", flush=True)
            else:
                sentences += result["sentences"]
            if done % 100 == 0 or done == len(jobs):
                print(f"{done}/{len(jobs)}", flush=True)
    report = {
        "papers": len(jobs),
        "ok": len(jobs) - len(failures),
        "failures": failures,
        "sentences": sentences,
    }
    REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("papers", "ok", "sentences")}, indent=2), flush=True)
    print(f"failures {len(failures)}", flush=True)


if __name__ == "__main__":
    main()
