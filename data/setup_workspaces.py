"""Hold out the demo scoop paper and stand up the two workspace graphs.

No OpenAI calls. The held-out paper stays in the extract files. Re-ingest it
later with --ingest, which writes it back into frontier_corpus and reassesses
open gaps. Workspace graphs store ids, not paper embeddings.
"""

import json
import threading
from datetime import datetime, timedelta, timezone

from falkordb import FalkorDB
from redis.exceptions import ResponseError

from load_corpus import EXTRACT, GRAPH, attach_vectors, build, load
from r2_config import ROOT

SCOOP_ID = "2007.15251"
TASK_NAME = "large message size in prior algorithms"
FAMILY = "defective list coloring algorithm"
NEIGHBORS = ("2105.04700", "2304.09666")
WS = {"maya": "frontier_ws_maya", "dev": "frontier_ws_dev"}
TIMEOUT = 120000


def q(graph, query, params=None):
    return graph.query(query, params or {}, timeout=TIMEOUT)


def clock(step):
    return (datetime(2026, 10, 16, 21, 0, tzinfo=timezone.utc) + timedelta(seconds=step)).isoformat()


def cell_count(corpus, task_id, family):
    rows = q(
        corpus,
        "MATCH (p:Paper)-[:ADDRESSES]->(:Task {slug: $task}) "
        "MATCH (p)-[:USES_METHOD]->(:Method {family: $family}) "
        "RETURN count(DISTINCT p)",
        {"task": task_id, "family": family},
    ).result_set
    return rows[0][0]


def hold_out(corpus):
    found = q(
        corpus,
        "MATCH (t:Task {name: $task})<-[:ADDRESSES]-(p:Paper {arxiv_id: $id}) "
        "-[:USES_METHOD]->(m:Method {family: $family}) "
        "RETURN t.slug, m.slug, p.title, p.year",
        {"task": TASK_NAME, "id": SCOOP_ID, "family": FAMILY},
    ).result_set
    if not found:
        raise SystemExit(f"{SCOOP_ID} is not in the cell; it may already be held out")
    task_id, method_id, title, year = found[0]
    before = cell_count(corpus, task_id, FAMILY)
    methods_before = q(corpus, "MATCH (m:Method {slug: $id}) RETURN count(m)", {"id": method_id}).result_set[0][0]
    q(corpus, "MATCH (:Paper {arxiv_id: $id})-[:HAS_CLAIM]->(c:Claim) DETACH DELETE c", {"id": SCOOP_ID})
    q(corpus, "MATCH (p:Paper {arxiv_id: $id}) DETACH DELETE p", {"id": SCOOP_ID})
    after = cell_count(corpus, task_id, FAMILY)
    methods_after = q(corpus, "MATCH (m:Method {slug: $id}) RETURN count(m)", {"id": method_id}).result_set[0][0]
    gone = q(corpus, "MATCH (p:Paper {arxiv_id: $id}) RETURN count(p)", {"id": SCOOP_ID}).result_set[0][0]
    if gone != 0 or after != 0 or methods_after != methods_before or before < 1:
        raise SystemExit(f"hold-out failed before={before} after={after} paper={gone} method={methods_after}")
    record = {
        "arxiv_id": SCOOP_ID,
        "title": title,
        "year": year,
        "task_id": task_id,
        "task_name": TASK_NAME,
        "method_family_id": method_id,
        "method_family": FAMILY,
        "neighbor_papers": list(NEIGHBORS),
        "cell_count_after_holdout": after,
    }
    (EXTRACT / "scoop.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    q(
        corpus,
        "MERGE (w:WorkItem {id: $id}) "
        "ON CREATE SET w.type = 'ingest_paper', w.status = 'open', w.payload = $payload, w.created_at = $at",
        {"id": f"ingest-{SCOOP_ID}", "payload": SCOOP_ID, "at": clock(0)},
    )
    return record


def transition(ws, gap_id, frm, to, version, step, kind):
    rows = q(
        ws,
        "MATCH (g:Gap {id: $id, status: $frm, version: $version}) "
        "SET g.status = $to, g.version = g.version + 1 "
        "CREATE (e:Event {id: $event, at: $at, kind: $kind, ref: $id}) "
        "CREATE (e)-[:DESCRIBES]->(g) "
        "RETURN g.status, g.version",
        {
            "id": gap_id,
            "frm": frm,
            "to": to,
            "version": version,
            "event": f"event-{gap_id}-{to}",
            "at": clock(step),
            "kind": kind,
        },
    ).result_set
    if not rows:
        raise SystemExit(f"{gap_id} did not move from {frm} version {version}")
    return rows[0]


def reassess(corpus, ws, gap_id, step):
    gap = q(
        ws,
        "MATCH (g:Gap {id: $id}) RETURN g.status, g.version, g.task_id, g.method_family, g.method_family_id",
        {"id": gap_id},
    ).result_set[0]
    status, version, task_id, family, method_id = gap
    count = cell_count(corpus, task_id, family)
    if count < 1:
        q(
            ws,
            "MATCH (g:Gap {id: $id, status: $status}) "
            "CREATE (e:Event {id: $event, at: $at, kind: 'reassessed', ref: $id, cell_count: 0}) "
            "CREATE (e)-[:DESCRIBES]->(g)",
            {"id": gap_id, "status": status, "event": f"event-{gap_id}-open", "at": clock(step)},
        )
        return {"scooped": False, "cell_count": count, "status": status}
    paper = q(
        corpus,
        "MATCH (p:Paper)-[:ADDRESSES]->(:Task {slug: $task}) "
        "MATCH (p)-[:USES_METHOD]->(:Method {family: $family}) "
        "RETURN p.arxiv_id, p.year LIMIT 1",
        {"task": task_id, "family": family},
    ).result_set[0]
    rows = q(
        ws,
        "MATCH (g:Gap {id: $id, status: 'alive', version: $version}) "
        "SET g.status = 'scooped', g.version = g.version + 1, g.valid_to = $year "
        "MERGE (r:Ref {id: $ref}) SET r.kind = 'paper', r.ref_id = $paper "
        "MERGE (g)-[:SCOOPED_BY]->(r) "
        "CREATE (e:Event {id: $event, at: $at, kind: 'scooped', ref: $id}) "
        "CREATE (e)-[:DESCRIBES]->(g) "
        "WITH g "
        "OPTIONAL MATCH (d:Decision)-[:ABOUT]->(g) "
        "FOREACH (item IN CASE WHEN d IS NULL THEN [] ELSE [d] END | SET item.invalidated = true) "
        "RETURN g.status, g.version",
        {
            "id": gap_id,
            "version": version,
            "year": paper[1],
            "ref": f"paper:{paper[0]}",
            "paper": paper[0],
            "event": f"event-{gap_id}-scooped",
            "at": clock(step),
        },
    ).result_set
    if not rows:
        raise SystemExit(f"{gap_id} was not scooped")
    return {"scooped": True, "cell_count": count, "status": rows[0][0], "paper": paper[0]}


def claim_one(ws, item_id, who):
    rows = q(
        ws,
        "MATCH (w:WorkItem {id: $id, status: 'open'}) "
        "SET w.status = 'claimed', w.claimed_by = $who, w.lease_until = $until "
        "RETURN w.claimed_by",
        {"id": item_id, "who": who, "until": clock(40)},
    ).result_set
    return rows[0][0] if rows else None


def seed_maya(ws, scoop):
    q(
        ws,
        "CREATE (:Student {id: 'maya', name: 'Maya', level: 'msc'}) "
        "CREATE (:Session {id: 'session-maya', started_at: $start})",
        {"start": clock(1)},
    )
    q(ws, "MATCH (s:Student {id: 'maya'}), (n:Session {id: 'session-maya'}) CREATE (s)-[:HAD]->(n)")
    q(
        ws,
        "CREATE (r:ReadEvent {id: 'note-maya', at: $at, depth: 'read', note: $note}) "
        "CREATE (ref:Ref {id: $ref, kind: 'paper', ref_id: $paper}) "
        "CREATE (r)-[:OF]->(ref) "
        "WITH r MATCH (n:Session {id: 'session-maya'}) CREATE (n)-[:INCLUDES]->(r)",
        {
            "at": clock(2),
            "note": "Read the ultrafast coloring paper. The open question is whether defective list coloring has been used on the large-message-size problem.",
            "ref": "paper:2105.04700",
            "paper": "2105.04700",
        },
    )
    q(
        ws,
        "CREATE (g:Gap {id: 'gap_coloring', status: 'candidate', version: 1, task_id: $task, "
        "method_family_id: $method, method_family: $family, score: 2, valid_from: 2021, tx_time: $at}) "
        "CREATE (e:Event {id: 'event-gap_coloring-candidate', at: $at, kind: 'gap_opened', ref: 'gap_coloring'}) "
        "CREATE (e)-[:DESCRIBES]->(g)",
        {
            "task": scoop["task_id"],
            "method": scoop["method_family_id"],
            "family": scoop["method_family"],
            "at": clock(3),
        },
    )
    for paper, step in zip(NEIGHBORS, (4, 5)):
        q(
            ws,
            "MATCH (g:Gap {id: 'gap_coloring'}) "
            "CREATE (ref:Ref {id: $ref, kind: 'paper', ref_id: $paper}) "
            "CREATE (g)-[:EVIDENCED_BY]->(ref) "
            "CREATE (e:Event {id: $event, at: $at, kind: 'evidence_added', ref: 'gap_coloring'}) "
            "CREATE (e)-[:DESCRIBES]->(g)",
            {"ref": f"paper:{paper}", "paper": paper, "event": f"event-evidence-{paper}", "at": clock(step)},
        )
    transition(ws, "gap_coloring", "candidate", "challenged", 1, 6, "challenged")
    transition(ws, "gap_coloring", "challenged", "alive", 2, 7, "alive")
    q(
        ws,
        "MATCH (g:Gap {id: 'gap_coloring'}), (n:Session {id: 'session-maya'}) "
        "CREATE (d:Decision {id: 'decision-maya', at: $at, kind: 'pursue', reason: $reason, invalidated: false}) "
        "CREATE (n)-[:INCLUDES]->(d) "
        "CREATE (d)-[:ABOUT]->(g) "
        "CREATE (e:Event {id: 'event-decision-maya', at: $at, kind: 'decided', ref: 'gap_coloring'}) "
        "CREATE (e)-[:DESCRIBES]->(g)",
        {"at": clock(8), "reason": "The cell is empty and both neighboring papers are already in the field."},
    )
    precondition = q(
        ws,
        "MATCH (g:Gap {id: 'gap_coloring', status: 'alive'})-[:EVIDENCED_BY]->(:Ref) "
        "WITH g, count(*) AS n WHERE n >= 2 RETURN g.id",
    ).result_set
    q(
        ws,
        "CREATE (:Handoff {id: 'handoff-adversary', from_agent: 'GapHunter', to_agent: 'Adversary', "
        "precondition: 'gap alive with two evidence refs', status: $status, reason: $reason})",
        {"status": "accepted" if precondition else "blocked", "reason": "" if precondition else "fewer than two evidence refs"},
    )
    q(
        ws,
        "CREATE (:Handoff {id: 'handoff-brief', from_agent: 'Adversary', to_agent: 'Chronicler', "
        "precondition: 'gap status is scooped', status: 'blocked', reason: 'the filling paper is not in the corpus'})",
    )
    for item_id, item_type, status in (
        ("work-find", "find_gaps", "done"),
        ("work-challenge", "challenge_gap", "done"),
        ("work-reassess", "reassess_gap", "open"),
        ("work-brief", "write_brief", "open"),
    ):
        q(
            ws,
            "CREATE (:WorkItem {id: $id, type: $type, status: $status, payload: 'gap_coloring'})",
            {"id": item_id, "type": item_type, "status": status},
        )


def seed_dev(ws, corpus):
    other = q(
        corpus,
        "MATCH (:Paper {arxiv_id: '1409.1556'})-[:ADDRESSES]->(t:Task) "
        "MATCH (:Paper {arxiv_id: '1409.1556'})-[:USES_METHOD]->(m:Method) "
        "RETURN t.slug, t.name, m.slug, m.family LIMIT 1",
    ).result_set[0]
    q(
        ws,
        "CREATE (:Student {id: 'dev', name: 'Dev', level: 'msc'}) "
        "CREATE (:Session {id: 'session-dev', started_at: $at}) "
        "CREATE (r:ReadEvent {id: 'note-dev', at: $at, depth: 'skimmed', note: $note}) "
        "CREATE (ref:Ref {id: 'paper:1409.1556', kind: 'paper', ref_id: '1409.1556'}) "
        "CREATE (r)-[:OF]->(ref) "
        "CREATE (g:Gap {id: 'gap_dev', status: 'alive', version: 1, task_id: $task, method_family_id: $method, "
        "method_family: $family, score: 1, valid_from: 2014, tx_time: $at})",
        {
            "at": clock(2),
            "note": "Skimmed the VGG paper. Looking at a different cell from Maya.",
            "task": other[0],
            "method": other[2],
            "family": other[3],
        },
    )
    q(
        ws,
        "MATCH (s:Student {id: 'dev'}), (n:Session {id: 'session-dev'}), (r:ReadEvent {id: 'note-dev'}) "
        "CREATE (s)-[:HAD]->(n) CREATE (n)-[:INCLUDES]->(r)",
    )
    q(ws, "CREATE (:WorkItem {id: 'work-dev-brief', type: 'write_brief', status: 'open', payload: 'gap_dev'})")


def claim_race(ws):
    winners = []
    lock = threading.Lock()

    def run(who):
        got = claim_one(ws, "work-reassess", who)
        if got:
            with lock:
                winners.append(got)

    threads = [threading.Thread(target=run, args=(name,)) for name in ("worker-a", "worker-b")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return winners


def finish_reassess(corpus, ws, scoop):
    outcome = reassess(corpus, ws, "gap_coloring", 9)
    q(
        ws,
        "MATCH (w:WorkItem {id: 'work-reassess', status: 'claimed'}) "
        "SET w.status = 'done', w.result = $result",
        {"result": "still_open" if not outcome["scooped"] else "scooped"},
    )
    return outcome


def timeline(ws):
    try:
        ws.ro_query("CREATE (:Nope {id: 'x'})", timeout=TIMEOUT)
        rejected = False
    except ResponseError:
        rejected = True
    rows = ws.ro_query(
        "MATCH (e:Event) RETURN e.at, e.kind, e.ref ORDER BY e.at",
        timeout=TIMEOUT,
    ).result_set
    return rejected, rows


def checks(db, corpus, scoop, winners, outcome):
    maya = db.select_graph(WS["maya"])
    dev = db.select_graph(WS["dev"])
    maya_gaps = [row[0] for row in q(maya, "MATCH (g:Gap) RETURN g.id").result_set]
    dev_gaps = [row[0] for row in q(dev, "MATCH (g:Gap) RETURN g.id").result_set]
    dev_sees_maya = q(dev, "MATCH (g:Gap {id: 'gap_coloring'}) RETURN count(g)").result_set[0][0]
    corpus_private = q(
        corpus,
        "MATCH (n) WHERE n:Student OR n:Gap OR n:Decision OR n:ReadEvent OR n:Ref OR n:Session OR n:Event OR n:Handoff "
        "RETURN count(n)",
    ).result_set[0][0]
    embeddings = q(
        maya,
        "MATCH (n) WHERE n.embedding IS NOT NULL RETURN count(n)",
    ).result_set[0][0]
    papers = q(maya, "MATCH (p:Paper) RETURN count(p)").result_set[0][0]
    rejected, events = timeline(maya)
    titles = q(
        corpus,
        "MATCH (p:Paper) WHERE p.arxiv_id IN $ids RETURN p.arxiv_id, p.title",
        {"ids": list(NEIGHBORS)},
    ).result_set
    return {
        "scoop": scoop,
        "cell_count": outcome["cell_count"],
        "reassess": outcome,
        "claim_winners": winners,
        "maya_gaps": maya_gaps,
        "dev_gaps": dev_gaps,
        "dev_sees_maya_gap": dev_sees_maya,
        "corpus_private_nodes": corpus_private,
        "maya_embeddings": embeddings,
        "maya_papers": papers,
        "ro_query_rejected_write": rejected,
        "timeline": events,
        "neighbor_titles": titles,
        "graphs": db.list_graphs(),
        "openai": "not used",
    }


def ingest_held_out():
    scoop = json.loads((EXTRACT / "scoop.json").read_text(encoding="utf-8"))
    loaded = [
        rec["arxiv_id"]
        for rec in __import__("load_corpus").read_jsonl(EXTRACT / "corpus.jsonl")
        if rec["arxiv_id"] != SCOOP_ID
    ]
    built = build([SCOOP_ID], loaded)
    db = FalkorDB(host="localhost", port=6379)
    corpus = db.select_graph(GRAPH)
    load(corpus, built, datetime.now(timezone.utc).isoformat())
    attach_vectors(corpus, built)
    outcome = reassess(corpus, db.select_graph(WS["maya"]), "gap_coloring", 20)
    print(json.dumps({"ingested": SCOOP_ID, "reassess": outcome}, indent=2))


def main():
    import sys

    if "--ingest" in sys.argv:
        ingest_held_out()
        return
    db = FalkorDB(host="localhost", port=6379)
    corpus = db.select_graph(GRAPH)
    scoop = hold_out(corpus)
    for name in WS.values():
        graph = db.select_graph(name)
        try:
            graph.delete()
        except ResponseError:
            pass
    maya = db.select_graph(WS["maya"])
    dev = db.select_graph(WS["dev"])
    seed_maya(maya, scoop)
    seed_dev(dev, corpus)
    winners = claim_race(maya)
    if winners != ["worker-a"] and winners != ["worker-b"]:
        raise SystemExit(f"claim race expected one winner, got {winners}")
    outcome = finish_reassess(corpus, maya, scoop)
    if outcome["scooped"] or outcome["cell_count"] != 0:
        raise SystemExit(f"held-out cell should be empty, got {outcome}")
    report = checks(db, corpus, scoop, winners, outcome)
    (EXTRACT / "workspace_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
