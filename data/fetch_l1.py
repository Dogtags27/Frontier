"""Pull L1 citing papers for the Frontier L0 seeds.

Selection per seed, cap 10:
  4 canon: highest cited_by_count, floor 50, surveys skipped when alternatives exist
  3 timeline: highest-cited paper in each of the 3 most recent citing years
  3 diversity: highest-cited papers whose primary topic is not already used
  leftover slots: next-highest cited papers
L0 papers never occupy an L1 slot. A paper reached from two seeds is one node
with two edges.
"""

from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MAILTO = "frontier-hackathon@example.com"
API = "https://api.openalex.org/works"
SELECT = "id,display_name,publication_year,cited_by_count,type,doi,primary_topic,authorships"
SURVEY_RE = re.compile(
    r"\b(a survey|survey on|survey of|systematic review|literature review|a review of|review of)\b",
    re.I,
)

# venue_year is the year we trust. openalex is a hint, possibly wrong.
SEEDS = [
    {"domain": "AI", "key": "alexnet", "year": 2012, "title": "ImageNet Classification with Deep Convolutional Neural Networks", "openalex": "W2163605009"},
    {"domain": "AI", "key": "resnet", "year": 2016, "title": "Deep Residual Learning for Image Recognition", "openalex": "W2194775991"},
    {"domain": "AI", "key": "gan", "year": 2014, "title": "Generative Adversarial Nets", "openalex": None, "arxiv": "1406.2661"},
    {"domain": "AI", "key": "dqn", "year": 2015, "title": "Human-level control through deep reinforcement learning", "openalex": "W2145339207"},
    {"domain": "AI", "key": "vit", "year": 2021, "title": "An Image is Worth 16x16 Words: Transformers for Image Recognition at Scale", "openalex": "W3094502228"},
    {"domain": "NLP", "key": "word2vec", "year": 2013, "title": "Efficient Estimation of Word Representations in Vector Space", "openalex": "W1614298861"},
    {"domain": "NLP", "key": "seq2seq", "year": 2014, "title": "Sequence to Sequence Learning with Neural Networks", "openalex": "W2130942839"},
    {"domain": "NLP", "key": "bahdanau", "year": 2015, "title": "Neural Machine Translation by Jointly Learning to Align and Translate", "openalex": "W2133564696"},
    {"domain": "NLP", "key": "elmo", "year": 2018, "title": "Deep Contextualized Word Representations", "openalex": "W2787560479"},
    {"domain": "NLP", "key": "bert", "year": 2019, "title": "BERT: Pre-training of Deep Bidirectional Transformers for Language Understanding", "openalex": "W2963341956"},
    {"domain": "LLM", "key": "attention", "year": 2017, "title": "Attention Is All You Need", "openalex": "W2626778328", "arxiv": "1706.03762"},
    {"domain": "LLM", "key": "gpt3", "year": 2020, "title": "Language Models are Few-Shot Learners", "openalex": "W3030163527"},
    {"domain": "LLM", "key": "instructgpt", "year": 2022, "title": "Training language models to follow instructions with human feedback", "openalex": "W7133211372"},
    {"domain": "LLM", "key": "llama", "year": 2023, "title": "LLaMA: Open and Efficient Foundation Language Models", "openalex": "W4322718191"},
    {"domain": "LLM", "key": "rag", "year": 2020, "title": "Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks", "openalex": None, "arxiv": "2005.11401"},
    {"domain": "SLM", "key": "distilbert", "year": 2019, "title": "DistilBERT, a distilled version of BERT: smaller, faster, cheaper and lighter", "openalex": "W2978017171"},
    {"domain": "SLM", "key": "tinybert", "year": 2020, "title": "TinyBERT: Distilling BERT for Natural Language Understanding", "openalex": "W3105966348"},
    {"domain": "SLM", "key": "minilm", "year": 2020, "title": "MiniLM: Deep Self-Attention Distillation for Task-Agnostic Compression of Pre-Trained Transformers", "openalex": "W3008374555"},
    {"domain": "SLM", "key": "lora", "year": 2022, "title": "LoRA: Low-Rank Adaptation of Large Language Models", "openalex": None, "arxiv": "2106.09685"},
    {"domain": "SLM", "key": "phi1", "year": 2023, "title": "Textbooks Are All You Need", "openalex": "W4381586770"},
    {"domain": "Graph", "key": "gcn", "year": 2017, "title": "Semi-Supervised Classification with Graph Convolutional Networks", "openalex": "W2519887557"},
    {"domain": "Graph", "key": "graphsage", "year": 2017, "title": "Inductive Representation Learning on Large Graphs", "openalex": "W2624431344"},
    {"domain": "Graph", "key": "gat", "year": 2018, "title": "Graph Attention Networks", "openalex": "W2766453196"},
    {"domain": "Graph", "key": "gin", "year": 2019, "title": "How Powerful are Graph Neural Networks?", "openalex": "W2894175828"},
    {"domain": "Graph", "key": "node2vec", "year": 2016, "title": "node2vec: Scalable Feature Learning for Networks", "openalex": "W2962756421"},
    {"domain": "DBMS", "key": "bigtable", "year": 2006, "title": "Bigtable: A Distributed Storage System for Structured Data", "openalex": "W1981420413"},
    {"domain": "DBMS", "key": "dynamo", "year": 2007, "title": "Dynamo: Amazon's Highly Available Key-value Store", "openalex": None},
    {"domain": "DBMS", "key": "spanner", "year": 2012, "title": "Spanner: Google's Globally Distributed Database", "openalex": "W2013409485"},
    {"domain": "DBMS", "key": "columnstore", "year": 2008, "title": "Column-Stores vs. Row-Stores: How Different Are They Really?", "openalex": "W2005112390"},
    {"domain": "DBMS", "key": "snowflake", "year": 2016, "title": "The Snowflake Elastic Data Warehouse", "openalex": "W2430301697"},
]

# OpenAlex split some papers across rows. These are the rows whose citing edges
# are the real neighborhood. Identity in the output stays the seed title.
CITATION_HUBS = {
    "gan": ["W4298289240", "W2099471712"],
    "dynamo": ["W2153704625"],
}


def is_cs(work: dict) -> bool:
    topic = work.get("primary_topic") or {}
    field = ((topic.get("field") or {}).get("display_name") or "")
    domain = ((topic.get("domain") or {}).get("display_name") or "")
    return field == "Computer Science" or domain == "Computer Science"


def corrupted(work: dict) -> bool:
    """Drop records whose citation mass was attached to an unrelated title.

    The pattern seen on this pull: a preprint with a non-arXiv DOI and a
    citation count in the tens of thousands, while the DOI belongs to a
    different paper.
    """
    cites = work.get("cited_by_count") or 0
    kind = (work.get("type") or "").lower()
    doi = (work.get("doi") or "").lower()
    arxiv = "arxiv" in doi or "10.48550" in doi
    if cites >= 8000 and kind == "preprint" and not arxiv:
        return True
    if cites >= 20000 and not doi:
        return True
    return False


def get(url: str, retries: int = 8) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": f"frontier/0.1 (mailto:{MAILTO})"})
    last = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.load(resp)
        except Exception as exc:  # noqa: BLE001
            last = exc
            wait = min(30, 2 ** attempt)
            print(f"  retry {attempt + 1} in {wait}s: {exc}", flush=True)
            time.sleep(wait)
    raise RuntimeError(f"GET failed {url}: {last}")


def works_url(params: dict) -> str:
    params = dict(params)
    params["mailto"] = MAILTO
    return API + "?" + urllib.parse.urlencode(params, safe=":,|*")


def short_id(value: str | None) -> str | None:
    if not value:
        return None
    return value.rstrip("/").split("/")[-1]


def norm(title: str) -> str:
    title = title.lower().replace("’", "'").replace("（", "(").replace("）", ")")
    return re.sub(r"[^a-z0-9]+", " ", title).strip()


def title_match(a: str, b: str) -> bool:
    return norm(a) == norm(b)


def slim(work: dict) -> dict:
    topic = work.get("primary_topic") or {}
    authors = work.get("authorships") or []
    first = None
    if authors:
        first = (authors[0].get("author") or {}).get("display_name")
    return {
        "id": short_id(work.get("id")),
        "title": work.get("display_name"),
        "year": work.get("publication_year"),
        "cited_by_count": work.get("cited_by_count") or 0,
        "type": work.get("type"),
        "doi": work.get("doi"),
        "topic": topic.get("display_name"),
        "topic_id": short_id(topic.get("id")),
        "first_author": first,
    }


def is_survey(work: dict) -> bool:
    if (work.get("type") or "").lower() == "review":
        return True
    return bool(SURVEY_RE.search(work.get("display_name") or ""))


def fetch_work(openalex_id: str) -> dict:
    url = f"https://api.openalex.org/works/{openalex_id}?mailto={MAILTO}&select=id,display_name,publication_year,cited_by_count,referenced_works,ids"
    time.sleep(0.12)
    return get(url)


def citer_count(openalex_id: str) -> int:
    url = works_url({"filter": f"cites:{openalex_id}", "per-page": "1"})
    time.sleep(0.12)
    return int(get(url).get("meta", {}).get("count") or 0)


def search_exact(title: str) -> list[dict]:
    found: list[dict] = []
    seen: set[str] = set()
    for page in range(1, 4):
        url = works_url({
            "search": title,
            "page": str(page),
            "per-page": "50",
            "select": "id,display_name,publication_year,cited_by_count",
        })
        time.sleep(0.12)
        results = get(url).get("results") or []
        if not results:
            break
        for row in results:
            if not title_match(row.get("display_name") or "", title):
                continue
            sid = short_id(row.get("id"))
            if sid and sid not in seen:
                seen.add(sid)
                found.append(row)
    found.sort(key=lambda row: row.get("cited_by_count") or 0, reverse=True)
    return found


def resolve_from_references(referencer_id: str, title: str) -> str | None:
    work = fetch_work(referencer_id)
    refs = [short_id(r) for r in (work.get("referenced_works") or []) if r]
    found = None
    for i in range(0, len(refs), 50):
        chunk = refs[i : i + 50]
        if not chunk:
            continue
        url = works_url({
            "filter": "openalex:" + "|".join(chunk),
            "per-page": "50",
            "select": "id,display_name,publication_year,cited_by_count",
        })
        time.sleep(0.12)
        for row in get(url).get("results") or []:
            if title_match(row.get("display_name") or "", title):
                if found is None or (row.get("cited_by_count") or 0) > found[0]:
                    found = (row.get("cited_by_count") or 0, short_id(row["id"]), row.get("display_name"))
    return found[1] if found else None


def choose_richest(candidates: list[str], expected_title: str | None = None) -> tuple[str, int, str]:
    best = None
    for cid in candidates:
        work = fetch_work(cid)
        title = work.get("display_name") or ""
        if expected_title and not title_match(title, expected_title):
            continue
        count = citer_count(cid)
        row = (count, cid, title, work.get("publication_year"), work.get("cited_by_count"))
        if best is None or row[0] > best[0]:
            best = row
    if best is None:
        raise RuntimeError(f"no title-matched candidate among {candidates}")
    return best[1], best[0], best[2]


def fetch_top_citers(openalex_id: str, pages: int = 2) -> list[dict]:
    cursor = "*"
    rows: list[dict] = []
    for _ in range(pages):
        url = works_url({
            "filter": f"cites:{openalex_id}",
            "sort": "cited_by_count:desc",
            "per-page": "100",
            "cursor": cursor,
            "select": SELECT,
        })
        time.sleep(0.15)
        payload = get(url)
        rows.extend(payload.get("results") or [])
        cursor = (payload.get("meta") or {}).get("next_cursor")
        if not cursor:
            break
    return rows


def fetch_year_citers(openalex_id: str, year: int) -> list[dict]:
    url = works_url({
        "filter": f"cites:{openalex_id},publication_year:{year}",
        "sort": "cited_by_count:desc",
        "per-page": "15",
        "select": SELECT,
    })
    time.sleep(0.12)
    return get(url).get("results") or []


def recent_years(openalex_id: str) -> list[int]:
    url = works_url({"filter": f"cites:{openalex_id}", "group_by": "publication_year"})
    time.sleep(0.12)
    groups = get(url).get("group_by") or []
    years = []
    for group in groups:
        key = str(group.get("key") or "")
        if key.isdigit() and int(group.get("count") or 0) > 0:
            years.append(int(key))
    years = [y for y in sorted(set(years), reverse=True) if 1990 <= y <= 2026]
    return years[:3]


def usable(work: dict, blocked: set[str]) -> bool:
    sid = short_id(work.get("id"))
    if not sid or sid in blocked or corrupted(work):
        return False
    return True


def prefer_cs(works: list[dict]) -> list[dict]:
    cs = [w for w in works if is_cs(w)]
    return cs if cs else works


def select_l1(pool: list[dict], year_pools: dict[int, list[dict]], blocked: set[str]) -> list[dict]:
    selected: list[dict] = []
    seen = set(blocked)

    def add(work: dict, stratum: str) -> bool:
        sid = short_id(work.get("id"))
        if not sid or sid in seen or not usable(work, blocked):
            return False
        seen.add(sid)
        row = slim(work)
        row["stratum"] = stratum
        row["cs"] = is_cs(work)
        selected.append(row)
        return True

    ranked = sorted(
        [w for w in pool if usable(w, blocked)],
        key=lambda w: w.get("cited_by_count") or 0,
        reverse=True,
    )
    canon_pool = [w for w in ranked if (w.get("cited_by_count") or 0) >= 50]
    canon_pool = prefer_cs(canon_pool)
    non_survey = [w for w in canon_pool if not is_survey(w)]
    use = non_survey if len(non_survey) >= 4 else canon_pool
    for work in use:
        if sum(1 for row in selected if row["stratum"] == "canon") >= 4:
            break
        add(work, "canon")

    for works in year_pools.values():
        ordered = sorted(works, key=lambda w: w.get("cited_by_count") or 0, reverse=True)
        ordered = prefer_cs([w for w in ordered if usable(w, blocked)])
        for work in ordered:
            if add(work, "timeline"):
                break

    taken_topics = {row["topic_id"] for row in selected if row.get("topic_id")}
    diversity_pool = prefer_cs(ranked)
    for work in diversity_pool:
        if sum(1 for row in selected if row["stratum"] == "diversity") >= 3:
            break
        topic = short_id((work.get("primary_topic") or {}).get("id"))
        if not topic or topic in taken_topics:
            continue
        if add(work, "diversity"):
            taken_topics.add(topic)

    for work in prefer_cs(ranked) + ranked:
        if len(selected) >= 10:
            break
        add(work, "fill")
    return selected[:10]


def main() -> None:
    warnings: list[str] = []
    print("resolving seeds", flush=True)

    # GAN via Conditional GAN's reference list when the search records are split.
    gan_from_refs = resolve_from_references("W2125389028", "Generative Adversarial Nets")
    attention_from_refs = resolve_from_references("W2963341956", "Attention Is All You Need")
    lora_from_refs = resolve_from_references("W4322718191", "LoRA: Low-Rank Adaptation of Large Language Models")
    rag_from_refs = resolve_from_references("W3030163527", "Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks")
    if rag_from_refs is None:
        rag_from_refs = resolve_from_references("W7133211372", "Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks")

    resolved_hints = {
        "gan": gan_from_refs,
        "attention": attention_from_refs,
        "lora": lora_from_refs,
        "rag": rag_from_refs,
    }
    print("ref hints", {k: v for k, v in resolved_hints.items()}, flush=True)

    resolved = []
    for seed in SEEDS:
        row = dict(seed)
        if seed["key"] in CITATION_HUBS:
            hubs = CITATION_HUBS[seed["key"]]
            counts = [(hub, citer_count(hub)) for hub in hubs]
            row["hubs"] = [hub for hub, _ in counts]
            row["resolved_id"] = counts[0][0]
            row["resolved_title"] = seed["title"]
            row["citer_count"] = sum(count for _, count in counts)
            resolved.append(row)
            print(f"  {seed['key']}: hubs={counts}", flush=True)
            continue
        hint = resolved_hints.get(seed["key"])
        candidates = []
        if hint:
            candidates.append(hint)
        if seed.get("openalex"):
            candidates.append(seed["openalex"])
        if not candidates:
            matches = search_exact(seed["title"])
            candidates.extend(short_id(m["id"]) for m in matches[:5])
        uniq = []
        for cid in candidates:
            if cid and cid not in uniq:
                uniq.append(cid)
        if not uniq:
            warnings.append(f"{seed['key']}: no OpenAlex candidate")
            row["resolved_id"] = None
            row["citer_count"] = 0
            resolved.append(row)
            print(f"  {seed['key']}: UNRESOLVED", flush=True)
            continue
        cid, count, title = choose_richest(uniq, seed["title"])
        row["hubs"] = [cid]
        row["resolved_id"] = cid
        row["resolved_title"] = title
        row["citer_count"] = count
        resolved.append(row)
        flag = "" if title_match(title, seed["title"]) else " TITLE MISMATCH"
        print(f"  {seed['key']}: {cid} citers={count}{flag} | {title}", flush=True)

    blocked = set()
    for row in resolved:
        if row.get("resolved_id"):
            blocked.add(row["resolved_id"])
        blocked.update(row.get("hubs") or [])
    edges = []
    nodes: dict[str, dict] = {}

    for seed in resolved:
        if not seed.get("resolved_id"):
            continue
        sid = seed["resolved_id"]
        hubs = seed.get("hubs") or [sid]
        print(f"selecting {seed['key']}", flush=True)
        pool = []
        seen_pool: set[str] = set()
        year_map: dict[int, list[dict]] = {}
        years: list[int] = []
        for hub in hubs:
            for work in fetch_top_citers(hub, pages=2):
                wid = short_id(work.get("id"))
                if wid and wid not in seen_pool:
                    seen_pool.add(wid)
                    pool.append(work)
            for year in recent_years(hub):
                if year not in years:
                    years.append(year)
        years = sorted(years, reverse=True)[:3]
        for year in years:
            merged: list[dict] = []
            seen_year: set[str] = set()
            for hub in hubs:
                for work in fetch_year_citers(hub, year):
                    wid = short_id(work.get("id"))
                    if wid and wid not in seen_year:
                        seen_year.add(wid)
                        merged.append(work)
            year_map[year] = merged
        year_pools = year_map
        picks = select_l1(pool, year_pools, blocked)
        if len(picks) < 10:
            warnings.append(f"{seed['key']}: only {len(picks)} L1 papers (citers={seed['citer_count']})")
        seed["l1"] = picks
        seed["timeline_years"] = years
        for pick in picks:
            edges.append({
                "seed_key": seed["key"],
                "seed_id": sid,
                "paper_id": pick["id"],
                "stratum": pick["stratum"],
            })
            current = nodes.get(pick["id"])
            if current is None:
                nodes[pick["id"]] = dict(pick)
                nodes[pick["id"]]["parents"] = [seed["key"]]
            else:
                current["parents"].append(seed["key"])

    payload = {
        "pulled": "2026-10-14",
        "source": "OpenAlex",
        "rule": "Per seed: 4 canon (cited_by_count>=50, surveys deprioritized), 3 timeline (top paper in each of the 3 most recent citing years), 3 diversity (new primary topic), fill to 10. L0 ids excluded from slots.",
        "warnings": warnings,
        "seeds": [
            {
                "domain": s["domain"],
                "key": s["key"],
                "title": s["title"],
                "venue_year": s["year"],
                "openalex_id": s.get("resolved_id"),
                "resolved_title": s.get("resolved_title"),
                "citer_count": s.get("citer_count"),
                "timeline_years": s.get("timeline_years"),
                "l1": s.get("l1") or [],
            }
            for s in resolved
        ],
        "unique_l1": len(nodes),
        "edges": len(edges),
    }
    (ROOT / "l1.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

    lines = [
        "# L1 papers",
        "",
        "Pulled 2026-10-14 from OpenAlex. Each seed has at most 10 citing papers: canon, timeline, diversity, then fill. An L0 paper is not reused as an L1 node. `parents` lists every seed that selected the paper.",
        "",
        f"Unique L1 papers: {len(nodes)}. Citation edges: {len(edges)}.",
        "",
    ]
    if warnings:
        lines.append("Warnings:")
        lines.extend(f"- {w}" for w in warnings)
        lines.append("")
    for seed in payload["seeds"]:
        lines.append(f"## {seed['domain']} / {seed['key']} ({seed['venue_year']})")
        lines.append("")
        lines.append(seed["title"])
        lines.append("")
        lines.append(f"OpenAlex `{seed['openalex_id']}`, citing works indexed: {seed['citer_count']}. Timeline years: {seed['timeline_years']}.")
        lines.append("")
        if not seed["l1"]:
            lines.append("No L1 papers.")
            lines.append("")
            continue
        lines.append("| Stratum | Year | Citations | Topic | Paper |")
        lines.append("|---|---:|---:|---|---|")
        for paper in seed["l1"]:
            title = (paper.get("title") or "").replace("|", "/")
            topic = (paper.get("topic") or "").replace("|", "/")
            lines.append(
                f"| {paper['stratum']} | {paper.get('year')} | {paper.get('cited_by_count')} | {topic} | {title} |"
            )
        lines.append("")
    (ROOT / "L1.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"unique={len(nodes)} edges={len(edges)} warnings={len(warnings)}", flush=True)


if __name__ == "__main__":
    main()
