"""D1: map demo-slice MAG ids to arXiv ids. Not product code."""

import json
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from difflib import SequenceMatcher
from pathlib import Path

import certifi

SSL_CTX = ssl.create_default_context(cafile=certifi.where())

ROOT = Path(__file__).resolve().parents[1]
PAPERS = ROOT / "data" / "demo" / "papers.jsonl"
OUT = ROOT / "data" / "extract" / "arxiv_ids.jsonl"
REPORT = ROOT / "data" / "extract" / "arxiv_ids_report.json"

OPENALEX = "https://api.openalex.org/works"
BATCH = 40
TITLE_MATCH_MIN = 0.80
TITLE_SEARCH_MIN = 0.93
TITLE_SEARCH_MARGIN = 0.05
UA = "frontier-data-prep/0.1 (hackathon corpus resolve; contact local)"

ARXIV_ID_RE = re.compile(
    r"(?:arxiv\.org/(?:abs|pdf|html)/|10\.48550/arxiv\.)"
    r"([0-9]{4}\.[0-9]{4,5}|[a-z-]+/[0-9]{7})",
    re.I,
)
STOP = {
    "a", "an", "the", "of", "for", "and", "on", "in", "with", "to", "via",
    "from", "using", "based", "by", "into", "over", "its", "their", "our",
}


def norm_title(text):
    text = (text or "").lower().replace("+", "")
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def title_score(ours, theirs):
    a, b = norm_title(ours), norm_title(theirs)
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def accept_title(score, margin, ours, theirs):
    a, b = norm_title(ours), norm_title(theirs)
    prefix = bool(a and b) and (a.startswith(b) or b.startswith(a))
    if score >= TITLE_SEARCH_MIN and margin >= TITLE_SEARCH_MARGIN:
        return True
    # Slice titles sometimes drop a subtitle, so a long shared prefix is still one paper.
    return prefix and score >= 0.85 and margin >= 0.15 and min(len(a), len(b)) >= 40
    words = [
        w
        for w in norm_title(title).split()
        if w not in STOP and len(w) > 2 and not w.isdigit()
    ]
    words = words[:8] or norm_title(title).split()[:6]
    return "+AND+".join(f"ti:{w}" for w in words)


def get_json(url, timeout=45):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    last = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as exc:
            last = exc
            if exc.code not in (429, 500, 502, 503):
                raise
            time.sleep(2 ** attempt)
        except urllib.error.URLError as exc:
            last = exc
            time.sleep(2 ** attempt)
    raise last


def arxiv_ids_from_work(work):
    found = []
    for loc in work.get("locations") or []:
        for url in (loc.get("landing_page_url"), loc.get("pdf_url")):
            if not url:
                continue
            match = ARXIV_ID_RE.search(url)
            if match:
                found.append(match.group(1).lower())
    return list(dict.fromkeys(found))


def lookup_batches(papers):
    by_mag = {}
    ids = [p["mag_id"] for p in papers]
    for start in range(0, len(ids), BATCH):
        chunk = ids[start : start + BATCH]
        filt = "ids.mag:" + "|".join(chunk)
        cursor = "*"
        got_all = []
        while cursor:
            query = urllib.parse.urlencode(
                {
                    "filter": filt,
                    "per-page": "100",
                    "cursor": cursor,
                    "select": "display_name,ids,locations,publication_year",
                }
            )
            data = get_json(f"{OPENALEX}?{query}")
            page = data.get("results") or []
            got_all.extend(page)
            meta = data.get("meta") or {}
            cursor = meta.get("next_cursor") if len(got_all) < (meta.get("count") or 0) else None
        print(
            f"batch {start} requested {len(chunk)} returned {len(got_all)}",
            flush=True,
        )
        for work in got_all:
            mag = str((work.get("ids") or {}).get("mag") or "")
            if mag:
                by_mag[mag] = work
        time.sleep(0.2)
    return by_mag


def classify(paper, work):
    base = {
        "mag_id": paper["mag_id"],
        "title": paper["title"],
        "year": paper["year"],
        "role": paper["role"],
        "arxiv_id": None,
        "match_score": 0.0,
        "match_method": None,
        "status": "unmatched",
        "pdf": False,
        "candidates": [],
    }
    if work is None:
        return base
    ids = arxiv_ids_from_work(work)
    score = round(title_score(paper["title"], work.get("display_name") or ""), 4)
    base["match_score"] = score
    base["candidates"] = ids
    base["openalex_title"] = work.get("display_name")
    if len(ids) == 1 and score >= TITLE_MATCH_MIN:
        base.update(
            arxiv_id=ids[0],
            match_method="openalex_mag",
            status="matched",
            pdf=True,
        )
    elif len(ids) >= 1:
        base.update(match_method="openalex_mag", status="ambiguous", pdf=False)
    else:
        base.update(match_method="openalex_mag_no_arxiv", status="unmatched", pdf=False)
    return base


def write_rows(rows):
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    counts = {}
    for row in rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    report = {
        "papers": len(rows),
        "matched": counts.get("matched", 0),
        "ambiguous": counts.get("ambiguous", 0),
        "unmatched": counts.get("unmatched", 0),
        "title_match_min": TITLE_MATCH_MIN,
        "title_search_min": TITLE_SEARCH_MIN,
        "methods": {},
    }
    for row in rows:
        key = row["match_method"] or "none"
        report["methods"][key] = report["methods"].get(key, 0) + 1
    REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)


def load_rows():
    return [
        json.loads(line)
        for line in OUT.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def openalex_title_search(title):
    query = urllib.parse.urlencode(
        {"search": title, "per-page": "5", "select": "display_name,ids,locations"}
    )
    data = get_json(f"{OPENALEX}?{query}")
    candidates = []
    for work in data.get("results") or []:
        ids = arxiv_ids_from_work(work)
        if len(ids) != 1:
            continue
        candidates.append(
            (title_score(title, work.get("display_name") or ""), ids[0], work.get("display_name") or "")
        )
    candidates.sort(key=lambda row: row[0], reverse=True)
    return candidates


def run_fallback(rows):
    need_search = [r for r in rows if r["status"] != "matched"]
    print(f"title fallback {len(need_search)}", flush=True)
    for i, row in enumerate(need_search, 1):
        try:
            candidates = openalex_title_search(row["title"])
        except Exception as exc:
            row["title_search_error"] = str(exc)
            print(f"fallback {i}/{len(need_search)} error {exc}", flush=True)
            time.sleep(1)
            continue
        time.sleep(0.15)
        scored = [(round(s, 4), aid, t) for s, aid, t in candidates]
        row["title_search"] = scored[:3]
        if not scored:
            print(f"fallback {i}/{len(need_search)} miss", flush=True)
            continue
        best = scored[0]
        second_score = scored[1][0] if len(scored) > 1 else 0.0
        margin = best[0] - second_score
        if accept_title(best[0], margin, row["title"], best[2]):
            row.update(
                arxiv_id=best[1],
                match_score=best[0],
                match_method="openalex_title",
                status="matched",
                pdf=True,
                candidates=[best[1]],
            )
        elif best[0] >= TITLE_MATCH_MIN and row["status"] == "unmatched":
            row.update(
                match_score=best[0],
                match_method="openalex_title",
                status="ambiguous",
                pdf=False,
                candidates=[c[1] for c in scored[:3]],
            )
        print(f"fallback {i}/{len(need_search)} {row['status']} {best[0]} {best[1]}", flush=True)
        if i % 50 == 0:
            write_rows(rows)


def main():
    if "--fallback-only" in sys.argv:
        rows = load_rows()
        run_fallback(rows)
        write_rows(rows)
        return

    papers = [
        json.loads(line)
        for line in PAPERS.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    works = lookup_batches(papers)
    rows = [classify(paper, works.get(paper["mag_id"])) for paper in papers]
    write_rows(rows)
    if "--openalex-only" in sys.argv:
        return
    run_fallback(rows)
    write_rows(rows)


if __name__ == "__main__":
    main()
