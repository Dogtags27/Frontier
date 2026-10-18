"""Link each claim to that paper's methods, datasets, and metrics.

Sentence-number matches first, then a lexical match against the paper's own
labels. No model call. Writes data/extract/claim_links.jsonl.
"""

import json
import re
from pathlib import Path

from r2_config import ROOT

CLEAN = ROOT / "data" / "extract" / "facets_clean.jsonl"
SENT_DIR = ROOT / "data" / "extract" / "sentences"
OUT = ROOT / "data" / "extract" / "claim_links.jsonl"
REPORT = ROOT / "data" / "extract" / "claim_link_report.json"

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
    "experimental_setup": "setup",
    "reproducibility_details": "reproducibility",
}
TARGET_LISTS = (
    ("techniques_used", "method"),
    ("baselines_compared", "method"),
    ("datasets_evaluated", "dataset"),
    ("scoring_measures", "metric"),
)
ACRONYM = re.compile(r"\b[A-Z][A-Z0-9]{1,}\b")
TOKEN = re.compile(r"[a-z0-9]+")


def norm(text):
    return " ".join(TOKEN.findall(text.casefold()))


def needles(label):
    found = []
    folded = norm(label)
    if len(folded) >= 5:
        found.append(folded)
    for acronym in ACRONYM.findall(label):
        if len(acronym) >= 2:
            found.append(acronym.casefold())
    return found


def original_sentence(arxiv_id, number, cache):
    if arxiv_id not in cache:
        rows = {}
        path = SENT_DIR / f"{arxiv_id}.jsonl"
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                row = json.loads(line)
                rows[row["n"]] = row["original"]
        cache[arxiv_id] = rows
    return cache[arxiv_id].get(number, "")


def link_paper(rec, cache):
    targets = []
    for key, role in TARGET_LISTS:
        for item in rec["facets"].get(key) or []:
            targets.append(
                {
                    "role": role,
                    "label": item["label"],
                    "sentence_number": item["sentence_number"],
                    "needles": needles(item["label"]),
                }
            )
    rows = []
    for key, kind in CLAIM_LISTS.items():
        for item in rec["facets"].get(key) or []:
            links, seen = [], set()
            number = item["sentence_number"]
            haystack = norm(item["label"] + " " + original_sentence(rec["arxiv_id"], number, cache))
            for target in targets:
                identity = (target["role"], target["label"].strip().casefold())
                if identity in seen:
                    continue
                if target["sentence_number"] == number:
                    source = "sentence"
                elif any(needle in haystack for needle in target["needles"]):
                    source = "lexical"
                else:
                    continue
                seen.add(identity)
                links.append(
                    {
                        "role": target["role"],
                        "label": target["label"],
                        "sentence_number": target["sentence_number"],
                        "source": source,
                    }
                )
            rows.append(
                {
                    "arxiv_id": rec["arxiv_id"],
                    "kind": kind,
                    "label": item["label"],
                    "sentence_number": number,
                    "links": links,
                }
            )
    return rows


def main():
    cache = {}
    totals = {kind: {"claims": 0, "linked": 0, "sentence": 0, "lexical": 0} for kind in CLAIM_LISTS.values()}
    written = 0
    with CLEAN.open(encoding="utf-8") as src, OUT.open("w", encoding="utf-8") as dst:
        for line in src:
            rec = json.loads(line)
            for row in link_paper(rec, cache):
                bucket = totals[row["kind"]]
                bucket["claims"] += 1
                if row["links"]:
                    bucket["linked"] += 1
                sources = {link["source"] for link in row["links"]}
                bucket["sentence"] += "sentence" in sources
                bucket["lexical"] += "lexical" in sources
                dst.write(json.dumps(row, ensure_ascii=False) + "\n")
                written += 1
            cache.clear()
    REPORT.write_text(json.dumps(totals, indent=2), encoding="utf-8")
    print(f"rows {written}")
    for kind, bucket in totals.items():
        share = round(100 * bucket["linked"] / bucket["claims"], 1) if bucket["claims"] else 0
        print(f"{kind:16} {bucket['linked']:5}/{bucket['claims']:<5} {share:5}%  sentence {bucket['sentence']} lexical {bucket['lexical']}")


if __name__ == "__main__":
    main()
