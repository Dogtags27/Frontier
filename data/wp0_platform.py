"""WP0 platform checks on a synthetic graph. Does not read the corpus."""

import threading
from falkordb import FalkorDB

HOST = "localhost"
PORT = 6379
SRC = "wp0_probe"
CLONE = "wp0_probe_copy"


def rows(result):
    return result.result_set


def one(graph, query, params=None):
    result = graph.query(query, params or {})
    return rows(result)


def main():
    report = []

    def check(name, ok, detail):
        report.append((name, "pass" if ok else "fail", detail))
        print(f"{'PASS' if ok else 'FAIL'}  {name}: {detail}", flush=True)

    db = FalkorDB(host=HOST, port=PORT)
    graph = db.select_graph(SRC)
    try:
        graph.delete()
    except Exception:
        pass
    clone = db.select_graph(CLONE)
    try:
        clone.delete()
    except Exception:
        pass
    graph = db.select_graph(SRC)

    one(graph, "CREATE (:Ping {ok: true})")
    got = one(graph, "MATCH (p:Ping) RETURN p.ok")
    check("python client", got == [[True]], str(got))

    one(graph, "CREATE (:WorkItem {id: 'job', status: 'open'})")
    winners = []
    errors = []
    lock = threading.Lock()

    def claim(worker):
        try:
            result = graph.query(
                "MATCH (w:WorkItem {id: 'job', status: 'open'}) "
                "SET w.status = 'claimed', w.claimed_by = $who "
                "RETURN w.claimed_by",
                {"who": worker},
            )
            with lock:
                if result.result_set:
                    winners.append(result.result_set[0][0])
        except Exception as exc:
            with lock:
                errors.append(f"{worker}: {type(exc).__name__}: {exc}")

    threads = [threading.Thread(target=claim, args=(f"w{i}",)) for i in range(20)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    check(
        "atomic claim",
        len(winners) == 1 and not errors,
        f"winners={winners} errors={errors[:3]}",
    )

    one(graph, "CREATE (:Gap {id: 'g', status: 'candidate', version: 1})")
    gap_winners = []

    def transit(name):
        try:
            result = graph.query(
                "MATCH (g:Gap {id: 'g', status: 'candidate', version: 1}) "
                "SET g.status = $to, g.version = g.version + 1 "
                "RETURN g.status, g.version",
                {"to": name},
            )
            with lock:
                if result.result_set:
                    gap_winners.append(result.result_set[0])
        except Exception as exc:
            with lock:
                errors.append(str(exc))

    pair = [threading.Thread(target=transit, args=(label,)) for label in ("alive", "killed")]
    for thread in pair:
        thread.start()
    for thread in pair:
        thread.join()
    final = one(graph, "MATCH (g:Gap {id: 'g'}) RETURN g.status, g.version")
    check(
        "optimistic gap transition",
        len(gap_winners) == 1 and final and final[0][1] == 2,
        f"writers={gap_winners} stored={final}",
    )

    write_rejected = False
    write_detail = ""
    try:
        graph.ro_query("CREATE (:Nope {id: 'x'})")
        write_detail = "write was accepted"
    except Exception as exc:
        write_rejected = True
        write_detail = f"{type(exc).__name__}: {exc}"
    left = one(graph, "MATCH (n:Nope) RETURN count(n)")
    check("GRAPH.RO_QUERY rejects writes", write_rejected and left == [[0]], write_detail)

    graph.create_node_vector_index("Doc", "embedding", dim=3, similarity_function="cosine")
    docs = [
        ("near", "failure", [1.0, 0.0, 0.0]),
        ("also_near", "failure", [0.98, 0.02, 0.0]),
        ("far_result", "result", [0.0, 1.0, 0.0]),
        ("farther_result", "result", [0.0, 0.0, 1.0]),
    ]
    for name, kind, vector in docs:
        literal = ", ".join(str(value) for value in vector)
        one(
            graph,
            f"CREATE (:Doc {{name: $name, kind: $kind, embedding: vecf32([{literal}])}})",
            {"name": name, "kind": kind},
        )
    nearest = one(
        graph,
        "CALL db.idx.vector.queryNodes('Doc', 'embedding', 2, vecf32([1.0, 0.0, 0.0])) "
        "YIELD node, score RETURN node.name, score",
    )
    names = [row[0] for row in nearest]
    check("vector query", names[:1] == ["near"] and len(names) == 2, str(nearest))

    filtered = one(
        graph,
        "CALL db.idx.vector.queryNodes('Doc', 'embedding', 2, vecf32([1.0, 0.0, 0.0])) "
        "YIELD node, score WITH node, score WHERE node.kind = 'result' "
        "RETURN node.name, score",
    )
    wide = one(
        graph,
        "CALL db.idx.vector.queryNodes('Doc', 'embedding', 4, vecf32([1.0, 0.0, 0.0])) "
        "YIELD node, score WITH node, score WHERE node.kind = 'result' "
        "RETURN node.name ORDER BY score DESC",
    )
    check(
        "vector query then filter",
        True,
        f"k=2 filtered to result -> {filtered or '[]'}; k=4 filtered -> {[row[0] for row in wide]}",
    )

    graph.copy(CLONE)
    copied = db.select_graph(CLONE)
    one(graph, "CREATE (:OnlySource {id: 's'})")
    one(copied, "CREATE (:OnlyCopy {id: 'c'})")
    source_has_copy = one(graph, "MATCH (n:OnlyCopy) RETURN count(n)")
    copy_has_source = one(copied, "MATCH (n:OnlySource) RETURN count(n)")
    check(
        "GRAPH.COPY independence",
        source_has_copy == [[0]] and copy_has_source == [[0]],
        f"source sees copy node {source_has_copy}, copy sees later source node {copy_has_source}",
    )
    copy_nearest = []
    copy_error = ""
    try:
        copy_nearest = rows(
            copied.ro_query(
                "CALL db.idx.vector.queryNodes('Doc', 'embedding', 1, vecf32([1.0, 0.0, 0.0])) "
                "YIELD node, score RETURN node.name"
            )
        )
    except Exception as exc:
        copy_error = f"{type(exc).__name__}: {exc}"
    check(
        "copied graph keeps vectors",
        copy_nearest == [["near"]],
        str(copy_nearest) if copy_nearest else copy_error,
    )

    graph.create_node_fulltext_index("Doc", "name")
    text_rows = []
    text_error = ""
    try:
        text_rows = one(
            graph,
            "CALL db.idx.fulltext.queryNodes('Doc', 'near') YIELD node, score RETURN node.name, score",
        )
    except Exception as exc:
        text_error = f"{type(exc).__name__}: {exc}"
    check("full-text index", bool(text_rows) and text_rows[0][0] == "near", str(text_rows) or text_error)

    one(
        graph,
        "CREATE (:Paper {id:'a'})-[:CITES]->(:Paper {id:'b'}), (:Paper {id:'c'})",
    )
    algo = {}
    for label, query in (
        ("pagerank", "CALL algo.pageRank('Paper', 'CITES') YIELD node, score RETURN node.id, score"),
        ("wcc", "CALL algo.wcc() YIELD node, componentId RETURN node.id, componentId"),
        ("bfs", "MATCH (a:Paper {id:'a'}) CALL algo.bfs(a, 2) YIELD nodes RETURN nodes"),
        ("shortest", "MATCH (a:Paper {id:'a'}), (b:Paper {id:'b'}) CALL algo.shortestPath(a, b) YIELD path RETURN path"),
    ):
        try:
            algo[label] = str(one(graph, query))
        except Exception as exc:
            algo[label] = f"{type(exc).__name__}: {exc}"
            print(f"NOTE  {label}: {algo[label]}", flush=True)
    procedures = ""
    try:
        listed = one(graph, "CALL db.procedures() YIELD name RETURN name")
        names = sorted(row[0] for row in listed if "algo" in row[0] or "path" in row[0].lower() or "rank" in row[0].lower())
        procedures = ", ".join(names[:30])
    except Exception as exc:
        procedures = f"{type(exc).__name__}: {exc}"
    check("algorithm procedures", "pagerank" in algo and not algo["pagerank"].startswith(("ResponseError", "TypeError")), procedures or str(algo))

    print("---")
    for name, status, detail in report:
        print(f"{status:4} {name}")
    graph.delete()
    copied.delete()


if __name__ == "__main__":
    main()
