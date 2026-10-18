"""D1: foundation layer, recent layer, citation edges. Not product code."""

import json
import random
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
REFS = ROOT / "data" / "extract" / "refs.jsonl"
CORPUS = ROOT / "data" / "extract" / "corpus.jsonl"
CITES = ROOT / "data" / "extract" / "cites.csv"
REPORT = ROOT / "data" / "extract" / "corpus_report.json"
HITS = ROOT / "data" / "extract" / "foundation_hits.json"
FOUNDATION_FILE = ROOT / "data" / "extract" / "foundation.json"
SAMPLED_FILE = ROOT / "data" / "extract" / "sampled.json"

S2 = "https://api.semanticscholar.org/graph/v1"
CTX = ssl.create_default_context(cafile=certifi.where())
UA = "frontier-data-prep/0.1"
SEED = 7
FOUNDATION_N = 300
RECENT_PER_QUARTER = 24
RECENT_N = 672
PER_QUARTER = 80
CAT_CAP_OLD = 16
YEAR_CAP_OLD = 36
CAT_CAP_RECENT = 45
CAT_CAP_ALL = 140

def era(year):
    if year <= 2014:
        return "old"
    if year <= 2020:
        return "middle"
    return "recent"


def quarter_of(created):
    dt = parsedate_to_datetime(created)
    return dt.year, (dt.month - 1) // 3 + 1


def request(url, data=None, timeout=90):
    headers = {"User-Agent": UA}
    body = None
    if data is not None:
        body = json.dumps(data).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=headers)
    delay = 8
    last = None
    for _ in range(12):
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=CTX) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            last = exc
            if exc.code not in (429, 500, 502, 503):
                raise
            print(f"  http {exc.code}, sleep {delay}s", flush=True)
            time.sleep(delay)
            delay = min(delay * 2, 90)
        except urllib.error.URLError as exc:
            last = exc
            print(f"  url error, sleep {delay}s", flush=True)
            time.sleep(delay)
            delay = min(delay * 2, 90)
    raise last


def load_index():
    index = {}
    by_quarter = defaultdict(list)
    with POOL.open(encoding="utf-8") as fh:
        for line in fh:
            rec = json.loads(line)
            aid = rec["arxiv_id"]
            index[aid] = {
                "primary": rec["primary"],
                "year": rec["year"],
                "title": rec["title"],
                "categories": rec["categories"],
                "first_version": rec["first_version"],
            }
            by_quarter[quarter_of(rec["first_version"])].append(aid)
    return index, by_quarter


def arxiv_of(paper):
    if not paper:
        return None
    ext = paper.get("externalIds") or {}
    aid = ext.get("ArXiv")
    if not aid:
        return None
    return aid.split("v")[0].strip()


def fetch_foundation_candidates(index):
    if HITS.exists():
        raw = json.loads(HITS.read_text(encoding="utf-8"))
        print(f"foundation hits cached {len(raw)}", flush=True)
        return {aid: cites for aid, cites in raw.items() if aid in index}
    found = {}
    for year in range(2007, 2020):
        token = None
        got = 0
        for page in range(5):
            params = {
                "query": "computer",
                "year": f"{year}-{year}",
                "fieldsOfStudy": "Computer Science",
                "fields": "title,year,citationCount,externalIds",
                "sort": "citationCount:desc",
            }
            if token:
                params["token"] = token
            url = S2 + "/paper/search/bulk?" + urllib.parse.urlencode(params)
            data = request(url)
            token = data.get("token")
            for paper in data.get("data") or []:
                aid = arxiv_of(paper)
                if not aid or aid not in index or index[aid]["year"] > 2019:
                    continue
                cites = paper.get("citationCount") or 0
                if aid not in found or cites > found[aid]:
                    found[aid] = cites
                    got += 1
            print(f"foundation {year} page {page + 1} pool-hits {got}", flush=True)
            time.sleep(1.5)
            if got >= 80 or not token:
                break
    HITS.write_text(json.dumps(found), encoding="utf-8")
    return found


def choose_foundation(found, index):
    ranked = sorted(found.items(), key=lambda item: item[1], reverse=True)
    chosen = []
    cat_n = Counter()
    year_n = Counter()

    def take(cat_cap, year_cap):
        for aid, cites in ranked:
            if aid in {c[0] for c in chosen}:
                continue
            primary = index[aid]["primary"]
            year = index[aid]["year"]
            if cat_n[primary] >= cat_cap or year_n[year] >= year_cap:
                continue
            chosen.append((aid, cites))
            cat_n[primary] += 1
            year_n[year] += 1
            if len(chosen) >= FOUNDATION_N:
                return

    take(CAT_CAP_OLD, YEAR_CAP_OLD)
    if len(chosen) < FOUNDATION_N:
        take(28, 50)
    return chosen


def sample_recent(index, by_quarter):
    rng = random.Random(SEED)
    picked = []
    for quarter in sorted(q for q in by_quarter if q >= (2020, 1)):
        groups = defaultdict(list)
        for aid in by_quarter[quarter]:
            groups[index[aid]["primary"]].append(aid)
        keys = list(groups)
        rng.shuffle(keys)
        for ids in groups.values():
            rng.shuffle(ids)
        quarter_ids = []
        while len(quarter_ids) < PER_QUARTER and any(groups[k] for k in keys):
            for key in keys:
                if groups[key]:
                    quarter_ids.append(groups[key].pop())
                if len(quarter_ids) >= PER_QUARTER:
                    break
        picked.append((quarter, quarter_ids))
        print(f"sampled {quarter} {len(quarter_ids)}", flush=True)
    return picked


def load_refs():
    got = {}
    if not REFS.exists():
        return got
    with REFS.open(encoding="utf-8") as fh:
        for line in fh:
            rec = json.loads(line)
            got[rec["arxiv_id"]] = rec["refs"]
    return got


def fetch_refs(ids):
    have = load_refs()
    missing = [aid for aid in ids if aid not in have]
    print(f"refs cached {len(have)} to fetch {len(missing)}", flush=True)
    with REFS.open("a", encoding="utf-8") as fh:
        for i, aid in enumerate(missing, 1):
            paper = request(f"{S2}/paper/ARXIV:{aid}?fields=references.externalIds")
            refs = []
            if paper:
                for ref in paper.get("references") or []:
                    rid = arxiv_of(ref)
                    if rid:
                        refs.append(rid)
            have[aid] = refs
            fh.write(json.dumps({"arxiv_id": aid, "refs": refs}) + "\n")
            if i % 20 == 0:
                fh.flush()
                print(f"refs {i}/{len(missing)}", flush=True)
            time.sleep(1.2)
    return have


def choose_recent(sampled, foundation_ids, refs, index):
    foundation_cat = Counter(index[aid]["primary"] for aid in foundation_ids)
    recent_cat = Counter()
    in_set = set(foundation_ids)
    kept = []
    for _quarter, ids in sampled:
        quarter_kept = 0
        for aid in ids:
            if aid not in refs or aid in in_set:
                continue
            primary = index[aid]["primary"]
            if recent_cat[primary] >= CAT_CAP_RECENT:
                continue
            if foundation_cat[primary] + recent_cat[primary] >= CAT_CAP_ALL:
                continue
            cited_here = sum(1 for rid in refs.get(aid, []) if rid in in_set)
            if cited_here < 2:
                continue
            if quarter_kept >= RECENT_PER_QUARTER:
                break
            in_set.add(aid)
            recent_cat[primary] += 1
            kept.append(aid)
            quarter_kept += 1
            if len(kept) >= RECENT_N:
                return kept
    return kept


def write_outputs(index, foundation, recent_ids, refs):
    foundation_ids = [aid for aid, _cites in foundation]
    cites_of = dict(foundation)
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
        for aid in recent_ids:
            rec = rows[aid]
            rec["layer"] = "recent"
            rec["era"] = era(rec["year"])
            rec["citation_count"] = None
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    edges = []
    seen = set()
    for aid in selected:
        for rid in refs.get(aid, []):
            if rid in selected and rid != aid and (aid, rid) not in seen:
                seen.add((aid, rid))
                edges.append((aid, rid))
    with CITES.open("w", encoding="utf-8") as fh:
        fh.write("citing_arxiv_id,cited_arxiv_id\n")
        for citing, cited in edges:
            fh.write(f"{citing},{cited}\n")
    degree = Counter()
    for citing, cited in edges:
        degree[citing] += 1
        degree[cited] += 1
    by_era = Counter(era(index[aid]["year"]) for aid in selected)
    by_primary = Counter(index[aid]["primary"] for aid in selected)
    by_year = Counter(index[aid]["year"] for aid in selected)
    report = {
        "papers": len(selected),
        "foundation": len(foundation_ids),
        "recent": len(recent_ids),
        "edges": len(edges),
        "isolates": sum(1 for aid in selected if degree[aid] == 0),
        "by_era": dict(by_era),
        "by_year": {str(k): v for k, v in sorted(by_year.items())},
        "by_primary": dict(by_primary.most_common()),
        "recent_target": RECENT_N,
        "foundation_target": FOUNDATION_N,
    }
    REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)


def main():
    print("indexing pool", flush=True)
    index, by_quarter = load_index()
    print("pool", len(index), flush=True)
    if FOUNDATION_FILE.exists() and SAMPLED_FILE.exists():
        foundation = json.loads(FOUNDATION_FILE.read_text(encoding="utf-8"))
        sampled = json.loads(SAMPLED_FILE.read_text(encoding="utf-8"))
        sampled = [(tuple(q), ids) for q, ids in sampled]
        print("loaded foundation", len(foundation), "quarters", len(sampled), flush=True)
    else:
        found = fetch_foundation_candidates(index)
        foundation = choose_foundation(found, index)
        print("foundation", len(foundation), flush=True)
        sampled = sample_recent(index, by_quarter)
        FOUNDATION_FILE.write_text(json.dumps(foundation), encoding="utf-8")
        SAMPLED_FILE.write_text(
            json.dumps([[list(q), ids] for q, ids in sampled]),
            encoding="utf-8",
        )
    recent_flat = [aid for _q, ids in sampled for aid in ids]
    wanted = [aid for aid, _c in foundation] + recent_flat
    refs = fetch_refs(wanted)
    recent_ids = choose_recent(sampled, [aid for aid, _c in foundation], refs, index)
    print("recent kept", len(recent_ids), flush=True)
    write_outputs(index, foundation, recent_ids, refs)


if __name__ == "__main__":
    main()
