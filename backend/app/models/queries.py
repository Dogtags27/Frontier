"""Named queries. Procedure yield fields were checked on a throwaway graph in B0.

algo.pageRank(label, relationship) yields node, score.
algo.WCC() yields node, componentId.
algo.BFS(sourceNode, maxDepth, relationshipType) yields nodes, one list.
algo.labelPropagation() yields node, communityId. This is the community procedure.
algo.SPpaths({sourceNode, targetNode}) yields path.
"""


class Q:
    PAPER_COUNT = "MATCH (p:Paper) RETURN count(p)"
    CLAIM_VECTORS = "MATCH (c:Claim) WHERE c.embedding IS NOT NULL RETURN count(c)"
    PAPERS_MISSING_VECTOR = "MATCH (p:Paper) WHERE p.embedding IS NULL RETURN count(p)"
    TASK_COUNT = "MATCH (n:Task) RETURN count(n)"
    METHOD_COUNT = "MATCH (n:Method) RETURN count(n)"
    DATASET_COUNT = "MATCH (n:Dataset) RETURN count(n)"
    METRIC_COUNT = "MATCH (n:Metric) RETURN count(n)"
    LABEL_COUNT = "MATCH (n:Label) RETURN count(n)"
    LAYER_COUNTS = "MATCH (p:Paper) RETURN p.layer AS layer, count(p) AS n"
    PRIVATE_NODES = (
        "MATCH (n) WHERE n:Student OR n:Gap OR n:Decision OR n:ReadEvent "
        "OR n:Ref OR n:Session OR n:Event OR n:Handoff OR n:Conversation OR n:Turn "
        "RETURN count(n)"
    )
    ENSURE_STUDENT = "MERGE (s:Student {id: $id}) SET s.name = $name, s.level = 'student'"
    GAP_COUNTS = "MATCH (g:Gap) RETURN g.status AS status, count(g) AS n"
    OPEN_GAPS = (
        "MATCH (g:Gap) WHERE g.status IN ['candidate', 'challenged', 'alive'] "
        "OPTIONAL MATCH (g)-[e:EVIDENCED_BY]->() "
        "RETURN g.id, g.status, coalesce(g.score, 0), coalesce(g.task_id, ''), "
        "coalesce(g.text, ''), count(e) "
        "LIMIT 20"
    )
    RECENT_READS = (
        "MATCH (r:ReadEvent) "
        "OPTIONAL MATCH (r)-[:OF]->(ref:Ref {kind: 'paper'}) "
        "RETURN r.id, r.at, r.depth, r.note, coalesce(ref.ref_id, '') "
        "ORDER BY r.at DESC LIMIT 20"
    )
    RECENT_DECISIONS = (
        "MATCH (d:Decision) RETURN d.id, d.at, d.kind, d.reason, d.invalidated "
        "ORDER BY d.at DESC LIMIT 20"
    )
    TIMELINE = (
        "MATCH (e:Event) WHERE e.kind IN $kinds "
        "RETURN e.at, e.kind, e.ref ORDER BY e.at DESC LIMIT 50"
    )
    COUNT_GAPS = "MATCH (g:Gap) RETURN count(g)"
    COUNT_READS = "MATCH (r:ReadEvent) RETURN count(r)"
    COUNT_DECISIONS = "MATCH (d:Decision) RETURN count(d)"
    COUNT_KNOWS = "MATCH (:Student)-[:KNOWS]->(:Ref) RETURN count(*)"
    VECTOR_PAPERS = (
        "CALL db.idx.vector.queryNodes('Paper', 'embedding', $k, vecf32($vector)) "
        "YIELD node, score "
        "RETURN node.arxiv_id, node.title, node.year, node.category, node.layer, node.paper_kind, score"
    )
    VECTOR_CLAIMS = (
        "CALL db.idx.vector.queryNodes('Claim', 'embedding', $k, vecf32($vector)) "
        "YIELD node, score "
        "RETURN node.arxiv_id, node.id, node.kind, node.label, node.span, score"
    )
    FULLTEXT_PAPERS = (
        "CALL db.idx.fulltext.queryNodes('Paper', $q) YIELD node, score "
        "RETURN node.arxiv_id, node.title, node.year, node.category, node.layer, node.paper_kind, score "
        "LIMIT $limit"
    )
    FULLTEXT_TASKS = (
        "CALL db.idx.fulltext.queryNodes('Task', $q) YIELD node, score "
        "RETURN node.slug, node.name, score LIMIT $limit"
    )
    FULLTEXT_METHODS = (
        "CALL db.idx.fulltext.queryNodes('Method', $q) YIELD node, score "
        "RETURN node.slug, node.name, score LIMIT $limit"
    )
    DATASETS_CONTAIN = (
        "MATCH (n:Dataset) WHERE toLower(n.name) CONTAINS toLower($q) "
        "RETURN n.slug, n.name LIMIT $limit"
    )
    METRICS_CONTAIN = (
        "MATCH (n:Metric) WHERE toLower(n.name) CONTAINS toLower($q) "
        "RETURN n.slug, n.name LIMIT $limit"
    )
    PAPERS_FOR_TASKS = (
        "UNWIND $slugs AS slug MATCH (p:Paper)-[:ADDRESSES]->(:Task {slug: slug}) "
        "RETURN DISTINCT p.arxiv_id, p.title, p.year, p.category, p.layer, p.paper_kind LIMIT $limit"
    )
    PAPERS_FOR_METHODS = (
        "UNWIND $slugs AS slug MATCH (p:Paper)-[:USES_METHOD|MENTIONS_METHOD]->(:Method {slug: slug}) "
        "RETURN DISTINCT p.arxiv_id, p.title, p.year, p.category, p.layer, p.paper_kind LIMIT $limit"
    )
    PAPERS_FOR_DATASETS = (
        "UNWIND $slugs AS slug MATCH (p:Paper)-[:EVALUATED_ON]->(:Dataset {slug: slug}) "
        "RETURN DISTINCT p.arxiv_id, p.title, p.year, p.category, p.layer, p.paper_kind LIMIT $limit"
    )
    PAPERS_FOR_METRICS = (
        "UNWIND $slugs AS slug MATCH (p:Paper)-[:REPORTS_METRIC]->(:Metric {slug: slug}) "
        "RETURN DISTINCT p.arxiv_id, p.title, p.year, p.category, p.layer, p.paper_kind LIMIT $limit"
    )
    TASK_IDS = (
        "MATCH (p:Paper)-[:ADDRESSES]->(t:Task) "
        "WHERE t.slug = $name OR toLower(t.name) CONTAINS toLower($name) "
        "RETURN DISTINCT p.arxiv_id "
        "UNION "
        "MATCH (l:Label)-[:ALIAS_OF]->(t:Task)<-[:ADDRESSES]-(p:Paper) "
        "WHERE toLower(l.surface) = toLower($name) RETURN DISTINCT p.arxiv_id"
    )
    METHOD_IDS = (
        "MATCH (p:Paper)-[:USES_METHOD|MENTIONS_METHOD]->(m:Method) "
        "WHERE m.slug = $name OR toLower(m.name) CONTAINS toLower($name) "
        "RETURN DISTINCT p.arxiv_id"
    )
    DATASET_IDS = (
        "MATCH (p:Paper)-[:EVALUATED_ON]->(d:Dataset) "
        "WHERE d.slug = $name OR toLower(d.name) CONTAINS toLower($name) "
        "RETURN DISTINCT p.arxiv_id"
    )
    METRIC_IDS = (
        "MATCH (p:Paper)-[:REPORTS_METRIC]->(m:Metric) "
        "WHERE m.slug = $name OR toLower(m.name) CONTAINS toLower($name) "
        "RETURN DISTINCT p.arxiv_id"
    )
    CITING = "MATCH (p:Paper)-[:CITES]->(:Paper {arxiv_id: $id}) RETURN DISTINCT p.arxiv_id"
    CITED_BY = "MATCH (:Paper {arxiv_id: $id})-[:CITES]->(p:Paper) RETURN DISTINCT p.arxiv_id"
    CITATION_COUNTS = (
        "UNWIND $ids AS id MATCH (p:Paper {arxiv_id: id}) "
        "OPTIONAL MATCH (c:Paper)-[:CITES]->(p) "
        "RETURN id, count(c)"
    )
    PAPERS_BY_IDS = (
        "UNWIND $ids AS id MATCH (p:Paper {arxiv_id: id}) "
        "RETURN p.arxiv_id, p.title, p.year, p.category, p.layer, p.paper_kind"
    )
    PAPER_NODE = (
        "MATCH (p:Paper {arxiv_id: $id}) "
        "RETURN p.arxiv_id, p.title, p.year, p.category, p.layer, p.paper_kind"
    )
    FACETS = (
        "MATCH (p:Paper {arxiv_id: $id}) "
        "RETURN "
        "[(p)-[:ADDRESSES]->(t:Task) | {slug: t.slug, name: t.name}], "
        "[(p)-[:USES_METHOD|MENTIONS_METHOD]->(m:Method) | {slug: m.slug, name: m.name}], "
        "[(p)-[:EVALUATED_ON]->(d:Dataset) | {slug: d.slug, name: d.name}], "
        "[(p)-[:REPORTS_METRIC]->(m:Metric) | {slug: m.slug, name: m.name}]"
    )
    CITES_OUT = (
        "MATCH (:Paper {arxiv_id: $id})-[:CITES]->(b:Paper) "
        "RETURN b.arxiv_id, b.title, b.year ORDER BY b.year DESC LIMIT 20"
    )
    CITES_IN = (
        "MATCH (a:Paper)-[:CITES]->(:Paper {arxiv_id: $id}) "
        "RETURN a.arxiv_id, a.title, a.year ORDER BY a.year DESC LIMIT 20"
    )
    PAPER_MARKS = "MATCH (r:Ref {kind: 'paper'}) RETURN r.ref_id, coalesce(r.state, 'read')"
    RECORD_READ = (
        "MERGE (ref:Ref {kind: 'paper', ref_id: $paper_id}) "
        "SET ref.state = 'read' "
        "MERGE (r:ReadEvent {id: $id}) "
        "ON CREATE SET r.at = $at, r.depth = $depth, r.note = $note, r.paper_id = $paper_id "
        "ON MATCH SET r.depth = $depth, r.note = $note "
        "MERGE (r)-[:OF]->(ref) "
        "WITH r "
        "OPTIONAL MATCH (e:Event {kind: 'read', ref: $paper_id})-[:DESCRIBES]->(r) "
        "FOREACH (_ IN CASE WHEN e IS NULL THEN [1] ELSE [] END | "
        "CREATE (ev:Event {id: $event_id, at: $at, kind: 'read', ref: $paper_id}) "
        "CREATE (ev)-[:DESCRIBES]->(r)) "
        "RETURN r.id, r.at"
    )
    RECORD_NOTE = (
        "CREATE (r:ReadEvent {id: $id, at: $at, depth: 'note', note: $note}) "
        "CREATE (e:Event {id: $event_id, at: $at, kind: 'read', ref: $id}) "
        "CREATE (e)-[:DESCRIBES]->(r) "
        "RETURN r.id"
    )
    RECORD_DECISION = (
        "CREATE (d:Decision {id: $id, at: $at, kind: $kind, reason: $reason, invalidated: false}) "
        "CREATE (e:Event {id: $event_id, at: $at, kind: 'decided', ref: $id}) "
        "CREATE (e)-[:DESCRIBES]->(d) "
        "RETURN d.id"
    )
    RECORD_DECISION_ABOUT = (
        "MATCH (g:Gap {id: $gap_id}) "
        "CREATE (d:Decision {id: $id, at: $at, kind: $kind, reason: $reason, invalidated: false}) "
        "CREATE (d)-[:ABOUT]->(g) "
        "CREATE (e:Event {id: $event_id, at: $at, kind: 'decided', ref: $id}) "
        "CREATE (e)-[:DESCRIBES]->(d) "
        "RETURN d.id"
    )
    OPEN_GAP = (
        "CREATE (g:Gap {id: $id, status: 'candidate', score: 0, task_id: $task_id, "
        "version: 1, text: $text, at: $at}) "
        "CREATE (e:Event {id: $event_id, at: $at, kind: 'gap_opened', ref: $id}) "
        "CREATE (e)-[:DESCRIBES]->(g) "
        "RETURN g.id"
    )
    FIND_MEMORY = (
        "MATCH (m:Memory {kind: $kind, entity: $entity, text: $text}) "
        "WHERE m.valid_to IS NULL RETURN m.id, m.valid_from LIMIT 1"
    )
    CLOSE_MEMORIES = (
        "MATCH (m:Memory {kind: $kind, entity: $entity}) "
        "WHERE m.valid_to IS NULL AND m.text <> $text "
        "SET m.valid_to = $at RETURN m.id"
    )
    CREATE_MEMORY = (
        "CREATE (m:Memory {id: $id, kind: $kind, entity: $entity, text: $text, "
        "valid_from: $at, tx_time: $at}) "
        "RETURN m.id, m.valid_from"
    )
    FORGET_MEMORY = (
        "MATCH (m:Memory {id: $id}) WHERE m.valid_to IS NULL "
        "SET m.valid_to = $at RETURN m.id"
    )
    RECALL_MEMORY = (
        "MATCH (m:Memory) WHERE m.valid_to IS NULL "
        "AND ($q = '' OR toLower(m.text) CONTAINS toLower($q) OR toLower(m.entity) CONTAINS toLower($q)) "
        "RETURN m.id, m.kind, m.text, m.entity, m.valid_from "
        "ORDER BY m.valid_from DESC LIMIT $limit"
    )
    MEMORY_AS_OF = (
        "MATCH (m:Memory) WHERE m.valid_from <= $at "
        "AND (m.valid_to IS NULL OR m.valid_to > $at) "
        "RETURN m.id, m.kind, m.text, m.entity, m.valid_from ORDER BY m.valid_from"
    )
    LIST_GAPS = (
        "MATCH (g:Gap) RETURN g.id, g.status, coalesce(g.score, 0), coalesce(g.task_id, ''), "
        "coalesce(g.text, ''), g.at, coalesce(g.version, 1) ORDER BY g.at DESC LIMIT 50"
    )
    SCOPE_GAP = (
        "MATCH (g:Gap {id: $id}) "
        "OPTIONAL MATCH (g)-[e:EVIDENCED_BY]->() "
        "RETURN g.id, g.status, coalesce(g.task_id, ''), coalesce(g.method_family, ''), "
        "coalesce(g.text, ''), count(e)"
    )
    TASK_DATASET = (
        "MATCH (p:Paper)-[:ADDRESSES]->(:Task {slug: $task}) "
        "MATCH (p)-[:EVALUATED_ON]->(d:Dataset) "
        "WHERE coalesce(p.paper_kind, '') <> 'survey_like' "
        "RETURN d.slug, d.name, p.arxiv_id ORDER BY d.name, d.slug LIMIT 1"
    )
    TASK_METRIC = (
        "MATCH (p:Paper)-[:ADDRESSES]->(:Task {slug: $task}) "
        "MATCH (p)-[:REPORTS_METRIC]->(m:Metric) "
        "WHERE coalesce(p.paper_kind, '') <> 'survey_like' "
        "RETURN m.slug, m.name, p.arxiv_id ORDER BY m.name, m.slug LIMIT 1"
    )
    TASK_BASELINE = (
        "MATCH (p:Paper)-[:ADDRESSES]->(:Task {slug: $task}) "
        "MATCH (p)-[:COMPARES_TO]->(m:Method) "
        "WHERE coalesce(p.paper_kind, '') <> 'survey_like' AND m.family <> $family "
        "RETURN m.slug, coalesce(m.name, m.family), p.arxiv_id ORDER BY m.name, m.slug LIMIT 1"
    )
    CLEAR_PLAYBOOK = (
        "MERGE (b:Playbook {id: $id}) "
        "SET b.at = $at, b.gap_id = $gap, b.summary = $summary "
        "WITH b OPTIONAL MATCH (b)-[old:INCLUDES]->() DELETE old"
    )
    ADD_PLAYBOOK_STEP = (
        "MATCH (b:Playbook {id: $id}) "
        "MERGE (ref:Ref {kind: $kind, ref_id: $ref_id}) "
        "MERGE (b)-[inc:INCLUDES]->(ref) "
        "SET inc.order = $order, inc.role = $role "
        "RETURN ref.ref_id, inc.order"
    )
    LIST_PLANS = (
        "MATCH (b:Playbook) RETURN b.gap_id, b.summary ORDER BY b.at DESC LIMIT 5"
    )
    GAP_ONE = (
        "MATCH (g:Gap {id: $id}) "
        "OPTIONAL MATCH (g)-[e:EVIDENCED_BY]->() "
        "RETURN g.id, g.status, coalesce(g.version, 1), coalesce(g.score, 0), "
        "coalesce(g.task_id, ''), coalesce(g.text, ''), coalesce(g.at, ''), count(e)"
    )
    GAP_REFS = (
        "MATCH (:Gap {id: $id})-[:EVIDENCED_BY]->(ref:Ref) "
        "RETURN ref.kind, ref.ref_id"
    )
    TRANSITION_GAP = (
        "MATCH (g:Gap {id: $id, status: $from, version: $version}) "
        "SET g.status = $to, g.version = g.version + 1, "
        "g.valid_to = CASE WHEN $to IN ['killed', 'adopted', 'scooped'] THEN $at ELSE g.valid_to END "
        "CREATE (e:Event {id: $event_id, at: $at, kind: $to, ref: g.id}) "
        "CREATE (e)-[:DESCRIBES]->(g) "
        "WITH g "
        "OPTIONAL MATCH (d:Decision)-[:ABOUT]->(g) "
        "WHERE g.status = 'scooped' "
        "WITH g, [item IN collect(d) WHERE item IS NOT NULL] AS decisions "
        "FOREACH (item IN decisions | SET item.invalidated = true) "
        "RETURN g.id, g.status, g.version"
    )
    ADD_EVIDENCE = (
        "MATCH (g:Gap {id: $id}) "
        "MERGE (ref:Ref {kind: $kind, ref_id: $ref_id}) "
        "MERGE (g)-[:EVIDENCED_BY]->(ref) "
        "MERGE (e:Event {id: $event_id}) "
        "ON CREATE SET e.at = $at, e.kind = 'evidence_added', e.ref = g.id "
        "MERGE (e)-[:DESCRIBES]->(g) "
        "WITH g "
        "MATCH (g)-[edge:EVIDENCED_BY]->() "
        "RETURN g.id, count(edge)"
    )
    REOPEN_HANDOFFS = (
        "MATCH (h:Handoff {gap_id: $id, precondition: $precondition, status: 'blocked'}) "
        "SET h.status = 'pending', h.reason = '' "
        "RETURN h.id"
    )
    CREATE_HANDOFF = (
        "MATCH (g:Gap {id: $gap_id}) "
        "CREATE (h:Handoff {id: $id, from_agent: $from_agent, to_agent: $to_agent, "
        "precondition: $precondition, status: 'pending', reason: '', gap_id: $gap_id, at: $at}) "
        "RETURN h.id, h.status, h.reason, h.precondition, h.gap_id, h.from_agent, h.to_agent"
    )
    ACCEPT_ADVERSARY = (
        "MATCH (h:Handoff {id: $id, status: 'pending', precondition: 'gap_ready_for_adversary'}) "
        "MATCH (g:Gap {id: h.gap_id, status: 'candidate'}) "
        "MATCH (g)-[:EVIDENCED_BY]->(a) "
        "MATCH (g)-[:EVIDENCED_BY]->(b) "
        "WHERE id(a) <> id(b) "
        "SET h.status = 'accepted', h.reason = '' "
        "RETURN h.id, h.status, h.reason, h.precondition, h.gap_id, h.from_agent, h.to_agent "
        "LIMIT 1"
    )
    ACCEPT_CHRONICLER = (
        "MATCH (h:Handoff {id: $id, status: 'pending', precondition: 'gap_ready_for_chronicler'}) "
        "MATCH (g:Gap {id: h.gap_id}) "
        "WHERE g.status IN ['alive', 'killed', 'adopted', 'scooped'] "
        "SET h.status = 'accepted', h.reason = '' "
        "RETURN h.id, h.status, h.reason, h.precondition, h.gap_id, h.from_agent, h.to_agent "
        "LIMIT 1"
    )
    BLOCK_HANDOFF = (
        "MATCH (h:Handoff {id: $id, status: 'pending'}) "
        "SET h.status = 'blocked', h.reason = $reason "
        "RETURN h.id, h.status, h.reason, h.precondition, h.gap_id, h.from_agent, h.to_agent"
    )
    HANDOFF_ONE = (
        "MATCH (h:Handoff {id: $id}) "
        "RETURN h.id, h.status, h.reason, h.precondition, h.gap_id, h.from_agent, h.to_agent"
    )
    LIST_HANDOFFS = (
        "MATCH (h:Handoff) "
        "RETURN h.id, h.status, h.reason, h.precondition, h.gap_id, h.from_agent, h.to_agent, h.at "
        "ORDER BY h.at DESC LIMIT 30"
    )
    CREATE_WORK = (
        "CREATE (w:WorkItem {id: $id, type: $type, status: 'open', payload: $payload, "
        "created: $now, finished: 0, lease_until: 0, attempts: 0, claimed_by: '', error: '', result: ''}) "
        "RETURN w.id, w.status"
    )
    CLAIM_WORK = (
        "MATCH (w:WorkItem) "
        "WHERE w.type IN $types AND (w.status = 'open' OR (w.status = 'claimed' AND w.lease_until < $now)) "
        "WITH w ORDER BY w.created LIMIT 1 "
        "SET w.status = 'claimed', w.claimed_by = $worker, w.lease_until = $until, "
        "w.attempts = coalesce(w.attempts, 0) + 1, w.error = '' "
        "RETURN w.id, w.type, w.payload, w.attempts"
    )
    CLAIMABLE_COUNT = (
        "MATCH (w:WorkItem) "
        "WHERE w.type IN $types AND (w.status = 'open' OR (w.status = 'claimed' AND w.lease_until < $now)) "
        "RETURN count(w)"
    )
    COMPLETE_WORK = (
        "MATCH (w:WorkItem {id: $id, status: 'claimed', claimed_by: $worker}) "
        "SET w.status = 'done', w.finished = $now, w.result = $result "
        "RETURN w.id, w.status"
    )
    FAIL_WORK = (
        "MATCH (w:WorkItem {id: $id, status: 'claimed', claimed_by: $worker}) "
        "SET w.error = $error, "
        "w.status = CASE WHEN w.attempts >= $max THEN 'failed' ELSE 'open' END, "
        "w.claimed_by = CASE WHEN w.attempts >= $max THEN w.claimed_by ELSE '' END, "
        "w.lease_until = 0 "
        "RETURN w.id, w.status"
    )
    WORK_ONE = (
        "MATCH (w:WorkItem {id: $id}) "
        "RETURN w.id, w.type, w.status, w.payload, w.result, w.error, w.created, w.finished, w.attempts"
    )
    LIST_WORK = (
        "MATCH (w:WorkItem) "
        "RETURN w.id, w.type, w.status, w.payload, w.result, w.error, w.created, w.finished, w.attempts "
        "ORDER BY w.created DESC LIMIT $limit"
    )
    OPEN_WORK = (
        "MATCH (w:WorkItem) WHERE w.status <> 'done' "
        "RETURN w.id, w.type, w.status, w.created, w.error "
        "ORDER BY w.created LIMIT $limit"
    )
    STORE_BRIEF = (
        "MERGE (s:Session {id: $id}) "
        "SET s.summary = $summary, s.ended_at = $at, s.started_at = coalesce(s.started_at, $at) "
        "RETURN s.id, s.summary"
    )
    DECISION_STATE = (
        "MATCH (d:Decision {id: $id}) RETURN d.id, d.invalidated"
    )
    PAPER_TASKS = (
        "MATCH (p:Paper {arxiv_id: $id})-[:ADDRESSES]->(t:Task) "
        "RETURN DISTINCT t.slug, t.name, p.year, p.title"
    )
    OCCUPIED_FAMILIES = (
        "MATCH (p:Paper)-[:ADDRESSES]->(t:Task) "
        "WHERE t.slug IN $tasks AND coalesce(p.paper_kind, '') <> 'survey_like' "
        "MATCH (p)-[:USES_METHOD]->(m:Method) "
        "WHERE m.family <> '' "
        "RETURN t.slug, collect(DISTINCT m.family)"
    )
    TASK_BREADTH = (
        "MATCH (p:Paper)-[:ADDRESSES]->(t:Task) "
        "WHERE t.slug IN $tasks AND coalesce(p.paper_kind, '') <> 'survey_like' "
        "MATCH (p)-[:USES_METHOD]->(m:Method) "
        "WHERE m.family <> '' "
        "RETURN t.slug, count(DISTINCT m.family)"
    )
    CITATION_FAMILIES = (
        "MATCH (p:Paper)-[:ADDRESSES]->(t:Task) WHERE t.slug IN $tasks "
        "MATCH (p)-[:CITES]-(other:Paper) "
        "WHERE other <> p AND coalesce(other.paper_kind, '') <> 'survey_like' "
        "MATCH (other)-[:USES_METHOD]->(m:Method) WHERE m.family <> '' "
        "RETURN t.slug, m.family, count(DISTINCT other) AS support "
        "ORDER BY support DESC LIMIT 80"
    )
    DATASET_FAMILIES = (
        "MATCH (p:Paper)-[:ADDRESSES]->(t:Task) WHERE t.slug IN $tasks "
        "MATCH (p)-[:EVALUATED_ON]->(:Dataset)<-[:EVALUATED_ON]-(other:Paper) "
        "WHERE other <> p AND coalesce(other.paper_kind, '') <> 'survey_like' "
        "MATCH (other)-[:USES_METHOD]->(m:Method) WHERE m.family <> '' "
        "RETURN t.slug, m.family, count(DISTINCT other) AS support "
        "ORDER BY support DESC LIMIT 80"
    )
    METRIC_FAMILIES = (
        "MATCH (p:Paper)-[:ADDRESSES]->(t:Task) WHERE t.slug IN $tasks "
        "MATCH (p)-[:REPORTS_METRIC]->(:Metric)<-[:REPORTS_METRIC]-(other:Paper) "
        "WHERE other <> p AND coalesce(other.paper_kind, '') <> 'survey_like' "
        "MATCH (other)-[:USES_METHOD]->(m:Method) WHERE m.family <> '' "
        "RETURN t.slug, m.family, count(DISTINCT other) AS support "
        "ORDER BY support DESC LIMIT 80"
    )
    BASELINE_FAMILIES = (
        "MATCH (p:Paper)-[:ADDRESSES]->(t:Task) "
        "WHERE t.slug IN $tasks AND coalesce(p.paper_kind, '') <> 'survey_like' "
        "MATCH (p)-[:COMPARES_TO]->(m:Method) WHERE m.family <> '' "
        "RETURN t.slug, m.family, count(DISTINCT p) AS support "
        "ORDER BY support DESC LIMIT 40"
    )
    FAMILY_OTHER_TASKS = (
        "UNWIND $pairs AS pair "
        "MATCH (p:Paper)-[:USES_METHOD]->(:Method {family: pair.family}) "
        "WHERE coalesce(p.paper_kind, '') <> 'survey_like' "
        "MATCH (p)-[:ADDRESSES]->(t:Task) WHERE t.slug <> pair.task "
        "RETURN pair.task, pair.family, count(DISTINCT t)"
    )
    OPEN_LIMITATIONS = (
        "MATCH (p:Paper)-[:ADDRESSES]->(t:Task) WHERE t.slug IN $tasks "
        "MATCH (p)-[:HAS_CLAIM]->(c:Claim)-[:ABOUT_METHOD]->(m:Method) "
        "WHERE c.kind IN $kinds AND m.family <> '' "
        "RETURN t.slug, t.name, m.family, c.kind, c.id, c.label, c.span, p.arxiv_id, p.year "
        "LIMIT 40"
    )
    CELL_PAPERS = (
        "MATCH (p:Paper)-[:ADDRESSES]->(:Task {slug: $task}) "
        "WHERE coalesce(p.paper_kind, '') <> 'survey_like' "
        "MATCH (p)-[:USES_METHOD]->(:Method {family: $family}) "
        "RETURN p.arxiv_id, p.title, p.year LIMIT 5"
    )
    LATER_PAPERS = (
        "MATCH (p:Paper)-[:ADDRESSES]->(:Task {slug: $task}) "
        "WHERE p.year > $year AND coalesce(p.paper_kind, '') <> 'survey_like' "
        "MATCH (p)-[:USES_METHOD]->(:Method {family: $family}) "
        "RETURN p.arxiv_id, p.title, p.year LIMIT 5"
    )
    TASK_PAPERS = (
        "MATCH (p:Paper)-[:ADDRESSES]->(:Task {slug: $task}) "
        "WHERE coalesce(p.paper_kind, '') <> 'survey_like' "
        "RETURN p.arxiv_id, p.title, p.year LIMIT 3"
    )
    FAMILY_ELSEWHERE = (
        "MATCH (p:Paper)-[:USES_METHOD]->(:Method {family: $family}) "
        "WHERE coalesce(p.paper_kind, '') <> 'survey_like' "
        "MATCH (p)-[:ADDRESSES]->(t:Task) WHERE t.slug <> $task "
        "RETURN p.arxiv_id, p.title, t.name LIMIT 2"
    )
    READ_IDS = (
        "MATCH (ref:Ref {kind: 'paper'}) WHERE coalesce(ref.state, '') = 'read' "
        "RETURN ref.ref_id"
    )
    READS_ON_TASK = (
        "UNWIND $reads AS id MATCH (r:Paper {arxiv_id: id})-[:ADDRESSES]->(:Task {slug: $task}) "
        "RETURN count(r)"
    )
    READS_BESIDE_TASK = (
        "UNWIND $reads AS id "
        "MATCH (r:Paper {arxiv_id: id})-[:CITES]-(n:Paper)-[:ADDRESSES]->(:Task {slug: $task}) "
        "RETURN count(DISTINCT n)"
    )
    METHOD_FOR_FAMILIES = (
        "UNWIND $families AS family MATCH (m:Method {family: family}) "
        "WITH family, collect(m.slug)[0] AS slug "
        "RETURN family, slug"
    )
    SAVE_GAP = (
        "MERGE (g:Gap {id: $id}) "
        "ON CREATE SET g.status = 'candidate', g.version = 1, g.at = $at, g.task_id = $task, "
        "g.method_family = $family, g.method_family_id = $method, g.score = $score, g.text = $text, "
        "g.signal = $signal, g.claim_year = $year "
        "WITH g WHERE g.status = 'candidate' "
        "SET g.score = $score, g.text = $text "
        "MERGE (e:Event {id: $event_id}) "
        "ON CREATE SET e.at = $at, e.kind = 'gap_opened', e.ref = g.id "
        "MERGE (e)-[:DESCRIBES]->(g) "
        "RETURN g.id, g.status, g.version, g.score"
    )
    GAP_SIGNAL = (
        "MATCH (g:Gap {id: $id}) "
        "RETURN g.id, g.status, coalesce(g.version, 1), coalesce(g.task_id, ''), "
        "coalesce(g.method_family, ''), coalesce(g.signal, ''), coalesce(g.text, ''), "
        "coalesce(g.claim_year, 0), coalesce(g.score, 0)"
    )
    RECORD_ATTEMPT = (
        "MATCH (g:Gap {id: $gap_id}) "
        "CREATE (a:Attempt {id: $id, at: $at, query: $query, result: $result, reason: $reason}) "
        "CREATE (a)-[:AGAINST]->(g) "
        "RETURN a.id, a.result"
    )
    GAP_ATTEMPTS = (
        "MATCH (a:Attempt)-[:AGAINST]->(:Gap {id: $id}) "
        "RETURN a.result, a.reason ORDER BY a.at"
    )
    CITED_BY_PAPER = (
        "MATCH (:Paper {arxiv_id: $id})-[:CITES]->(b:Paper) "
        "WHERE NOT b.arxiv_id IN $skip "
        "RETURN b.arxiv_id, b.title, b.year ORDER BY b.year LIMIT 6"
    )
    CITES_PAPER = (
        "MATCH (b:Paper)-[:CITES]->(:Paper {arxiv_id: $id}) "
        "WHERE NOT b.arxiv_id IN $skip "
        "RETURN b.arxiv_id, b.title, b.year ORDER BY b.year LIMIT 6"
    )
    PAPERS_ON_TASKS = (
        "MATCH (p:Paper)-[:ADDRESSES]->(t:Task) "
        "WHERE t.slug IN $tasks AND coalesce(p.paper_kind, '') <> 'survey_like' "
        "AND NOT p.arxiv_id IN $skip "
        "RETURN DISTINCT p.arxiv_id, p.title, p.year "
        "ORDER BY p.year LIMIT 8"
    )
    CLEAR_PATH = (
        "MERGE (path:ReadingPath {id: 'current'}) "
        "WITH path "
        "OPTIONAL MATCH (path)-[inc:INCLUDES]->(ref:Ref) "
        "OPTIONAL MATCH (ref)-[nxt:NEXT]->(:Ref) "
        "DELETE nxt, inc"
    )
    ADD_PATH_STEP = (
        "MERGE (path:ReadingPath {id: 'current'}) "
        "SET path.at = $at, path.summary = $summary "
        "MERGE (ref:Ref {kind: 'paper', ref_id: $id}) "
        "MERGE (path)-[inc:INCLUDES]->(ref) "
        "SET inc.order = $order "
        "RETURN ref.ref_id, inc.order"
    )
    LINK_NEXT = (
        "MATCH (a:Ref {kind: 'paper', ref_id: $src}), (b:Ref {kind: 'paper', ref_id: $dst}) "
        "MERGE (a)-[:NEXT]->(b) "
        "RETURN a.ref_id, b.ref_id"
    )
    LIST_PATH = (
        "MATCH (:ReadingPath {id: 'current'})-[inc:INCLUDES]->(ref:Ref {kind: 'paper'}) "
        "RETURN ref.ref_id, inc.order ORDER BY inc.order"
    )
    MARK_KNOWS = (
        "MERGE (s:Student {id: $student}) "
        "MERGE (ref:Ref {kind: $kind, ref_id: $ref_id}) "
        "MERGE (s)-[:KNOWS]->(ref) "
        "RETURN ref.ref_id"
    )
    KNOWN_TASKS = (
        "MATCH (:Student)-[:KNOWS]->(ref:Ref) "
        "WHERE ref.kind IN ['task', 'concept'] "
        "RETURN DISTINCT ref.ref_id"
    )
    READ_DAYS = "MATCH (r:ReadEvent) RETURN r.at"
    INTEREST_LINE = (
        "MATCH (m:Memory {kind: 'interest'}) WHERE m.valid_to IS NULL "
        "RETURN m.text ORDER BY m.valid_from DESC LIMIT 1"
    )
    PAPER_CLAIMS = (
        "MATCH (:Paper {arxiv_id: $id})-[:HAS_CLAIM]->(c:Claim) "
        "RETURN c.id, c.kind, c.label, c.span LIMIT 8"
    )
    PROVENANCE = (
        "MATCH (:Paper {arxiv_id: $id})-[:CITES]->(cited:Paper) "
        "OPTIONAL MATCH (cited)-[:CITES]->(origin:Paper) "
        "RETURN cited.arxiv_id, cited.title, coalesce(origin.arxiv_id, ''), coalesce(origin.title, '') "
        "LIMIT 40"
    )
    STRIP = (
        "MATCH (later:Paper)-[:CITES]->(:Paper {arxiv_id: $id}) "
        "OPTIONAL MATCH (later)-[:CITES]->(earlier:Paper) "
        "RETURN later.arxiv_id, later.title, coalesce(later.year, 0), "
        "coalesce(earlier.arxiv_id, ''), coalesce(earlier.title, ''), coalesce(earlier.year, 0) "
        "LIMIT 60"
    )
    FINDING_COUNT = "MATCH (f:Finding) RETURN count(f)"
    STUDENT_WRITES = "MATCH (n) WHERE n:Finding OR n:ReadingPath OR n:Memory RETURN count(n)"
    SAVE_FINDING = (
        "CREATE (f:Finding {id: $id, at: $at, kind: $kind, paper_id: $paper, summary: $summary, origin: $origin}) "
        "RETURN f.id"
    )
    SHORTEST_CITES = (
        "MATCH (a:Paper {arxiv_id: $src}), (b:Paper {arxiv_id: $dst}) "
        "CALL algo.SPpaths({sourceNode: a, targetNode: b, relType: 'CITES', maxLen: 4}) "
        "YIELD path RETURN [n IN nodes(path) | n.arxiv_id] LIMIT 1"
    )
    CITATION_CHAIN = (
        "MATCH (p:Paper {arxiv_id: $id})-[:CITES]->(a:Paper) "
        "OPTIONAL MATCH (a)-[:CITES]->(b:Paper) "
        "RETURN a.arxiv_id, a.title, a.year, coalesce(b.arxiv_id, ''), coalesce(b.title, '') "
        "LIMIT 12"
    )
    CREATE_CONVERSATION = (
        "CREATE (c:Conversation {id: $id, at: $at, updated: $at, title: $title, turns: 0}) "
        "RETURN c.id, c.at, c.title"
    )
    LIST_CONVERSATIONS = (
        "MATCH (c:Conversation) "
        "RETURN c.id, coalesce(c.updated, c.at), c.title, coalesce(c.turns, 0) "
        "ORDER BY coalesce(c.updated, c.at) DESC LIMIT 50"
    )
    GET_CONVERSATION = "MATCH (c:Conversation {id: $id}) RETURN c.id, c.title, coalesce(c.turns, 0)"
    CONVERSATION_TURNS = (
        "MATCH (c:Conversation {id: $id}) "
        "OPTIONAL MATCH (c)-[:HAS_TURN]->(t:Turn) "
        "RETURN c.id, c.title, t.id, t.at, t.role, t.text, coalesce(t.evidence, '[]'), coalesce(t.intent, '') "
        "ORDER BY coalesce(t.seq, 0), t.at"
    )
    RECENT_TURNS = (
        "MATCH (:Conversation {id: $id})-[:HAS_TURN]->(t:Turn) "
        "RETURN t.role, t.text, coalesce(t.evidence, '[]'), coalesce(t.seq, 0), t.at "
        "ORDER BY coalesce(t.seq, 0) DESC, t.at DESC LIMIT $limit"
    )
    ADD_TURN = (
        "MATCH (c:Conversation {id: $id}) "
        "SET c.turns = coalesce(c.turns, 0) + 1, c.updated = $at "
        "WITH c "
        "CREATE (t:Turn {id: $turn_id, at: $at, seq: c.turns, role: 'student', text: $text, evidence: '[]'}) "
        "CREATE (c)-[:HAS_TURN]->(t) "
        "RETURN t.id, t.at"
    )
    ADD_CHAT_TURN = (
        "MATCH (c:Conversation {id: $id}) "
        "SET c.turns = coalesce(c.turns, 0) + 1, c.updated = $at "
        "WITH c "
        "CREATE (t:Turn {id: $turn_id, at: $at, seq: c.turns, role: $role, text: $text, "
        "evidence: $evidence, intent: $intent}) "
        "CREATE (c)-[:HAS_TURN]->(t) "
        "RETURN t.id, t.at, t.seq"
    )
    TITLE_CONVERSATION = (
        "MATCH (c:Conversation {id: $id}) WHERE c.title IN ['Chat', 'Conversation', ''] "
        "SET c.title = $title RETURN c.title"
    )
    DELETE_CONVERSATION = (
        "MATCH (c:Conversation {id: $id}) "
        "OPTIONAL MATCH (c)-[:HAS_TURN]->(t:Turn) "
        "DETACH DELETE t, c"
    )
    SEARCH_TURNS = (
        "MATCH (c:Conversation)-[:HAS_TURN]->(t:Turn) "
        "WHERE c.id <> $exclude AND ANY(w IN $words WHERE toLower(t.text) CONTAINS w) "
        "RETURN c.id, c.title, t.role, t.text, t.at ORDER BY t.at DESC LIMIT $limit"
    )
    RECENT_CONVERSATIONS = (
        "MATCH (c:Conversation) WHERE c.id <> $exclude AND coalesce(c.turns, 0) > 0 "
        "RETURN c.id, c.title, coalesce(c.updated, c.at) ORDER BY coalesce(c.updated, c.at) DESC LIMIT $limit"
    )
    IDEMPOTENT_GET = "MATCH (i:Idempotency {key: $key}) RETURN i.body LIMIT 1"
    IDEMPOTENT_PUT = "CREATE (i:Idempotency {key: $key, body: $body, at: $at}) RETURN i.key"
    ALL_PAPERS = (
        "MATCH (p:Paper) RETURN p.arxiv_id, p.title, p.year, p.category, p.layer, p.paper_kind"
    )
    CELL_COUNT = (
        "MATCH (p:Paper)-[:ADDRESSES]->(:Task {slug: $task}) "
        "MATCH (p)-[:USES_METHOD]->(:Method {family: $family}) "
        "RETURN count(DISTINCT p)"
    )
    PAPER_CELLS = (
        "UNWIND $ids AS id MATCH (p:Paper {arxiv_id: id})-[:USES_METHOD]->(m:Method) "
        "MATCH (p)-[:ADDRESSES]->(t:Task) "
        "RETURN DISTINCT t.slug, m.family, m.slug"
    )
    ALL_IDS = "MATCH (p:Paper) RETURN p.arxiv_id"
    FILLING_PAPER = (
        "MATCH (p:Paper)-[:ADDRESSES]->(:Task {slug: $task}) "
        "MATCH (p)-[:USES_METHOD]->(:Method {family: $family}) "
        "RETURN p.arxiv_id, p.year LIMIT 1"
    )
    DROP_CELL_EDGE = (
        "MATCH (:Paper {arxiv_id: $id})-[e:USES_METHOD]->(:Method {family: $family}) "
        "DELETE e"
    )
    OPEN_CELL_GAPS = (
        "MATCH (g:Gap) WHERE g.task_id = $task AND g.method_family = $family "
        "AND g.status IN ['candidate', 'challenged', 'alive'] "
        "RETURN g.id, g.status, coalesce(g.version, 1)"
    )
    SCOOP_GAP = (
        "MATCH (g:Gap {id: $id}) "
        "WHERE g.status IN ['candidate', 'challenged', 'alive'] "
        "SET g.status = 'scooped', g.version = coalesce(g.version, 1) + 1, g.valid_to = $at "
        "MERGE (r:Ref {kind: 'paper', ref_id: $paper}) "
        "MERGE (g)-[:SCOOPED_BY]->(r) "
        "CREATE (e:Event {id: $event, at: $at, kind: 'scooped', ref: g.id}) "
        "CREATE (e)-[:DESCRIBES]->(g) "
        "WITH g "
        "OPTIONAL MATCH (d:Decision)-[:ABOUT]->(g) "
        "WITH g, [item IN collect(d) WHERE item IS NOT NULL] AS decisions "
        "FOREACH (item IN decisions | SET item.invalidated = true) "
        "WITH g "
        "OPTIONAL MATCH (m:Memory {entity: g.id}) WHERE m.valid_to IS NULL "
        "WITH g, [item IN collect(m) WHERE item IS NOT NULL] AS memories "
        "FOREACH (item IN memories | SET item.valid_to = $at) "
        "RETURN g.id, g.status, g.version"
    )
    GAP_CELL = (
        "MATCH (g:Gap {id: $id}) "
        "RETURN coalesce(g.task_id, ''), coalesce(g.method_family_id, ''), coalesce(g.method_family, '')"
    )
    GAP_DECISION = (
        "MATCH (d:Decision)-[:ABOUT]->(:Gap {id: $id}) "
        "RETURN d.id, d.invalidated, d.reason"
    )
    MERGE_PAPER = (
        "UNWIND $rows AS row MERGE (p:Paper {arxiv_id: row.arxiv_id}) "
        "ON CREATE SET p.tx_time = $tx, p.valid_from = row.year "
        "SET p.title = row.title, p.year = row.year, p.category = row.category, "
        "p.layer = row.layer, p.paper_kind = row.paper_kind, p.extractor_version = row.extractor_version"
    )
    MERGE_CLAIM = (
        "UNWIND $rows AS row MERGE (c:Claim {id: row.id}) "
        "SET c.arxiv_id = row.arxiv_id, c.kind = row.kind, c.label = row.label, "
        "c.span = row.span, c.extractor_version = row.extractor_version "
        "WITH c, row MATCH (p:Paper {arxiv_id: row.arxiv_id}) MERGE (p)-[:HAS_CLAIM]->(c)"
    )
    MERGE_CITES = (
        "UNWIND $rows AS row MATCH (a:Paper {arxiv_id: row.citing}) "
        "MATCH (b:Paper {arxiv_id: row.cited}) MERGE (a)-[:CITES]->(b)"
    )
    PAPER_EDGE = {
        "ADDRESSES": (
            "UNWIND $rows AS row MATCH (p:Paper {arxiv_id: row.arxiv_id}) "
            "MATCH (n:Task {slug: row.slug}) MERGE (p)-[:ADDRESSES {span: row.span}]->(n)"
        ),
        "USES_METHOD": (
            "UNWIND $rows AS row MATCH (p:Paper {arxiv_id: row.arxiv_id}) "
            "MATCH (n:Method {slug: row.slug}) MERGE (p)-[:USES_METHOD {span: row.span}]->(n)"
        ),
        "MENTIONS_METHOD": (
            "UNWIND $rows AS row MATCH (p:Paper {arxiv_id: row.arxiv_id}) "
            "MATCH (n:Method {slug: row.slug}) MERGE (p)-[:MENTIONS_METHOD {span: row.span}]->(n)"
        ),
        "COMPARES_TO": (
            "UNWIND $rows AS row MATCH (p:Paper {arxiv_id: row.arxiv_id}) "
            "MATCH (n:Method {slug: row.slug}) MERGE (p)-[:COMPARES_TO {span: row.span}]->(n)"
        ),
        "EVALUATED_ON": (
            "UNWIND $rows AS row MATCH (p:Paper {arxiv_id: row.arxiv_id}) "
            "MATCH (n:Dataset {slug: row.slug}) MERGE (p)-[:EVALUATED_ON {span: row.span}]->(n)"
        ),
        "REPORTS_METRIC": (
            "UNWIND $rows AS row MATCH (p:Paper {arxiv_id: row.arxiv_id}) "
            "MATCH (n:Metric {slug: row.slug}) MERGE (p)-[:REPORTS_METRIC {span: row.span}]->(n)"
        ),
    }


RESEARCH_EVENT_KINDS = (
    "gap_opened",
    "challenged",
    "alive",
    "killed",
    "adopted",
    "scooped",
    "decided",
    "evidence_added",
    "read",
)


class SQL:
    PAPER_COUNT = "SELECT count(*) FROM papers"
    SENTENCE_COUNT = "SELECT count(*) FROM sentences"
    LAYER_COUNTS = "SELECT layer, count(*) FROM papers GROUP BY layer"
    APPLIED_MIGRATIONS = "SELECT version FROM schema_migrations"
    RECORD_MIGRATION = "INSERT INTO schema_migrations (version) VALUES (%s)"
    ENSURE_MIGRATIONS = (
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
    )
    USER_BY_ID = (
        "SELECT id, email, signup_role, role, display_name, org_id, graph_name, graph_status, disabled "
        "FROM users WHERE id = %s"
    )
    INSERT_USER = (
        "INSERT INTO users (id, email, signup_role, role, display_name, graph_status) "
        "VALUES (%s, %s, %s, %s, %s, 'pending') ON CONFLICT (id) DO NOTHING"
    )
    SET_GRAPH_READY = "UPDATE users SET graph_name = %s, graph_status = 'ready' WHERE id = %s"
    SET_ROLE = "UPDATE users SET role = %s WHERE id = %s"
    SET_ORG = "UPDATE users SET org_id = %s WHERE id = %s"
    SET_DISABLED = "UPDATE users SET disabled = %s WHERE id = %s"
    PENDING_USERS = (
        "SELECT id, email, signup_role, role, display_name, org_id, graph_name, graph_status, disabled "
        "FROM users WHERE graph_status = 'pending'"
    )
    READY_GRAPHS = (
        "SELECT graph_name FROM users WHERE graph_status = 'ready' AND graph_name <> ''"
    )
    INSERT_ORG = "INSERT INTO orgs (id, name, owner_supervisor_id) VALUES (%s, %s, %s)"
    ORG_BY_ID = "SELECT id, name, owner_supervisor_id FROM orgs WHERE id = %s"
    ORG_FOR_OWNER = "SELECT id FROM orgs WHERE owner_supervisor_id = %s"
    INSERT_INVITE = (
        "INSERT INTO invites (id, code_hash, code, org_id, created_by, expires_at, max_uses) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s)"
    )
    REVOKE_LIVE_INVITES = "UPDATE invites SET revoked = true WHERE org_id = %s AND revoked = false"
    LIVE_INVITE = (
        "SELECT id, code, expires_at, max_uses, used FROM invites "
        "WHERE org_id = %s AND revoked = false ORDER BY expires_at DESC LIMIT 1"
    )
    PICK_INVITE = (
        "SELECT org_id, created_by, used, max_uses FROM invites "
        "WHERE code_hash = %s AND revoked = false AND expires_at > now() AND used < max_uses "
        "FOR UPDATE"
    )
    BUMP_INVITE = "UPDATE invites SET used = used + 1 WHERE code_hash = %s AND revoked = false"
    EXPIRE_INVITE = "UPDATE invites SET expires_at = now() - interval '1 day' WHERE code = %s"
    EXHAUST_INVITE = "UPDATE invites SET max_uses = used WHERE code = %s"
    ENROLL = (
        "INSERT INTO enrollments (supervisor_id, student_id, org_id, status) "
        "VALUES (%s, %s, %s, 'active') ON CONFLICT (supervisor_id, student_id) "
        "DO UPDATE SET status = 'active', org_id = EXCLUDED.org_id"
    )
    ACTIVE_ENROLLMENT = (
        "SELECT supervisor_id, student_id, org_id, status FROM enrollments "
        "WHERE supervisor_id = %s AND student_id = %s AND status = 'active'"
    )
    REMOVE_ENROLLMENT = (
        "UPDATE enrollments SET status = 'removed' WHERE supervisor_id = %s AND student_id = %s"
    )
    ORG_STUDENTS = (
        "SELECT u.id, u.display_name FROM enrollments e "
        "JOIN users u ON u.id = e.student_id "
        "WHERE e.org_id = %s AND e.supervisor_id = %s AND e.status = 'active' "
        "ORDER BY u.display_name"
    )
    TEST_USERS = "SELECT id, graph_name FROM users WHERE email LIKE %s"
    INSERT_USAGE = (
        "INSERT INTO llm_usage (id, user_id, org_id, kind, model, input_tokens, output_tokens, usd, cached) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)"
    )
    USAGE_DAY_USER = (
        "SELECT coalesce(sum(input_tokens + output_tokens), 0)::bigint, coalesce(sum(usd), 0)::numeric "
        "FROM llm_usage WHERE user_id = %s AND cached = false "
        "AND created_at >= (date_trunc('day', now() AT TIME ZONE 'utc') AT TIME ZONE 'utc')"
    )
    USAGE_DAY_ORG = (
        "SELECT coalesce(sum(input_tokens + output_tokens), 0)::bigint, coalesce(sum(usd), 0)::numeric "
        "FROM llm_usage WHERE org_id = %s AND cached = false "
        "AND created_at >= (date_trunc('day', now() AT TIME ZONE 'utc') AT TIME ZONE 'utc')"
    )
    USAGE_MONTH = (
        "SELECT coalesce(sum(usd), 0)::numeric FROM llm_usage WHERE cached = false "
        "AND created_at >= (date_trunc('month', now() AT TIME ZONE 'utc') AT TIME ZONE 'utc')"
    )
    USAGE_FOR_USER = (
        "SELECT kind, model, input_tokens, output_tokens, usd, cached FROM llm_usage "
        "WHERE user_id = %s ORDER BY created_at"
    )
    DELETE_USAGE_USERS = "DELETE FROM llm_usage WHERE user_id::text = ANY(%s)"
    LOCK_BUCKET = "SELECT tokens, updated_at FROM rate_buckets WHERE key = %s FOR UPDATE"
    INSERT_BUCKET = (
        "INSERT INTO rate_buckets (key, tokens, updated_at) VALUES (%s, %s, %s) "
        "ON CONFLICT (key) DO NOTHING"
    )
    UPDATE_BUCKET = "UPDATE rate_buckets SET tokens = %s, updated_at = %s WHERE key = %s"
    DELETE_BUCKETS = "DELETE FROM rate_buckets WHERE key = ANY(%s)"
    ACQUIRE_CONCURRENCY = (
        "INSERT INTO rate_concurrency (key, held) VALUES (%s, 1) "
        "ON CONFLICT (key) DO UPDATE SET held = rate_concurrency.held + 1 "
        "WHERE rate_concurrency.held < %s RETURNING held"
    )
    RELEASE_CONCURRENCY = (
        "UPDATE rate_concurrency SET held = GREATEST(held - 1, 0) WHERE key = %s"
    )
    DELETE_CONCURRENCY = "DELETE FROM rate_concurrency WHERE key = ANY(%s)"
    PAPER_ROW = (
        "SELECT arxiv_id, title, year, category, categories, layer, abstract, r2_key "
        "FROM papers WHERE arxiv_id = %s"
    )
    PAPERS_BY_IDS = (
        "SELECT arxiv_id, left(coalesce(abstract, ''), 280) FROM papers WHERE arxiv_id = ANY(%s)"
    )
    ABSTRACT_SEARCH = (
        "SELECT arxiv_id FROM papers "
        "WHERE abstract IS NOT NULL AND abstract <> '' "
        "AND to_tsvector('english', abstract) @@ plainto_tsquery('english', %s) "
        "ORDER BY ts_rank_cd(to_tsvector('english', abstract), plainto_tsquery('english', %s)) DESC "
        "LIMIT %s"
    )
    SENTENCE_ONE = "SELECT n, original FROM sentences WHERE arxiv_id = %s AND n = %s"
    SENTENCE_PAGE = (
        "SELECT n, original FROM sentences WHERE arxiv_id = %s ORDER BY n LIMIT %s OFFSET %s"
    )
    SENTENCES_FOR = (
        "SELECT s.arxiv_id, s.n, left(s.original, 280) FROM sentences s "
        "JOIN unnest(%s::text[], %s::int[]) AS wanted(arxiv_id, n) "
        "ON s.arxiv_id = wanted.arxiv_id AND s.n = wanted.n"
    )
    UPSERT_GAP_INDEX = (
        "INSERT INTO open_gap_index (user_id, task_id, method_family_id, method_family) "
        "VALUES (%s, %s, %s, %s) "
        "ON CONFLICT (user_id, task_id, method_family_id) DO UPDATE SET method_family = EXCLUDED.method_family"
    )
    DELETE_GAP_INDEX = (
        "DELETE FROM open_gap_index WHERE user_id = %s AND task_id = %s AND method_family_id = %s"
    )
    GRAPHS_FOR_CELL = (
        "SELECT u.graph_name, i.method_family_id FROM open_gap_index i "
        "JOIN users u ON u.id = i.user_id "
        "WHERE i.task_id = %s AND i.method_family = %s AND u.graph_status = 'ready'"
    )
