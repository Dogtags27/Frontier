"""Recent layer from foundation citation lists. Not product code."""

import json
import os
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from email.utils import parsedate_to_datetime
from pathlib import Path

import certifi

ROOT = Path(__file__).resolve().parents[1]
POOL = ROOT / "data" / "extract" / "pool.jsonl"
FOUNDATION_FILE = ROOT / "data" / "extract" / "foundation.json"
CITERS = ROOT / "data" / "extract" / "citers.jsonl"
REFS = ROOT / "data" / "extract" / "refs.jsonl"
CORPUS = ROOT / "data" / "extract" / "corpus.jsonl"
CITES = ROOT / "data" / "extract" / "cites.csv"
REPORT = ROOT / "data" / "extract" / "corpus_report.json"
PDF_DIR = ROOT / "data" / "pdfs"

S2 = "https://api.semanticscholar.org/graph/v1"
CTX = ssl.create_default_context(cafile=certifi.where())
UA = "frontier-data-prep/0.1"
CITER_LIMIT = 300
YEAR_TARGET = {2020: 90, 2021: 90, 2022: 90, 2023: 100, 2024: 100, 2025: 110, 2026: 120}
# arXiv returns 404 for these PDFs. They are out of the study and must not be reselected.
DROPPED = {"0807.3223", "2106.09974", "2403.01085"}
MIN_TOTAL = 800
MAX_TOTAL = 1000


def choose_recent(foundation_ids, citers, index):
    hits = defaultdict(set)
    for fid, ids in citers.items():
        for cid in ids:
            meta = index.get(cid)
            if not meta or meta["year"] < 2020 or cid in foundation_ids or cid in DROPPED:
                continue
            hits[cid].add(fid)
    by_year = defaultdict(list)
    for aid, fids in hits.items():
        by_year[index[aid]["year"]].append((len(fids), aid))
    for rows in by_year.values():
        rows.sort(reverse=True)

    chosen = []
    chosen_ids = set()
    cat_n = Counter()

    def take(year, target, min_hits):
        got = 0
        for n_hits, aid in by_year.get(year, []):
            if n_hits < min_hits or aid in chosen_ids:
                continue
            primary = index[aid]["primary"]
            if cat_n[primary] >= 160:
                continue
            chosen.append((n_hits, aid))
            chosen_ids.add(aid)
            cat_n[primary] += 1
            got += 1
            if got >= target:
                return

    for year, target in YEAR_TARGET.items():
        take(year, target, 2)
        if sum(1 for _n, aid in chosen if index[aid]["year"] == year) < target:
            take(year, target - sum(1 for _n, aid in chosen if index[aid]["year"] == year), 1)
    if len(foundation_ids) + len(chosen) < MIN_TOTAL:
        for year in sorted(by_year):
            need = MIN_TOTAL - len(foundation_ids) - len(chosen)
            if need <= 0:
                break
            take(year, need, 1)
    room = MAX_TOTAL - len(foundation_ids)
    return chosen[:room]


def era(year):
    if year <= 2014:
        return "old"
    if year <= 2020:
        return "middle"
    return "recent"


def quarter_of(created):
    dt = parsedate_to_datetime(created)
    return dt.year, (dt.month - 1) // 3 + 1


def request(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    delay = 8
    last = None
    for _ in range(12):
        try:
            with urllib.request.urlopen(req, timeout=90, context=CTX) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as exc:
            last = exc
            if exc.code == 404:
                return None
            if exc.code not in (429, 500, 502, 503):
                raise
            print(f"  http {exc.code} sleep {delay}s", flush=True)
            time.sleep(delay)
            delay = min(delay * 2, 90)
        except urllib.error.URLError as exc:
            last = exc
            print(f"  url error sleep {delay}s", flush=True)
            time.sleep(delay)
            delay = min(delay * 2, 90)
    raise last


def load_done():
    done = {}
    if not CITERS.exists():
        return done
    with CITERS.open(encoding="utf-8") as fh:
        for line in fh:
            rec = json.loads(line)
            done[rec["foundation"]] = rec["citers"]
    return done


def fetch_citers(foundation, max_new=120):
    done = load_done()
    # Smaller papers first. Their citation lists still contain 2020-2025.
    ordered = sorted(foundation, key=lambda item: item[1])
    missing = [aid for aid, _c in ordered if aid not in done][:max_new]
    print(f"citers cached {len(done)} fetching {len(missing)}", flush=True)
    with CITERS.open("a", encoding="utf-8") as fh:
        for i, aid in enumerate(missing, 1):
            url = (
                f"{S2}/paper/ARXIV:{aid}/citations?fields="
                "citingPaper.externalIds,citingPaper.year&limit=" + str(CITER_LIMIT)
            )
            data = request(url) or {}
            citers = []
            seen = set()
            for row in data.get("data") or []:
                paper = row.get("citingPaper") or {}
                raw = (paper.get("externalIds") or {}).get("ArXiv")
                if not raw:
                    continue
                cid = raw.split("v")[0].strip()
                if cid in seen or cid == aid:
                    continue
                seen.add(cid)
                citers.append(cid)
            done[aid] = citers
            fh.write(json.dumps({"foundation": aid, "citers": citers}) + "\n")
            fh.flush()
            if i % 10 == 0 or i == len(missing):
                print(f"citers {i}/{len(missing)} last {len(citers)}", flush=True)
            time.sleep(6)
    return done


def load_pool_index():
    index = {}
    with POOL.open(encoding="utf-8") as fh:
        for line in fh:
            rec = json.loads(line)
            index[rec["arxiv_id"]] = {
                "primary": rec["primary"],
                "year": rec["year"],
                "quarter": quarter_of(rec["first_version"]),
                "title": rec["title"],
            }
    return index


def load_foundation_refs(foundation_ids):
    edges = []
    if not REFS.exists():
        return edges
    wanted = set(foundation_ids)
    with REFS.open(encoding="utf-8") as fh:
        for line in fh:
            rec = json.loads(line)
            if rec["arxiv_id"] not in wanted:
                continue
            for rid in rec["refs"]:
                if rid in wanted and rid != rec["arxiv_id"]:
                    edges.append((rec["arxiv_id"], rid))
    return edges


def write_corpus(foundation, recent, citers, index):
    foundation_ids = [aid for aid, _c in foundation]
    cites_of = dict(foundation)
    recent_ids = [aid for _n, aid in recent]
    hit_of = defaultdict(set)
    for fid, ids in citers.items():
        for cid in ids:
            if cid in set(recent_ids):
                hit_of[cid].add(fid)
    selected = set(foundation_ids) | set(recent_ids)
    rows = {}
    with POOL.open(encoding="utf-8") as fh:
        for line in fh:
            rec = json.loads(line)
            if rec["arxiv_id"] in selected:
                rows[rec["arxiv_id"]] = rec
    with CORPUS.open("w", encoding="utf-8") as fh:
        for aid, cites in foundation:
            rec = rows[aid]
            rec["layer"] = "foundation"
            rec["era"] = era(rec["year"])
            rec["citation_count"] = cites
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        for _n, aid in recent:
            rec = rows[aid]
            rec["layer"] = "recent"
            rec["era"] = era(rec["year"])
            rec["citation_count"] = None
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    edges = []
    seen = set()
    for citing, cited in load_foundation_refs(foundation_ids):
        if (citing, cited) not in seen:
            seen.add((citing, cited))
            edges.append((citing, cited))
    for aid in recent_ids:
        for fid in hit_of[aid]:
            if (aid, fid) not in seen:
                seen.add((aid, fid))
                edges.append((aid, fid))
    with CITES.open("w", encoding="utf-8") as fh:
        fh.write("citing_arxiv_id,cited_arxiv_id\n")
        for citing, cited in edges:
            fh.write(f"{citing},{cited}\n")
    degree = Counter()
    for citing, cited in edges:
        degree[citing] += 1
        degree[cited] += 1
    report = {
        "papers": len(selected),
        "foundation": len(foundation_ids),
        "recent": len(recent_ids),
        "with_arxiv_id": len(selected),
        "edges": len(edges),
        "isolates": sum(1 for aid in selected if degree[aid] == 0),
        "recent_citing_at_least_two": sum(1 for n, _a in recent if n >= 2),
        "by_era": dict(Counter(era(index[a]["year"]) for a in selected)),
        "by_year": {
            str(k): v
            for k, v in sorted(Counter(index[a]["year"] for a in selected).items())
        },
        "by_primary": dict(Counter(index[a]["primary"] for a in selected).most_common()),
        "by_quarter_recent": {
            str(k): v
            for k, v in sorted(Counter(index[a]["quarter"] for a in recent_ids).items())
        },
    }
    REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)


def download_pdfs(ids):
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    failures = []
    for i, aid in enumerate(ids, 1):
        dest = PDF_DIR / f"{aid.replace('/', '_')}.pdf"
        if dest.exists() and dest.stat().st_size > 1000:
            continue
        url = f"https://arxiv.org/pdf/{aid}.pdf"
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=90, context=CTX) as resp:
                blob = resp.read()
            if not blob.startswith(b"%PDF"):
                failures.append(aid)
            else:
                dest.write_bytes(blob)
        except Exception as exc:
            failures.append(aid)
            print(f"pdf fail {aid} {exc}", flush=True)
        if i % 25 == 0:
            print(f"pdf {i}/{len(ids)}", flush=True)
        time.sleep(3)
    print(f"pdf failures {len(failures)}", flush=True)
    (ROOT / "data" / "extract" / "pdf_failures.json").write_text(
        json.dumps(failures), encoding="utf-8"
    )


def main():
    foundation = [
        pair
        for pair in json.loads(FOUNDATION_FILE.read_text(encoding="utf-8"))
        if pair[0] not in DROPPED
    ]
    foundation_ids = [aid for aid, _c in foundation]
    citers = fetch_citers(foundation, max_new=0 if os.environ.get("CORPUS_ONLY") else 120)
    print("indexing pool", flush=True)
    index = load_pool_index()
    recent = choose_recent(set(foundation_ids), citers, index)
    print("recent", len(recent), "total", len(foundation_ids) + len(recent), flush=True)
    write_corpus(foundation, recent, citers, index)
    ids = foundation_ids + [aid for _n, aid in recent]
    download_pdfs(ids)


if __name__ == "__main__":
    main()
