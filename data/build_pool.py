"""D1 step 1: stream Cornell arXiv metadata, keep the cs.* pool. Not product code."""

import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = next((ROOT / "data" / "cache" / "kagglehub").rglob("arxiv-metadata-oai-snapshot.json"))
OUT = ROOT / "data" / "extract" / "pool.jsonl"
NEW_ID = re.compile(r"^\d{4}\.\d{4,5}$")

OUT.parent.mkdir(parents=True, exist_ok=True)
kept = 0
seen = 0
years = Counter()
subs = Counter()
latest = ""
with SRC.open(encoding="utf-8") as fh, OUT.open("w", encoding="utf-8") as out:
    for line in fh:
        seen += 1
        rec = json.loads(line)
        cats = (rec.get("categories") or "").split()
        if not cats or not cats[0].startswith("cs."):
            continue
        aid = rec["id"]
        if not NEW_ID.match(aid):
            continue
        versions = rec.get("versions") or []
        created = versions[0]["created"] if versions else ""
        # "Mon, 2 Apr 2007 19:18:42 GMT" -> year
        m = re.search(r"(\d{4})", created)
        year = int(m.group(1)) if m else None
        abstract = re.sub(r"\s+", " ", rec.get("abstract") or "").strip()
        if not abstract or year is None:
            continue
        latest = max(latest, rec.get("update_date") or "")
        years[year] += 1
        subs[cats[0]] += 1
        kept += 1
        out.write(
            json.dumps(
                {
                    "arxiv_id": aid,
                    "title": re.sub(r"\s+", " ", rec.get("title") or "").strip(),
                    "abstract": abstract,
                    "categories": cats,
                    "primary": cats[0],
                    "year": year,
                    "first_version": created,
                    "doi": rec.get("doi"),
                },
                ensure_ascii=False,
            )
            + "\n"
        )

print("scanned", seen, "kept", kept, "latest update_date", latest)
print("by year", dict(sorted(years.items())))
print("top primary", subs.most_common(20))
print("primary categories", len(subs))
