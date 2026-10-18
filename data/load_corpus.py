"""Load the foundation corpus into the FalkorDB graph frontier_corpus.

Recent papers stay in the extract files. No OpenAI calls. No workspace graph.
Paper and claim text stay out of the graph: a claim keeps its sentence number.
"""

import json
from datetime import datetime, timezone

import numpy as np
from falkordb import FalkorDB
from redis.exceptions import ResponseError

from r2_config import ROOT

EXTRACT = ROOT / "data" / "extract"
EMB = EXTRACT / "embeddings"
GRAPH = "frontier_corpus"
DIM = 1536
MODEL = "text-embedding-3-small"
TIMEOUT = 120000
VECTOR_KINDS = {
    "question",
    "contribution",
    "result",
    "quantitative",
    "ablation",
    "failure",
    "limit",
    "future_work",
    "assumption",
}
CLAIM_LISTS = (
    ("research_question", "question"),
    ("claimed_contributions", "contribution"),
    ("reported_results", "result"),
    ("quantitative_findings", "quantitative"),
    ("ablation_findings", "ablation"),
    ("failure_cases", "failure"),
    ("stated_limits", "limit"),
    ("future_work", "future_work"),
    ("assumptions_and_guarantees", "assumption"),
    ("experimental_setup", "setup"),
    ("reproducibility_details", "reproducibility"),
)
PAPER_EDGES = (
    ("problems_addressed", "problem", "ADDRESSES"),
    ("techniques_used", "method", "USES_METHOD"),
    ("baselines_compared", "method", "COMPARES_TO"),
    ("datasets_evaluated", "dataset", "EVALUATED_ON"),
    ("scoring_measures", "metric", "REPORTS_METRIC"),
)
NODE_LABEL = {"problem": "Task", "method": "Method", "dataset": "Dataset", "metric": "Metric"}
CLAIM_EDGE = {"method": "ABOUT_METHOD", "dataset": "ON_DATASET", "metric": "MEASURED_BY"}


def read_jsonl(path):
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)


def batches(rows, size):
    for start in range(0, len(rows), size):
        yield rows[start : start + size]


def q(graph, query, params=None):
    return graph.query(query, params or {}, timeout=TIMEOUT)


def ensure_schema(graph):
    unique = (
        ("Paper", "arxiv_id"),
        ("Task", "slug"),
        ("Method", "slug"),
        ("Dataset", "slug"),
        ("Metric", "slug"),
        ("Claim", "id"),
        ("Label", "id"),
    )
    for label, prop in unique:
        try:
            graph.create_node_unique_constraint(label, prop)
        except ResponseError as exc:
            if "already" not in str(exc).lower():
                raise
    indexes = (
        ("Paper", "embedding"),
        ("Claim", "embedding"),
        ("Task", "embedding"),
        ("Method", "embedding"),
    )
    for label, prop in indexes:
        try:
            graph.create_node_vector_index(label, prop, dim=DIM, similarity_function="cosine")
        except ResponseError as exc:
            if "already" not in str(exc).lower():
                raise
    for label, prop in (("Paper", "title"), ("Task", "name"), ("Method", "name")):
        try:
            graph.create_node_fulltext_index(label, prop)
        except ResponseError as exc:
            if "already" not in str(exc).lower():
                raise


def recent_ids():
    rows = [rec for rec in read_jsonl(EXTRACT / "corpus.jsonl") if rec.get("layer") == "recent"]
    rows.sort(key=lambda rec: (int(rec["year"]), rec["arxiv_id"]))
    return [rec["arxiv_id"] for rec in rows]


def build(include_ids, loaded_ids):
    include_ids = set(include_ids)
    loaded_ids = set(loaded_ids)
    papers = {}
    for rec in read_jsonl(EXTRACT / "corpus.jsonl"):
        if rec["arxiv_id"] in include_ids:
            papers[rec["arxiv_id"]] = rec
    facets = {}
    for rec in read_jsonl(EXTRACT / "facets_clean.jsonl"):
        if rec["arxiv_id"] in papers:
            facets[rec["arxiv_id"]] = rec
    missing = sorted(set(papers) - set(facets))
    if missing:
        raise SystemExit(f"{len(missing)} papers have no cleaned facets, first {missing[:5]}")

    alias = {}
    for row in read_jsonl(EXTRACT / "aliases.jsonl"):
        alias[(row["kind"], row["label"].casefold())] = row
    canon = {row["id"]: row for row in read_jsonl(EXTRACT / "canonical.jsonl")}

    label_index = {}
    for kind in ("problem", "method"):
        labels = json.loads((EMB / f"{kind}_labels.json").read_text(encoding="utf-8"))
        label_index[kind] = {label: i for i, label in enumerate(labels)}

    nodes = {}
    labels = {}
    paper_edges = []
    claims = []
    claim_pos = {}
    unresolved = []
    for arxiv_id, rec in facets.items():
        paper_kind = rec["paper_kind"]
        for key, kind, rel in PAPER_EDGES:
            use_rel = rel
            if rel == "USES_METHOD" and paper_kind == "survey_like":
                use_rel = "MENTIONS_METHOD"
            for item in rec["facets"].get(key) or []:
                found = alias.get((kind, item["label"].casefold()))
                if not found:
                    unresolved.append((arxiv_id, kind, item["label"]))
                    continue
                nodes[found["canonical_id"]] = canon[found["canonical_id"]]
                label_id = kind + ":" + item["label"].casefold()
                labels[label_id] = {
                    "id": label_id,
                    "kind": kind,
                    "text": item["label"],
                    "slug": found["canonical_id"],
                }
                paper_edges.append(
                    {
                        "arxiv_id": arxiv_id,
                        "slug": found["canonical_id"],
                        "span": item["sentence_number"],
                        "rel": use_rel,
                        "node": NODE_LABEL[kind],
                    }
                )
        per_kind = {kind: 0 for _, kind in CLAIM_LISTS}
        for key, kind in CLAIM_LISTS:
            for item in rec["facets"].get(key) or []:
                index = per_kind[kind]
                per_kind[kind] += 1
                claim_id = f"{arxiv_id}:{kind}:{index}"
                claims.append(
                    {
                        "id": claim_id,
                        "arxiv_id": arxiv_id,
                        "kind": kind,
                        "label": item["label"],
                        "span": item["sentence_number"],
                        "extractor_version": rec.get("prompt_version") or "d0-6",
                        "vector": kind in VECTOR_KINDS,
                    }
                )
                claim_pos[(arxiv_id, kind, index)] = len(claims) - 1

    claim_links = []
    cursor = {}
    for row in read_jsonl(EXTRACT / "claim_links.jsonl"):
        if row["arxiv_id"] not in papers:
            continue
        index = cursor.get((row["arxiv_id"], row["kind"]), 0)
        cursor[(row["arxiv_id"], row["kind"])] = index + 1
        claim_id = f"{row['arxiv_id']}:{row['kind']}:{index}"
        if (row["arxiv_id"], row["kind"], index) not in claim_pos:
            unresolved.append((row["arxiv_id"], row["kind"], claim_id))
            continue
        for link in row["links"]:
            found = alias.get((link["role"], link["label"].casefold()))
            if not found:
                unresolved.append((row["arxiv_id"], link["role"], link["label"]))
                continue
            nodes[found["canonical_id"]] = canon[found["canonical_id"]]
            claim_links.append(
                {
                    "claim_id": claim_id,
                    "slug": found["canonical_id"],
                    "rel": CLAIM_EDGE[link["role"]],
                    "node": NODE_LABEL[link["role"]],
                    "link_source": link["source"],
                    "span": link["sentence_number"],
                }
            )
    if unresolved:
        raise SystemExit(f"{len(unresolved)} labels had no canonical id, first {unresolved[:5]}")

    present = include_ids | loaded_ids
    cites = []
    with (EXTRACT / "cites.csv").open(encoding="utf-8") as fh:
        next(fh)
        for line in fh:
            citing, cited = line.strip().split(",")[:2]
            if citing in present and cited in present and (citing in include_ids or cited in include_ids):
                cites.append({"citing": citing, "cited": cited})

    paper_rows = []
    for arxiv_id, rec in papers.items():
        facet = facets[arxiv_id]
        paper_rows.append(
            {
                "arxiv_id": arxiv_id,
                "title": rec["title"],
                "year": int(rec["year"]),
                "category": rec.get("primary") or (rec.get("categories") or [""])[0],
                "layer": rec["layer"],
                "paper_kind": facet["paper_kind"],
                "extractor_version": facet.get("prompt_version") or "d0-6",
            }
        )
    return {
        "papers": paper_rows,
        "nodes": list(nodes.values()),
        "labels": list(labels.values()),
        "paper_edges": paper_edges,
        "claims": claims,
        "claim_links": claim_links,
        "cites": cites,
        "label_index": label_index,
    }


def write_rows(graph, query, rows, size=200, extra=None):
    params = dict(extra or {})
    for chunk in batches(rows, size):
        params["rows"] = chunk
        q(graph, query, params)


def load(graph, built, tx_time):
    q(
        graph,
        "MERGE (m:Meta {id: 'frontier_corpus'}) "
        "SET m.embedding_model = $model, m.embedding_dimension = $dim, "
        "m.extractor_version = 'd0-6'",
        {"model": MODEL, "dim": DIM},
    )
    write_rows(
        graph,
        "UNWIND $rows AS row MERGE (p:Paper {arxiv_id: row.arxiv_id}) "
        "ON CREATE SET p.tx_time = $tx, p.valid_from = row.year "
        "SET p.title = row.title, p.year = row.year, p.category = row.category, "
        "p.layer = row.layer, p.paper_kind = row.paper_kind, "
        "p.extractor_version = row.extractor_version",
        built["papers"],
        extra={"tx": tx_time},
    )

    by_label = {label: [] for label in NODE_LABEL.values()}
    for node in built["nodes"]:
        by_label[NODE_LABEL[node["kind"]]].append(
            {
                "slug": node["id"],
                "name": node["name"],
                "provisional": True,
                "family": node["name"] if node["kind"] == "method" else "",
            }
        )
    for label, rows in by_label.items():
        family = ", n.family = row.family" if label == "Method" else ""
        write_rows(
            graph,
            "UNWIND $rows AS row "
            f"MERGE (n:{label} {{slug: row.slug}}) "
            "SET n.name = row.name, n.provisional = row.provisional" + family,
            rows,
        )
    write_rows(
        graph,
        "UNWIND $rows AS row MERGE (l:Label {id: row.id}) "
        "SET l.kind = row.kind, l.surface = row.text "
        "REMOVE l.text "
        "WITH l, row MATCH (n {slug: row.slug}) WHERE n:Task OR n:Method OR n:Dataset OR n:Metric "
        "MERGE (l)-[:ALIAS_OF]->(n)",
        built["labels"],
    )
    for rel in ("ADDRESSES", "USES_METHOD", "MENTIONS_METHOD", "COMPARES_TO", "EVALUATED_ON", "REPORTS_METRIC"):
        rows = [row for row in built["paper_edges"] if row["rel"] == rel]
        if not rows:
            continue
        node = rows[0]["node"]
        write_rows(
            graph,
            "UNWIND $rows AS row "
            "MATCH (p:Paper {arxiv_id: row.arxiv_id}) "
            f"MATCH (n:{node} {{slug: row.slug}}) "
            f"MERGE (p)-[e:{rel} {{span: row.span}}]->(n)",
            rows,
        )
    write_rows(
        graph,
        "UNWIND $rows AS row MERGE (c:Claim {id: row.id}) "
        "SET c.arxiv_id = row.arxiv_id, c.kind = row.kind, c.label = row.label, "
        "c.span = row.span, c.extractor_version = row.extractor_version "
        "WITH c, row MATCH (p:Paper {arxiv_id: row.arxiv_id}) MERGE (p)-[:HAS_CLAIM]->(c)",
        built["claims"],
    )
    for rel in ("ABOUT_METHOD", "ON_DATASET", "MEASURED_BY"):
        rows = [row for row in built["claim_links"] if row["rel"] == rel]
        if not rows:
            continue
        node = rows[0]["node"]
        write_rows(
            graph,
            "UNWIND $rows AS row "
            "MATCH (c:Claim {id: row.claim_id}) "
            f"MATCH (n:{node} {{slug: row.slug}}) "
            f"MERGE (c)-[e:{rel} {{link_source: row.link_source, span: row.span}}]->(n)",
            rows,
        )
    write_rows(
        graph,
        "UNWIND $rows AS row "
        "MATCH (a:Paper {arxiv_id: row.citing}) "
        "MATCH (b:Paper {arxiv_id: row.cited}) "
        "MERGE (a)-[:CITES]->(b)",
        built["cites"],
    )


def attach_vectors(graph, built):
    paper_ids = json.loads((EMB / "paper_ids.json").read_text(encoding="utf-8"))
    paper_pos = {arxiv_id: i for i, arxiv_id in enumerate(paper_ids)}
    paper_matrix = np.load(EMB / "paper_vectors.npy", mmap_mode="r")
    wanted = [row["arxiv_id"] for row in built["papers"]]
    missing = [arxiv_id for arxiv_id in wanted if arxiv_id not in paper_pos]
    if missing:
        raise SystemExit(f"{len(missing)} foundation papers have no vector")
    print(f"paper vectors {len(wanted)}", flush=True)
    for chunk in batches(wanted, 16):
        rows = [
            {"arxiv_id": arxiv_id, "embedding": paper_matrix[paper_pos[arxiv_id]].tolist()}
            for arxiv_id in chunk
        ]
        q(
            graph,
            "UNWIND $rows AS row MATCH (p:Paper {arxiv_id: row.arxiv_id}) "
            "SET p.embedding = vecf32(row.embedding)",
            {"rows": rows},
        )
    del paper_matrix

    claim_ids = json.loads((EMB / "claim_ids.json").read_text(encoding="utf-8"))
    claim_pos = {claim_id: i for i, claim_id in enumerate(claim_ids)}
    claim_matrix = np.load(EMB / "claim_vectors.npy", mmap_mode="r")
    vector_claims = [row["id"] for row in built["claims"] if row["vector"]]
    missing = [claim_id for claim_id in vector_claims if claim_id not in claim_pos]
    if missing:
        raise SystemExit(f"{len(missing)} claims have no vector, first {missing[:5]}")
    print(f"claim vectors {len(vector_claims)}", flush=True)
    done = 0
    for chunk in batches(vector_claims, 16):
        rows = [
            {"id": claim_id, "embedding": claim_matrix[claim_pos[claim_id]].tolist()}
            for claim_id in chunk
        ]
        q(
            graph,
            "UNWIND $rows AS row MATCH (c:Claim {id: row.id}) SET c.embedding = vecf32(row.embedding)",
            {"rows": rows},
        )
        done += len(chunk)
        if done % 800 == 0 or done == len(vector_claims):
            print(f"claim vectors {done}/{len(vector_claims)}", flush=True)
    del claim_matrix

    for kind, label in (("problem", "Task"), ("method", "Method")):
        matrix = np.load(EMB / f"{kind}_vectors.npy", mmap_mode="r")
        index = built["label_index"][kind]
        rows = []
        skipped = 0
        for node in built["nodes"]:
            if node["kind"] != kind:
                continue
            position = index.get(node["name"])
            if position is None:
                skipped += 1
                continue
            rows.append({"slug": node["id"], "embedding": matrix[position].tolist()})
        if skipped:
            print(f"{label} vectors skipped {skipped}", flush=True)
        for chunk in batches(rows, 16):
            q(
                graph,
                f"UNWIND $rows AS row MATCH (n:{label} {{slug: row.slug}}) "
                "SET n.embedding = vecf32(row.embedding)",
                {"rows": chunk},
            )


def counts(graph):
    result = q(
        graph,
        "MATCH (p:Paper) "
        "RETURN count(p) AS papers, "
        "count(CASE WHEN p.layer = 'recent' THEN 1 END) AS recent, "
        "count(CASE WHEN p.abstract IS NOT NULL THEN 1 END) AS abstracts, "
        "count(CASE WHEN p.embedding IS NULL THEN 1 END) AS papers_missing_vector",
    ).result_set[0]
    claim = q(
        graph,
        "MATCH (c:Claim) RETURN count(c), "
        "count(CASE WHEN c.kind IN ['setup', 'reproducibility'] THEN 1 END), "
        "count(CASE WHEN c.embedding IS NULL AND NOT c.kind IN ['setup', 'reproducibility'] THEN 1 END)",
    ).result_set[0]
    rest = {}
    for label in ("Task", "Method", "Dataset", "Metric", "Label"):
        rest[label] = q(graph, f"MATCH (n:{label}) RETURN count(n)").result_set[0][0]
    edges = q(
        graph,
        "MATCH ()-[e]->() RETURN type(e) AS t, count(e) AS n ORDER BY t",
    ).result_set
    return {
        "papers": result[0],
        "recent_papers": result[1],
        "papers_with_abstract": result[2],
        "papers_missing_vector": result[3],
        "claims": claim[0],
        "setup_or_repro_claims": claim[1],
        "claims_missing_vector": claim[2],
        "nodes": rest,
        "edges": {row[0]: row[1] for row in edges},
    }


def check(graph, built):
    if not built["cites"]:
        return {"citation_hit": False, "nearest_is_self": False, "nodes_with_text": None}
    cited = built["cites"][0]
    neighbors = q(
        graph,
        "MATCH (a:Paper {arxiv_id: $citing})-[:CITES]->(b:Paper {arxiv_id: $cited}) RETURN b.arxiv_id",
        cited,
    ).result_set
    sample_id = built["papers"][0]["arxiv_id"]
    paper_ids = json.loads((EMB / "paper_ids.json").read_text(encoding="utf-8"))
    matrix = np.load(EMB / "paper_vectors.npy", mmap_mode="r")
    vector = matrix[paper_ids.index(sample_id)].tolist()
    nearest = q(
        graph,
        "CALL db.idx.vector.queryNodes('Paper', 'embedding', 3, vecf32($vector)) "
        "YIELD node, score RETURN node.arxiv_id, score",
        {"vector": vector},
    ).result_set
    text = q(
        graph,
        "CALL db.idx.fulltext.queryNodes('Paper', $q) YIELD node RETURN node.arxiv_id LIMIT 3",
        {"q": built["papers"][0]["title"].split()[0]},
    ).result_set
    body = q(
        graph,
        "MATCH (n) WHERE n.abstract IS NOT NULL OR n.original IS NOT NULL OR n.body IS NOT NULL RETURN count(n)",
    ).result_set[0][0]
    return {
        "citation_hit": neighbors == [[cited["cited"]]],
        "nearest": nearest,
        "nearest_is_self": bool(nearest) and nearest[0][0] == sample_id,
        "fulltext": [row[0] for row in text],
        "nodes_with_text": body,
    }


def main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--recent-offset", type=int, default=0)
    parser.add_argument("--recent-limit", type=int, default=0)
    args = parser.parse_args()
    ordered = recent_ids()
    if args.recent_limit:
        include = ordered[args.recent_offset : args.recent_offset + args.recent_limit]
        loaded = [
            rec["arxiv_id"]
            for rec in read_jsonl(EXTRACT / "corpus.jsonl")
            if rec.get("layer") == "foundation"
        ]
        loaded.extend(ordered[: args.recent_offset])
    else:
        include = [
            rec["arxiv_id"]
            for rec in read_jsonl(EXTRACT / "corpus.jsonl")
            if rec.get("layer") == "foundation"
        ]
        loaded = []
    built = build(include, loaded)
    print(
        f"prepared papers {len(built['papers'])} canonical {len(built['nodes'])} "
        f"claims {len(built['claims'])} cites {len(built['cites'])}",
        flush=True,
    )
    db = FalkorDB(host="localhost", port=6379)
    graph = db.select_graph(GRAPH)
    ensure_schema(graph)
    tx_time = datetime.now(timezone.utc).isoformat()
    load(graph, built, tx_time)
    print("structure written", flush=True)
    attach_vectors(graph, built)
    print("vectors written", flush=True)
    report = {"graph": GRAPH, "counts": counts(graph), "check": check(graph, built)}
    report["graphs"] = db.list_graphs()
    (EXTRACT / "corpus_load_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
