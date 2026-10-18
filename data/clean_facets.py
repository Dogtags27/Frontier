"""Drop repeated labels and flag survey-like papers. No model call.

Reads the two extraction files and writes data/extract/facets_clean.jsonl,
one paper per line. The extraction files are left as they are.
"""

import json
import re
from pathlib import Path

from r2_config import ROOT

LAYERS = ("foundation", "recent")
OUT = ROOT / "data" / "extract" / "facets_clean.jsonl"
SURVEY = re.compile(r"\b(survey|review|overview|tutorial)\b", re.I)
KEYS = (
    "problems_addressed",
    "research_question",
    "techniques_used",
    "claimed_contributions",
    "datasets_evaluated",
    "baselines_compared",
    "scoring_measures",
    "experimental_setup",
    "reported_results",
    "quantitative_findings",
    "ablation_findings",
    "failure_cases",
    "stated_limits",
    "future_work",
    "assumptions_and_guarantees",
    "reproducibility_details",
)


def dedupe(items):
    kept, seen, dropped = [], set(), 0
    for item in items:
        key = item["label"].strip().casefold()
        if not key or key in seen:
            dropped += 1
            continue
        seen.add(key)
        kept.append(item)
    return kept, dropped


def main():
    papers = dropped = survey = 0
    by_key = {key: 0 for key in KEYS}
    survey_ids = []
    with OUT.open("w", encoding="utf-8") as dst:
        for layer in LAYERS:
            path = ROOT / "data" / "extract" / layer / "facets.jsonl"
            seen = set()
            with path.open(encoding="utf-8") as fh:
                for line in fh:
                    rec = json.loads(line)
                    if "facets" not in rec or rec["arxiv_id"] in seen:
                        continue
                    seen.add(rec["arxiv_id"])
                    facets, paper_dropped = {}, {}
                    for key in KEYS:
                        kept, n = dedupe(rec["facets"].get(key) or [])
                        facets[key] = kept
                        paper_dropped[key] = n
                        dropped += n
                        by_key[key] += n
                    title = rec.get("title") or ""
                    kind = "research"
                    if len(facets["techniques_used"]) >= 20 or SURVEY.search(title):
                        kind = "survey_like"
                        survey += 1
                        survey_ids.append(rec["arxiv_id"])
                    dst.write(
                        json.dumps(
                            {
                                "arxiv_id": rec["arxiv_id"],
                                "title": title,
                                "layer": rec.get("layer") or layer,
                                "paper_kind": kind,
                                "prompt_version": rec.get("prompt_version"),
                                "dropped": paper_dropped,
                                "facets": facets,
                            },
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
                    papers += 1
    print(f"papers {papers} dropped {dropped} survey_like {survey}")
    print("dropped by list", {k: v for k, v in by_key.items() if v})
    print("survey ids", " ".join(survey_ids))


if __name__ == "__main__":
    main()
