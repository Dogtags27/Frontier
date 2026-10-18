"""Time the cell query and see whether two held-out papers would fill an empty cell.

Does not write to the graph. A cell is a task plus a method family, counted from
ADDRESSES and USES_METHOD. Survey-like papers do not fill a cell.
"""

import json
import time

from falkordb import FalkorDB

from load_corpus import EXTRACT, GRAPH, recent_ids, read_jsonl

TIMEOUT = 120000
HELD_OUT_FROM = 500
K = 2


def main():
    held = set(recent_ids()[HELD_OUT_FROM:])
    alias = {}
    for row in read_jsonl(EXTRACT / "aliases.jsonl"):
        alias[(row["kind"], row["label"].casefold())] = row["canonical_id"]
    canon = {row["id"]: row for row in read_jsonl(EXTRACT / "canonical.jsonl")}
    facets = {}
    corpus = {}
    for rec in read_jsonl(EXTRACT / "facets_clean.jsonl"):
        if rec["arxiv_id"] in held:
            facets[rec["arxiv_id"]] = rec
    for rec in read_jsonl(EXTRACT / "corpus.jsonl"):
        if rec["arxiv_id"] in held:
            corpus[rec["arxiv_id"]] = rec

    db = FalkorDB(host="localhost", port=6379)
    db.config_set("RESULTSET_SIZE", 1000000)
    graph = db.select_graph(GRAPH)
    started = time.perf_counter()
    rows = graph.query(
        "MATCH (p:Paper)-[:ADDRESSES]->(t:Task) "
        "MATCH (p)-[:USES_METHOD]->(m:Method) "
        "RETURN t.slug, m.family, count(DISTINCT p)",
        timeout=TIMEOUT,
    ).result_set
    elapsed = time.perf_counter() - started
    occupied = {}
    task_families = {}
    family_tasks = {}
    for task, family, papers in rows:
        occupied.setdefault(task, set()).add(family)
        task_families.setdefault(task, set()).add(family)
        family_tasks.setdefault(family, set()).add(task)
    print(f"cell query {elapsed:.2f}s occupied {len(rows)}", flush=True)

    hits = []
    for arxiv_id, rec in facets.items():
        if rec["paper_kind"] == "survey_like":
            continue
        tasks = []
        families = []
        for item in rec["facets"].get("problems_addressed") or []:
            slug = alias.get(("problem", item["label"].casefold()))
            if slug:
                tasks.append(slug)
        for item in rec["facets"].get("techniques_used") or []:
            slug = alias.get(("method", item["label"].casefold()))
            if slug:
                families.append(canon[slug]["name"])
        tasks = list(dict.fromkeys(tasks))
        families = list(dict.fromkeys(families))
        filled = []
        for task in tasks:
            known = occupied.get(task, set())
            for family in families:
                if family in known:
                    continue
                task_n = len(task_families.get(task, ()))
                family_n = len(family_tasks.get(family, ()))
                if task_n >= 1 and family_n >= 1:
                    filled.append((task, family, task_n, family_n, task_n + family_n))
        if filled:
            hits.append((len(tasks) * len(families), len(filled), arxiv_id, tasks, filled))
    overlap = empty = 0
    for arxiv_id, rec in facets.items():
        if rec["paper_kind"] == "survey_like":
            continue
        for item in rec["facets"].get("techniques_used") or []:
            slug = alias.get(("method", item["label"].casefold()))
            if slug and canon[slug]["name"] in family_tasks:
                overlap += 1
                break
        for task_item in rec["facets"].get("problems_addressed") or []:
            task = alias.get(("problem", task_item["label"].casefold()))
            if not task:
                continue
            known = occupied.get(task, set())
            for method_item in rec["facets"].get("techniques_used") or []:
                slug = alias.get(("method", method_item["label"].casefold()))
                if slug and canon[slug]["name"] not in known:
                    empty += 1
                    break
            else:
                continue
            break
    print(f"held-out papers reusing a loaded method family: {overlap}; with some empty pair: {empty}", flush=True)
    hits.sort(key=lambda item: (-max(row[4] for row in item[4]), item[0]))
    strong = sum(1 for hit in hits if any(row[2] >= K and row[3] >= K for row in hit[4]))
    print(f"held-out papers filling a known task with a known method: {len(hits)}; of those, neighbor k={K}: {strong}", flush=True)
    shown = []
    for _, filled_n, arxiv_id, tasks, filled in hits[:2]:
        task, family, task_n, family_n = filled[0][:4]
        check = graph.query(
            "MATCH (t:Task {slug: $task}) "
            "OPTIONAL MATCH (p:Paper)-[:ADDRESSES]->(t) "
            "WHERE EXISTS { MATCH (p)-[:USES_METHOD]->(:Method {family: $family}) } "
            "RETURN t.name, count(p)",
            {"task": task, "family": family},
            timeout=TIMEOUT,
        ).result_set
        shown.append(
            {
                "arxiv_id": arxiv_id,
                "year": corpus[arxiv_id]["year"],
                "title": corpus[arxiv_id]["title"],
                "pairs": len(tasks) * max(len(filled), 1),
                "strong_empty_fills": filled_n,
                "example_task": check[0][0] if check else task,
                "example_family": family,
                "task_other_families": task_n,
                "family_other_tasks": family_n,
                "papers_already_in_cell": check[0][1] if check else None,
            }
        )
        print(json.dumps(shown[-1], ensure_ascii=False), flush=True)
    (EXTRACT / "scoop_probe.json").write_text(
        json.dumps({"cell_query_seconds": round(elapsed, 2), "occupied_cells": len(rows), "papers": shown}, indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
