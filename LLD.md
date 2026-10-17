# Frontier: Low-Level Design (draft 1)

Status: for discussion. No code exists for the product. Items marked VERIFY are FalkorDB behaviors I believe but have not tested. The first work package exists to test them.
Supersedes PLAN.md sections 10 to 13 where they disagree. PLAN.md remains the source for scope, persona, and rules.

## 0. Constraints that shape everything

1. The corpus is 997 papers with full text, not abstracts. Extraction read the compressed PDF text of every paper, so limitations, failures, and future work are stated for most of them. Papers with an empty list: `stated_limits` 4, `future_work` 221, `failure_cases` 367, `ablation_findings` 596, `datasets_evaluated` 217, `baselines_compared` 223. The primary gap signal is still structural. The orphaned-statement signal needs a claim-to-method link that the extractor does not produce, so it depends on the linking pass in section 10.
2. A cell is a `(Task, MethodFamily)` pair counted from direct Paper edges. Datasets and baselines are missing for about a fifth of the papers each, so they are not part of the cell.
3. `quantitative_findings` are short labels, not dataset, metric, and value fields. Claim-to-claim `SUPPORTS`, `CHALLENGES`, and `CONTRADICTS` are therefore thin. They are created only for pairs that share a task and a dataset, with the conditions and a rationale recorded. A difference in wording or in a number never creates one. This is a small feature, not a pillar.
4. A gap found by our system means "not found in these 997 papers." It does not mean novel. The UI says so every time.
5. One FalkorDB query runs against one graph. A workspace graph cannot traverse into the corpus in the same query. The application runs the two queries and joins them on stable ids. The corpus is not copied into a workspace graph. Section 4.
6. A scoop beat only works if the data actually contains one: a cell empty through 2019 and filled by a 2020-2026 paper, close to something a student plausibly cares about. We must find it in the data before we build the demo around it (WP3). If none exists, the demo story changes.
7. Citation structure is thin: 967 edges over 997 papers, 104 isolates. Shared tasks and methods carry the graph structure, not citations alone.
8. Survey papers list other people's methods as techniques. Nine papers list 20 or more. Those get `paper_kind = survey_like` and `MENTIONS_METHOD` edges, not `USES_METHOD`, until reviewed by hand.
9. The model read stopword-compressed sentences. What a person is shown is the recovered original sentence (section 10).

## 1. What the system is, in one paragraph

A Python service owns one FalkorDB instance, a Render Postgres database, and a Cloudflare R2 bucket. R2 holds the PDFs. Postgres holds each paper's metadata, the R2 object key, the abstract, and one row per sentence (the compressed sentence the model saw and the recovered original), once. FalkorDB holds two kinds of graph. `frontier_corpus` holds the field structure, citations, facets, and embeddings, once. `frontier_ws_<id>` holds one workspace's notes, hypotheses, decisions, and agent memory, and stores ids of corpus nodes rather than copies of them. Six agents are workers that never talk to each other. They read work items from the graph they are allowed to write, claim one with an atomic Cypher update, write results back as nodes and edges, and may enqueue new work items. An agent fetches a PDF from R2 only when it is about to process or inspect that paper. Backend APIs serve a student console and a read-only supervisor timeline. The API maps the authenticated workspace to its graph name. The text of a sentence is read from Postgres by arXiv id when a span has to be shown. A title, a claim, or a vector search is a second query against `frontier_corpus`.

## 2. Components

| Component | Responsibility | Talks to |
|---|---|---|
| FalkorDB (Docker) | One corpus graph, plus one private graph per workspace. Embeddings live only on the corpus. Private graphs store ids, learner state, and their own work queue | Everything that decides |
| Cloudflare R2 | PDF objects, key `papers/{arxiv_id}.pdf`. S3-compatible. Free tier 10 GB-month, no egress fee | Extractor, and any inspect path |
| Postgres (Render) | One row per arXiv id: metadata, `r2_key`, abstract. One row per sentence: compressed and original text. No PDF bytes. No student data | Extractor, API when a span is displayed |
| Loader | Reads `data/extract/corpus.jsonl` and `cites.csv`. Writes paper ids and citation edges. Does not write the body | FalkorDB, Postgres |
| Extractor | Fetches that paper's PDF from R2, calls an LLM on the compressed abstract plus PDF text, validates the JSON, writes facets as a file and, at load time, nodes and edges to the graph and the sentence rows to Postgres | LLM, R2, FalkorDB, Postgres |
| Canonicalizer | Merges free-text methods and tasks into a controlled vocabulary | Embeddings, FalkorDB |
| Analytics | Pure Cypher and graph algorithms: cells, gap signals, learning distance | FalkorDB |
| Worker runtime | Loop: find claimable work item, claim, run an agent, write results, release | FalkorDB, LLM |
| Agents (6) | Behaviour behind a work item type | Worker runtime |
| API | Thin HTTP layer: student actions, simulated persona events, timeline reads | FalkorDB |
| Web app | Student console, supervisor timeline | API |

The runtime dependencies are FalkorDB, Render Postgres, Cloudflare R2, one LLM provider, and `text-embedding-3-small`. No message broker and no agent framework. Postgres does not hold gap state, handoffs, history, or PDF bytes. `DATABASE_URL` and the R2 credentials come from `.env` and are not committed. The local map of id to object is `data/extract/r2_index.jsonl` (`arxiv_id`, `r2_key`, `url`). Bucket name: `frontier-research-papers`. Key pattern: `papers/{arxiv_id}.pdf`.

## 3. Field graph (shared, read mostly)

Two kinds of node. Shared vocabulary nodes are what connect papers: many papers point at one Task or one Method, which is what makes a cell countable. Claim nodes keep one paper's own finding and the sentence it came from. A claim links to the shared nodes it concerns, so the context stays attached.

| Node | Key | Properties |
|---|---|---|
| Paper | `arxiv_id` | `title`, `year`, `category`, `layer` (foundation or recent), `paper_kind` (research or survey_like), `embedding`, `extractor_version`. No abstract and no text |
| Task | `slug` | `name`, `embedding` |
| Method | `slug` | `name`, `family` (named from a cluster, not a code list), `embedding` |
| Dataset | `slug` | `name` |
| Metric | `slug` | `name` |
| Claim | `id` | `arxiv_id`, `kind`, `label`, `span` (sentence number), `embedding` (nine kinds, not setup or reproducibility), `extractor_version` |
| Concept | `slug` | `name`, `level` (1 foundational to 4 specialised). Curriculum node for the student layer, not a task or a method |

Claim `kind` is one of: `result`, `quantitative`, `ablation`, `failure`, `limit`, `future_work`, `assumption`, `contribution`, `question`, `setup`, `reproducibility`. `setup` and `reproducibility` are kept so their sentence can be opened. They carry no vector and take no part in cells or gaps.

Edges:

- `(Paper)-[:CITES]->(Paper)` from `data/extract/cites.csv`, written when both ends are loaded
- Direct paper edges, each with `span`: `(Paper)-[:ADDRESSES]->(Task)`, `(Paper)-[:USES_METHOD]->(Method)`, `(Paper)-[:COMPARES_TO]->(Method)` for baselines, `(Paper)-[:EVALUATED_ON]->(Dataset)`, `(Paper)-[:REPORTS_METRIC]->(Metric)`. For a `survey_like` paper the technique edge is `MENTIONS_METHOD`
- `(Paper)-[:HAS_CLAIM]->(Claim)`
- Claim links, each with `link_source` (sentence, lexical, or llm): `(Claim)-[:ABOUT_METHOD]->(Method)`, `(Claim)-[:ON_DATASET]->(Dataset)`, `(Claim)-[:MEASURED_BY]->(Metric)`. A claim with no confident link stays attached to its paper only
- `(Claim)-[:SUPPORTS|CHALLENGES|CONTRADICTS]->(Claim)`, thin, with conditions and rationale (section 0, item 3)
- `(Label)-[:ALIAS_OF]->(Task|Method|Dataset|Metric)`
- `(Paper)-[:ABOUT]->(Concept)`, `(Concept)-[:PREREQ_OF]->(Concept)`

Rules for the field graph:

- Every extracted node and edge carries `arxiv_id` and `span`. The model calls it `sentence_number`. It is the index of the numbered sentence the label came from, so the sentence can be read back from Postgres. It is not a character offset or a page number. The graph does not contain that sentence text.
- Extraction is idempotent. Re-running a paper replaces its claims and edges by `MERGE` on stable keys. `extractor_version` records the prompt version (`d0-6`) and the model.
- Unique constraints on the keys above (VERIFY constraint support in the target version).
- Vector indexes: Paper, Claim, and the canonical Task and Method nodes. Model `text-embedding-3-small`. The model name and the dimension are stored with the index. Scores from different indexes are never compared. Full-text index on titles, acronyms, and canonical names (VERIFY syntax).

### Time model

Two clocks, kept separate:

- `valid_from` and `valid_to`: world time, a year, from `Paper.year`. A claim is valid from the year of its paper until a later paper supersedes or qualifies it.
- `tx_time`: when our system learned it, a real timestamp. Recent papers used as the scoop are present in the corpus file but get a `tx_time` of the demo moment, not the load moment.

Consequence: `frontier_corpus` is loaded with the 299 foundation papers first. The 698 recent papers are held back and can be ingested later. The demo sends one of them.

## 4. Tenancy

FalkorDB isolates tenants as named graphs inside one instance. It does not offer a cross-graph join, a foreign key, or a vector index that a second graph can search in place. `GRAPH.COPY` works and keeps vectors, which is exactly why it is not used here: the corpus embeddings are the same for every user, and copying them would duplicate the index, the ingest, and every later update.

Two graphs, one instance:

| Graph | Holds | Who writes |
|---|---|---|
| `frontier_corpus` | Papers, claims, tasks, methods, datasets, metrics, concepts, citations, and every shared embedding | Loader and ingest. Users do not write it |
| `frontier_ws_<id>` | That workspace's notes, hypotheses, reviews, decisions, agent memory, and session state | That workspace's agents |

The isolation boundary is a research workspace, not a duplicated corpus. Maya and Dev each get a workspace graph. A later shared project is another graph with the same private schema, and membership is checked by the application. The demo does not build accounts. The API still refuses a graph name sent by the client and uses a fixed map from workspace id to graph name.

A private node points at the corpus with a stable id and nothing else. A gap stores `task_id` and `method_family_id`. A note or a decision that cites a paper stores `paper_id` or `claim_id`. Those ids are resolved against `frontier_corpus` when the API needs a title, a sentence, or a vector. The paper embedding is never written into the workspace graph.

Retrieval is two searches, merged in the application:

1. Vector search on `frontier_corpus` over paper and claim embeddings.
2. Vector search on the workspace graph over that user's notes, hypotheses, and session summaries, which have their own small embeddings.
3. If a private hit carries a `paper_id`, one corpus lookup fills in the shared node.

A single vector query cannot see both graphs. The product does not build a combined index to get one.

Stale propagation: a new paper is written only into `frontier_corpus`. The application then enqueues `reassess_gap` on each workspace that has an open gap. The reassess reads the cell from the corpus and writes the new status only into that workspace graph, with an Event. Test: after ingest, both workspaces can see the new paper through a corpus query, and a query on Dev's graph returns none of Maya's gaps, notes, or decisions. The corpus contains no workspace nodes.

## 5. Learner layer (inside each workspace graph)

| Node | Key | Properties |
|---|---|---|
| Student | `id` | `name`, `level` |
| Session | `id` | `started_at`, `ended_at`, `summary` (written by Chronicler) |
| ReadEvent | `id` | `at`, `depth` (skimmed, read, understood), `note` (free text) |
| Gap | `id` | `status`, `version`, `task_id`, `method_family_id`, `score`, `valid_from`, `valid_to`, `tx_time`. Ids point at the corpus. The task and method nodes are not copied |
| Attempt | `id` | `at`, `query`, `result` (found_nothing, near_miss, killed), `reason` |
| Decision | `id` | `at`, `kind` (pursue, drop, defer), `reason` |
| WorkItem | `id` | `type`, `status`, `claimed_by`, `lease_until`, `payload` |
| Handoff | `id` | `from_agent`, `to_agent`, `precondition`, `status` |
| Event | `id` | `at`, `kind`, `ref` (the thing it describes). Backbone of the supervisor timeline |

Edges stay inside the workspace graph. A hop that used to land on a corpus node now lands on a `Ref` node whose only payload is the id: `(ReadEvent)-[:OF]->(Ref {kind:'paper', ref_id})`, `(Student)-[:KNOWS {strength}]->(Ref {kind:'concept', ref_id})`, `(Gap)-[:EVIDENCED_BY]->(Ref)`, `(Attempt)-[:FOUND]->(Ref)`, `(Gap)-[:SCOOPED_BY]->(Ref)`. The other edges are unchanged: `(Student)-[:HAD]->(Session)`, `(Session)-[:INCLUDES]->(ReadEvent|Attempt|Decision)`, `(Attempt)-[:AGAINST]->(Gap)`, `(Decision)-[:ABOUT]->(Gap)`, `(Event)-[:DESCRIBES]->(any)`, `(Gap)-[:SUPERSEDES]->(Gap)`. A `Ref` has no embedding, no title, and no sentence. The API resolves `ref_id` on `frontier_corpus` or, for sentence text, in Postgres.

Every state change on Gap, Claim, and Student knowledge writes an Event in the same query. The timeline is `MATCH (e:Event) RETURN ... ORDER BY e.at`. There is no separate audit log to keep in sync.

## 6. Coordination without a planner

LOCKED: agents coordinate only through graph state.

Mechanism: the work queue is nodes.

1. Anything that wants work done creates a `WorkItem` with `status = 'open'` and a `type`. Corpus work (`extract_paper`, `link_paper`) is queued on `frontier_corpus`. Workspace work (`find_gaps`, `challenge_gap`, `reassess_gap`, `write_brief`, `ingest_note`) is queued on that workspace graph. There is no `sync_paper` item, because the corpus is not copied.
2. A worker claims it with one Cypher statement that matches `status = 'open'` (or an expired lease), sets `status = 'claimed'`, `claimed_by`, and `lease_until`, and returns the row. If the match fails, someone else got it.
3. The worker does the job, writes result nodes, sets `status = 'done'`, and may create follow-up WorkItems.
4. A crashed worker's lease expires, so the item becomes claimable again.

Why this is correct only if a claim is a single query: FalkorDB serializes write queries per graph (VERIFY), so a read-then-set inside one query is atomic and a read in one call followed by a write in another is not. The design never splits a claim across calls. Work package 0 tests this with parallel claimers on one item and expects exactly one winner.

Handoffs (the Track 2 "handoffs" requirement) are explicit. A Handoff is a node with a `precondition`, expressed as Cypher that must return a row. Example: the Adversary may not pick up a gap until the GapHunter has attached at least two `EVIDENCED_BY` edges and `status = 'candidate'`. The receiving agent runs the precondition query and the handoff transitions to `accepted` or `blocked`. A blocked handoff stays visible with its reason. That is demo beat 3.

Gap lifecycle, enforced in Cypher, not in Python:

```
candidate -> challenged -> alive | killed -> adopted | scooped
```

Each transition is one query shaped like `MATCH (g:Gap {id:$id, status:$from, version:$v}) SET g.status=$to, g.version=g.version+1 ... CREATE (e:Event ...)`. A stale writer matches zero rows and learns it lost. That is the optimistic concurrency story, and it is tested.

## 7. Agents: what each one actually does

Each agent is a function from a work item and graph reads to graph writes. LLM calls are marked.

| Agent | Work item it serves | Reads | Does | Writes | LLM? |
|---|---|---|---|---|---|
| Cartographer | `map_field` | Corpus for structure. Workspace for the concept ids already known | Computes task and method neighborhoods, communities, PageRank to name load-bearing papers. Builds the reading path on the corpus from the workspace's known concept ids, then writes that path into the workspace as ordered steps with ids | Concept `level` on the corpus. A ReadingPath of `Ref` nodes on the workspace | No for structure. One call to name clusters |
| Reader | `extract_paper` on the corpus, `ingest_note` on the workspace | The paper's numbered sentences, or the student's note | Corpus: structured extraction. Workspace: turns a free-text note into ReadEvent depth and `KNOWS` strength, stored as ids | Facets on the corpus. ReadEvent and KNOWS on the workspace | Yes |
| Evidence | `check_claim` | Claims and citation edges on the corpus | Links claims to supporting, contradicting, or qualifying papers. Flags several "confirmations" that share one cited origin (provenance collapse) by walking `CITES` | Claim stance edges on the corpus | Yes, on a narrow pair-compare |
| GapHunter | `find_gaps` | Corpus for cells. Workspace for KNOWS ids | Runs the gap signals on the corpus, scores, filters by learning distance | Gap nodes and evidence `Ref` nodes on the workspace | No. This is deterministic Cypher so it can be explained and tested |
| Adversary | `challenge_gap` | The gap on the workspace. Cells and vectors on the corpus | Tries to kill the gap: exact cell lookup, neighbor cell lookup, then near misses by embedding similarity on the corpus. Records what it tried | Attempt nodes and the status transition on the workspace | Yes, to judge near misses. Hard checks are Cypher |
| Chronicler | `write_brief` | Events and Sessions on the workspace. Titles resolved from the corpus | Builds the "since you left" brief from graph state only. No model memory | Session summary on the workspace | Yes, to phrase. Content is chosen by query |

GapHunter being deterministic is a deliberate choice. The product claim is that the gap is derivable from the graph. If an LLM invents the gap, FalkorDB is decoration and Track 1 reviewers are right to doubt it.

## 8. Gap signals and scoring (precise)

Let a cell be a `(Task, MethodFamily)` pair. `count(cell)` is the number of papers with `ADDRESSES_TASK` to the task and `USES_METHOD` to a method in the family.

Signals, in order of how much I trust them on abstracts:

1. Empty cell with strong neighbors. `count(cell) = 0`, and the task has at least k other method families with papers, and the method family has at least k other tasks with papers. Neighbor strength is the sum of the two counts. Pure Cypher with pattern and aggregation.
2. Citation-separated clusters. Two sets of papers that each cite heavily within themselves, with few or no `CITES` between them. Weakly connected components and community detection on the citation subgraph (VERIFY the algorithm procedures on our version). Supporting signal only.
3. Orphaned statement. A `limit`, `failure`, or `future_work` Claim linked `ABOUT_METHOD` to a method on a task, where no later paper uses that method on that task. Full text makes these common (only 4 papers state no limit and 221 no future work), but the signal depends on the claim-to-method link from the linking pass. Used where the link exists, never required.
4. Unrelaxed assumption. A Claim of kind `assumption` that no later paper contradicts. Same dependency on links as 3.

Score is a weighted sum, and the weights are stated in the README, not hidden:

```
score = a * neighbor_strength + b * evidence_count - c * learning_distance
```

Learning distance: read the concept ids the workspace `KNOWS` from its own graph, then run the shortest path on `frontier_corpus` from those ids to the concepts the cell requires, over `PREREQ_OF`. The path is one corpus query parameterized by the private id list. A gap three concepts away from Maya ranks below one she can reach this week. FalkorDB still does the traversal. The application only supplies the ids and reads the length.

## 9. Scoop and revision (the heart of Track 2 memory)

There is no scoop endpoint and no fixed list of later papers. Ingest is `POST /field/papers` for one paper or a batch. Each ingested paper is extracted, linked into the vocabulary, and written into `frontier_corpus` only. Every workspace with an open gap is then reassessed. Zero, one, or many gaps can move to `scooped` from one batch. The demo script sends a single paper and shows the one gap that paper fills.

Trigger: any new paper is ingested into `frontier_corpus`.

1. Reader extracts its facets (a work item on the corpus, same pipeline).
2. The paper, its edges, and its embedding stay in `frontier_corpus`. No workspace graph is updated in this step.
3. A `reassess_gap` item runs per open gap, on that workspace graph. The worker reads `task_id` and `method_family_id` from the gap, then asks the corpus whether `count(cell) >= 1`. The status write goes back to the workspace graph only.
4. If yes, one query: set `status = 'scooped'`, `valid_to`, create `SCOOPED_BY`, create an Event, and mark each downstream `Decision` and `Attempt` that relied on the gap as `invalidated`.
5. Chronicler's next brief lists the invalidations with the path: `(Decision)-[:ABOUT]->(Gap)-[:SCOOPED_BY]->(Paper)`.

The old gap and the evidence stay in the graph. Nothing is overwritten. "What did we believe on date X" is a query that filters on `valid_from`, `valid_to`, and `tx_time`.

## 10. Extraction and vocabulary

### What is already extracted

Extraction is done. Prompt `d0-6`, model `gpt-4.1-mini`, one stateless request per paper, input the stopword-compressed abstract plus PDF text as numbered sentences. All 997 replies finished with `stop`. None hit the cap and none failed validation. Files: `data/extract/foundation/facets.jsonl` (299) and `data/extract/recent/facets.jsonl` (698). Each line holds `arxiv_id`, `usage`, `raw_content`, and `facets`. Real spend at list price was 18.75M input tokens and 1.00M output tokens, **$9.10**. Average reply 1,004 tokens.

Each paper has 16 lists. Every item is `{label, sentence_number}`, with `label` under 12 words and `sentence_number` the bracketed sentence index. 48,654 items in total.

| List | Becomes | Items |
|---|---|---|
| `problems_addressed` | Task, by alias | 3,975 |
| `techniques_used` | Method (`USES_METHOD`, or `MENTIONS_METHOD` for survey-like papers) | 6,157 |
| `baselines_compared` | Method (`COMPARES_TO`) | 2,483 |
| `datasets_evaluated` | Dataset | 1,883 |
| `scoring_measures` | Metric | 2,516 |
| `research_question`, `claimed_contributions` | Claim kinds `question`, `contribution` | 2,713, 4,804 |
| `reported_results`, `quantitative_findings`, `ablation_findings` | Claim kinds `result`, `quantitative`, `ablation` | 5,599, 4,753, 949 |
| `failure_cases`, `stated_limits`, `future_work`, `assumptions_and_guarantees` | Claim kinds `failure`, `limit`, `future_work`, `assumption` | 1,176, 2,388, 1,990, 1,982 |
| `experimental_setup`, `reproducibility_details` | Claim kinds `setup`, `reproducibility` | 3,286, 2,000 |

Labels are almost all distinct strings (3,975 problem labels are 3,975 different strings), so clustering into canonical names is the whole job of the vocabulary step.

### Sentence text

Postgres holds one row per sentence per paper: `arxiv_id`, `n`, the compressed sentence the model saw, and the recovered original sentence. The original is rebuilt without a model: the compression only deletes words, so the position of every surviving character is tracked back to the pre-stopword text and the same split rules are applied. Checked on 80 random papers (50,363 sentences): the rebuilt list has the same numbering as the extractor's list in every paper. The original wording is read back with citation markers still removed. A paper that fails the check at build time falls back to the compressed sentence. A known flaw in the compression: a lone letter inside an identifier is deleted (`Fig.4a` became `Fig.4`). It affects about 1% of sentences and is not worth a re-run.

### Clean-up (deterministic, no model)

- Drop an item whose label repeats another label in the same list of the same paper.
- Set `paper_kind = survey_like` when a paper lists 20 or more techniques or its title says survey, review, overview, or tutorial. The flagged list is read by hand once.
- Normalise labels for matching only (case, punctuation). The stored label is unchanged.

### Linking pass (targeted, not blanket)

Goal: tie each claim to the method, dataset, and metric it concerns, so a limit or a number keeps its context. Three steps, in order:

1. Same sentence. A claim and a method, dataset, or metric item of the same paper that cite the same sentence number are linked (`link_source = sentence`).
2. Lexical. The label or acronym of one of that paper's own methods, datasets, or metrics appears in the claim's label or in its original sentence (`link_source = lexical`).
3. Model, only for a claim left with no link. One stateless `gpt-4.1-mini` call per affected paper receives that paper's candidate methods, datasets, and metrics as an id list plus the unlinked claims (label and original sentence), and returns ids from that list only. An id not in the list is rejected (`link_source = llm`). Estimated $2-3 across all papers, labels and sentences only, no document text.

Before any full run, 40 claims from 10 papers are linked by hand and compared. The model step runs on all papers only if precision on the sample is at least 80%. Otherwise the graph keeps the deterministic links and says so.

### Vocabulary

The vocabulary is graph data, built after extraction, and it grows when new papers arrive. Nothing about task or method names is a constant in code.

1. Embed the surface forms with `text-embedding-3-small`: problem labels for Tasks, technique and baseline labels for Methods, dataset labels, metric labels.
2. Cluster them within each type. A cluster is a set of strings near each other, such as "transformer encoder" and "self-attention network."
3. One `gpt-4.1-mini` call per cluster, shown only that cluster's strings, returns one canonical name and, for methods, a family. That call is also stateless.
4. Write a `Task`, `Method`, `Dataset`, or `Metric` node for the canonical name and `(label)-[:ALIAS_OF]->(canonical)`. Papers link to the canonical node, so cell counts use one method, not twenty spellings.
5. A later paper embeds its new labels and links to an existing canonical node when the nearest neighbour is close enough. A label that matches nothing creates a new canonical node. Open gaps are then reassessed, because a new alias can fill a cell.

Cost of this pass is small next to extraction: a few hundred short calls, well under $1.

### Embeddings

- Paper vector: title, the original abstract, and the paper's `question` and `contribution` labels.
- Claim vector: `kind: label` plus the original sentence. Nine claim kinds only, about 26,000 vectors. `setup` and `reproducibility` get none.
- Canonical Task and Method vectors, a few thousand, for near-miss search.
- Estimated memory for about 28,000 vectors at 1,536 dimensions is about 170 MB, once, on `frontier_corpus`. Workspace graphs do not carry these vectors. A private note or hypothesis can have its own vector. That set stays small because it is only what that workspace wrote.
- The embedding model name and dimension are stored with every index. If the model changes, the affected index is rebuilt, never mixed.
- Passages are designed for and not built. The sentence table is their source. If search misses supporting context, a `Chunk` node with a sentence range and its own vector index is added later. It is not wired into cells.

### Quality bar

Hand-label 30 papers and report precision and recall for tasks and methods separately, and the precision of the claim links. The alias edges are queryable, so a bad merge is visible.

## 11. API and views

API surface is small, and every endpoint is a thin wrapper over a query or a work item:

- Persona driver: `POST /students/{id}/notes` (a simulated textual note), `POST /students/{id}/reads`, `POST /students/{id}/decisions`
- Student reads: `GET /students/{id}/brief`, `GET /students/{id}/gaps`, `GET /gaps/{id}/evidence`
- Supervisor: `GET /students/{id}/timeline`, served through `GRAPH.RO_QUERY` on that workspace graph. A write through it errors. Titles in the timeline are filled from `frontier_corpus` by the API.
- Ingest: `POST /field/papers` (one paper or a batch; the same path the demo uses for its single scoop paper), `POST /workers/step` (run one claim cycle), `GET /queue`

Views:

- Student console: the brief, the ranked gaps with evidence paths, and a small subgraph view for a selected gap.
- Supervisor timeline: chronological Events, filterable by Gap. No actions.

The persona is a script that calls the driver endpoints. No real student data, no authentication.

## 12. Work packages (ordered by dependency, not by clock)

Each package has an exit test. A package is not done until its test passes.

### WP0: Verify the platform
Tests, each with a fallback:

| Check | Result |
|---|---|
| Docker, Python client | Pass. Container `frontier-falkordb`, module `42201`, client `falkordb` 1.8.0, port 6379 |
| Atomic claim | Pass. 20 threads, one open item, one winner |
| Optimistic gap transition | Pass. Two writers, one wrote version 2 |
| `GRAPH.RO_QUERY` | Pass. A write errors and creates nothing |
| Vector query | Pass. The nearest node is first. The score is a distance: identical vectors score `0.0`, so nearer is smaller |
| Vector query then a filter | The filter runs after the nearest k. A kind that is not in that k comes back empty unless the query asks for more |
| `GRAPH.COPY` and copied vectors | Pass, and not used for tenancy. A copy keeps a working vector index, which is the duplication this design avoids |
| Full-text index | Pass |
| PageRank, weakly connected components, shortest path | Pass. Shortest path is `algo.SPpaths` with one map argument, `sourceNode` and `targetNode`. `algo.bfs` is registered; its yield fields were not settled |
| Load of the 997 papers, and memory of about 28,000 vectors | Not run. The corpus is loaded once, in WP1, into `frontier_corpus` |

### WP1: Field graph load
Loader reads `data/extract/corpus.jsonl`, `cites.csv`, and the frozen manifest. Writes the 299 foundation papers into `frontier_corpus` as structure: Paper nodes, direct paper edges, Claim nodes, and citation edges whose two ends are both loaded. Holds the 698 recent papers aside as files, not in the graph. Loads metadata, abstract, `r2_key`, and the sentence rows for all 997 into Postgres. No workspace graph is created here.
Exit test: graph counts match the foundation portion of the manifest; a citation traversal returns neighbors; no duplicate nodes on reload; Postgres has 997 papers, their sentence rows, and no student rows.

### WP2: Vocabulary, vectors, and canonical nodes
Extraction itself is finished (section 10). This package loads the vocabulary and the vectors: canonical Task, Method, Dataset, and Metric nodes with `ALIAS_OF` edges, claim links, and the paper and claim embeddings, on the foundation papers. The recent papers' facets stay as JSON for the demo, so the live ingest does not re-spend model calls.
Exit test: the 30-paper gold set scores are reported; alias edges exist for the merged names; re-running produces the same canonical nodes; a near-miss vector query returns sensible neighbours; graph nodes still have no PDF body or sentence text.

### WP3: Field analytics and backtest (the go/no-go for the demo story)
Cell counts, the four signals, and the backtest: run GapHunter on the 2007-2019 foundation papers only, then check which empty cells the 2020-2026 papers fill.
Exit test: a written list of real scoop candidates (cell, evidence, filling paper). The demo scripts one of them. If none is usable, we change the demo's story before building anything else on top of it. This package gates WP7. The ingest path itself stays batch-shaped either way.

### WP4: Learner layer and tenancy
Create `frontier_ws_maya` and `frontier_ws_dev` with the private schema only. `ingest_note` writes KNOWS as a `Ref` to a concept id. No paper, claim, or embedding is copied from `frontier_corpus`.
Exit test: a note changes Maya's KNOWS and nothing in Dev's graph; Dev's graph has none of Maya's gaps; `frontier_corpus` has no workspace nodes; resolving a `Ref` returns the shared paper from the corpus.

### WP5: Coordination substrate
WorkItem queue, claim and lease, Handoff with Cypher preconditions, Event writing, worker runtime.
Exit test: parallel workers drain a queue with no double execution; a killed worker's item is picked up after the lease; a handoff with an unmet precondition is blocked with a visible reason.

### WP6: Agents on the substrate
Reader (student side), GapHunter, Adversary, Cartographer, Evidence, Chronicler, in that order. Evidence and Cartographer polish are the first to be cut.
Exit test: the full pipeline runs from a note to a ranked gap to an Adversary verdict with no manual step except the persona input.

### WP7: Lifecycle, revision, scoop
Gap transitions in Cypher, invalidation, as-of queries.
Exit test: ingesting one real filling paper moves one gap to `scooped`, invalidates the dependent decision, and the brief lists the path. Ingesting a batch can scoop more than one gap with no separate code path. An as-of query before the ingest returns the old belief.

### WP8: Views
Student console and supervisor timeline over the API.
Exit test: a person who has not seen the system can read the timeline and say what happened to Maya's gap.

### WP9: Proof
Isolation test, concurrency test, stale-propagation test (a new corpus paper is visible to every workspace's reassess, and no workspace node is copied into the corpus or into another workspace), the backtest number with its sample size, extraction precision, graph-removal test (what stops working without FalkorDB), README with data model and every query, demo video from the persona script, deploy or local setup instructions.
Exit test: every claim in the README points to a test or a query output.

Dependency order: WP0 then WP1 then WP2 then WP3. WP4 and WP5 can proceed in parallel after WP1. WP6 needs WP2, WP4, WP5. WP7 needs WP3 and WP6. WP8 needs WP7. WP9 runs alongside from WP5 onward.

## 13. Cut list, in order

1. Evidence agent beyond provenance collapse.
2. Cartographer polish (community naming, PageRank display).
3. Signals 2 to 4 (keep signal 1 only).
4. Subgraph view in the console (keep list and evidence path).
5. Live deployment (keep the full local setup instructions).
6. Claim-to-claim relations (keep provenance collapse only).
7. Passage embeddings (designed for, not built in this phase).

Not cuttable: signal 1 gaps, gap lifecycle in Cypher, scoop invalidation, handoff precondition, tenant isolation, concurrency test, supervisor timeline.

## 14. Track 2 coverage and where FalkorDB is load-bearing

| Track 2 requirement | Where it lives | Test |
|---|---|---|
| Episodic memory | Session, ReadEvent, Attempt, Event | Resume brief built only from graph |
| Semantic memory, bi-temporal | Claim and Gap with `valid_from`, `valid_to`, `tx_time` | As-of query returns the old belief |
| Procedural memory | ReadingPath (ordered `NEXT` edges) | Path regenerated after a note changes KNOWS |
| Persistent history | Events survive restart | Kill and restart, timeline identical |
| Handoffs | Handoff node with Cypher precondition | Blocked handoff shown with reason |
| Concurrency | Single-query claim, versioned transitions | N parallel writers, stated outcome |
| Isolation | One private graph per workspace. The corpus is shared and holds the only copy of the embeddings | Dev's graph returns nothing of Maya's. The corpus returns the paper and none of either workspace |

What FalkorDB does that a table could not do cheaply: learning distance as a path query on the corpus from a private list of known ids; cell emptiness as a graph pattern with aggregation; scoop invalidation as a path inside the workspace graph from a decision to the gap to the paper id that scooped it; provenance as a path back to a sentence number; named graphs as the tenant boundary; the work queue and the workspace knowledge in the same atomic store.

The weak point I would worry about as a judge: the queue and gap lifecycle could be done in Postgres. The defense is that the coordination decisions are traversals over the same graph as the knowledge (a handoff precondition is a pattern over gap evidence), so splitting the stores would break atomicity between "the gap changed" and "the work item completed." We must show that, not assert it.

## 15. Decisions

Locked:

1. LLM: OpenAI `gpt-4.1-mini` for extraction, near-miss judgment, and brief phrasing. Embeddings: `text-embedding-3-small`. The API key comes from you and stays out of the repo.
2. Extraction input is the abstract plus the compressed PDF text. There is no document cap. Compression removes PDF whitespace and line-break hyphens, running headers, the bibliography, citation markers, and basic English stopwords. Negation words stay, including not. Each paper is one stateless request. Completion is capped at 3,000 tokens. A reply that reaches that cap is kept, including any complete items before the cut. Requests are never chained with `previous_response_id` or a shared thread. A shared instruction prefix may hit OpenAI's prompt cache; that cache does not insert another paper's text.
3. No frontend in this phase. Backend APIs only, each one a real query or work-item transition. The TypeScript UI comes later and is not in the work packages.

4. Vocabulary is produced by the model from extracted surface forms, stored as `Task` and `Method` nodes plus `ALIAS_OF` edges, and extended when a new paper arrives. There is no name list in code. Section 10.
5. Ingest accepts any number of papers and can scoop any number of gaps. The demo shows one scoop: one ingested paper, one gap.

6. PDFs live in Cloudflare R2 under `papers/{arxiv_id}.pdf`. Postgres on Render stores metadata, the object key, the abstract, and one row per sentence with the compressed and the original text. Connection strings and R2 credentials stay in the environment. Embeddings live once, on `frontier_corpus`. A workspace graph stores ids. Section 2 and section 4.

7. Graph shape. Direct Paper edges to Task, Method, Dataset, and Metric carry the paper's overall setup and are what a gap cell counts. `Claim` is the bridge for specific findings, limits, and numbers, each linked to its method, dataset, and metric. Not everything goes through a claim. Section 3.
8. Evidence text shown to a person is the recovered original sentence, from the Postgres sentence table. The compressed sentence is the fallback. Section 10.
9. Vectors: paper and claim embeddings first. Passage embeddings are designed for and deferred until evaluation shows missing supporting context.
10. Claim links to methods, datasets, and metrics come from a targeted pass: sentence number and lexical matching first, the model only for what is left, validated on a hand-checked sample before a full run. Section 10.
11. Claim-to-claim relations are created only with recorded conditions, never from a different wording or number.

12. Tenancy is one `frontier_corpus` graph plus one `frontier_ws_<id>` graph per workspace. `GRAPH.COPY` was tested and is not the tenant mechanism, because a copy keeps the vectors. The application joins the two graphs on stable ids. The client never chooses the graph name. Section 4.

Still open:

13. Postgres for development: a local Docker database now, Render at deploy. `DATABASE_URL` for Render has not been provided.

### Extraction cost bound (`gpt-4.1-mini`, list price 14 Oct 2026)

Rates: $0.40 / 1M input, $0.10 / 1M cached input, $1.60 / 1M output. No hidden reasoning tokens. There is no document cap. The PDF text is compressed before the call. The abstract is sent whole.

Per paper, the planned instruction is about 1,000 tokens and the completion cap sent to the API is 3,000 tokens. The prompt asks the model to stay under 1,500. Output in the likely row is 1,200 tokens.

| Case | PDF tokens | Share of raw | Likely cost |
|---|---|---|---|
| Raw PDF, no cap | 23.1M | 100% | $11.74 |
| Unwrap whitespace, hyphens, ligatures | 21.6M | 93% | $11.14 |
| Plus boilerplate (arXiv stamp, page numbers, running headers) | 21.3M | 92% | $11.00 |
| Plus drop the bibliography | 17.3M | 75% | $9.41 |
| Plus drop citation markers | 17.0M | 73% | $9.28 |
| Plus basic stopwords, negation kept | 13.4M | 58% | **$7.84** |

Negation kept: not, no, nor, neither, never, none, nothing, nobody, nowhere, without, cannot, and the n't forms. The bibliography cut fired on 749 of 997 papers. Counts are in `data/extract/compression_report.json`. The full stack if every completion uses the full 3,000-token request cap is about $10.72. With a 35% retry budget at the likely size it is $10.58. Embeddings of the compressed text are $0.27.

$18 remains the enforceable ceiling. The extraction call uses this full stack, including stopword removal. Negation words stay.

Actual: all 997 papers were extracted for 18.75M input tokens and 1.00M output tokens, **$9.10** at list price (average reply 1,004 tokens, no cap hits). Input ran above the earlier estimate because the final prompt is longer and numbering adds tokens. With the three pilot runs, about $9.3 of the $18 ceiling is spent. The linking pass (about $2-3 at most), the cluster-naming calls (under $1), and embeddings (a few cents) fit well inside what remains.

## 16. Data preparation (not the product)

Status: D1 to D4 are done. The 10-paper pilot is finished, the prompt is frozen at `d0-6`, and all 997 papers are extracted. The files are `data/extract/foundation/facets.jsonl` (299) and `data/extract/recent/facets.jsonl` (698). Every reply stopped on its own, none failed validation, and the real spend at list price was $9.10. Next are the sentence table, clean-up, the linking pass, the vocabulary, embeddings, and the manifest (D4b to D6). Nothing here is loaded into FalkorDB or Postgres yet.

Done: `data/extract/corpus.jsonl` has 997 `cs.*` papers with arXiv ids (299 from 2007-2019, 698 from 2020-2026). Every id has a file in `data/pdfs/` and an object in R2. `data/extract/cites.csv` has 967 edges. The 5.6 GB Cornell dump was deleted after the pool was cut. `data/pdfs/` and `data/extract/` are gitignored. The older `data/demo/` MAG-id slice is unused.

### D0. Pilot on 10 papers (done)

The ten papers are listed in `data/extract/d0_papers.json`. Three prompt generations were run on them (`d0-1`, `d0-3`, `d0-5`) and compared with a hand-read ideal. Prompt `d0-6` then replaced the six lists with the 16-list schema and was used for the bulk run. Results of the earlier runs are in `data/extract/d0/`, `data/extract/d0/previous/`, and `data/extract/d0/d0-3/`.

### D1. Build the corpus from arXiv ids (replaces the MAG-id slice)

The earlier slice started from MAG ids and had to be mapped back to arXiv. That was the wrong direction: it is why the set is narrow, 2018 to 2020, language only, and short of ids. New direction: start from arXiv ids, take citation edges from Semantic Scholar (its batch endpoint takes `ARXIV:<id>` and returns each paper's references with arXiv ids), and stay in `cs.*`. Verified on 4 papers (2018 to 2025): 60 to 80% of references carry an arXiv id.

Why not a random sample: a random 900 out of several hundred thousand CS papers has almost no citations among its members. Edges need structure. So the sample is built around a foundation layer.

1. **Pool.** Cornell arXiv metadata on Kaggle (needs your Kaggle login or token). Keep `cs.*` papers only: id, title, abstract, categories, first-version date. Stream it, keep the small pool, delete the 5.6 GB file. Cornell has no citations, only the pool.
2. **Foundation layer (old, about 300).** Highest-cited CS papers by era, from Semantic Scholar citation counts on the pool, spread across `cs.*` subfields and across 2007 to 2019 so no single topic or year dominates. These are the papers new work cites.
3. **Recent layer (about 600).** Sample candidates per submission quarter from 2020 to 2026, spread across subfields. Fetch their references. Keep a candidate only if it cites at least 2 foundation papers or at least 2 other kept papers. That is what guarantees edges.
4. **Balance targets.** Roughly one third old (up to 2014), one third middle (2015 to 2020), one third recent (2021 to 2026). No subfield above about 20%. If a bucket cannot reach its target with edges, the shortfall is reported, not hidden.
5. **Edges.** References between kept papers, from Semantic Scholar, both ends in the set.

Exit: `data/extract/corpus.jsonl` (arXiv id, title, abstract, categories, date, era), `data/extract/cites.csv` (arXiv id to arXiv id), and a report with counts per era and per subfield, edge count, isolates (target: none), and the share of papers with a PDF link.

### D2. Download the PDFs, then upload them to R2

arXiv ids give a direct PDF address for every paper. The download finished: 997 staging files under `data/pdfs/`, named by arXiv id. Do not restart it. Upload each file to R2 at `papers/{arxiv_id}.pdf` and record that key. The running system never reads `data/pdfs/` and never ships those files in the container or the repo.

Exit: one R2 object per corpus id. Staging files can be deleted after a successful upload. Check the total size against the 10 GB-month free allowance.

### D3. Text and token report, then the cap

Extract text from each PDF and count tokens with `o200k_base`. The 20,000-token cap was measured, then dropped: 507 papers were over it, and the tail is where limitations sit. A second pass applies the compression stack in `data/compress_text.py` and records each stage.

Exit: `data/extract/token_report.json` and `data/extract/compression_report.json`. The extraction input is the full compressed text.

### D4. Extract all 997 (done)

One stateless `gpt-4.1-mini` request per paper, eight at a time, by `data/extract_foundation.py --layer foundation|recent`. Each finished reply is appended to that layer's `facets.jsonl` and flushed. Input is the stopword-compressed abstract plus PDF text. The 10 pilot papers are among the 997 and were re-extracted with `d0-6`. Three papers failed once on a connection error before any reply and were re-sent.

Result: 997 of 997, all `finish_reason = stop`, 48,654 items, $9.10 at list price. A 3-paper spot check against the cited sentences found every label supported. Method papers are strong. Survey papers list other people's methods as techniques, which the clean-up step handles.

### D4b. Sentence table

For each paper, rebuild the original sentence for every sentence number the model saw, by position tracking through the compression (section 10). Write `data/extract/sentences/{arxiv_id}.jsonl` with `n`, `compressed`, `original`. Check that the rebuilt list has the same numbering as the extractor's list. Load into Postgres once it exists.

Exit: 997 files. Every paper passes the numbering check or is listed with a fallback to compressed text.

### D4c. Clean-up and survey flag

Drop repeated labels within a list, set `paper_kind`, and write `data/extract/facets_clean.jsonl`. No model call.

Exit: a count of dropped items per list, and the survey-like list read by hand.

### D4d. Claim linking

Section 10, linking pass. Deterministic links first, the model only for what is left, measured on a 40-claim hand-checked sample before a full run.

Exit: `data/extract/claim_links.jsonl`, and the sample precision written down. Spend stays well inside the ceiling.

### D5. Vocabulary files

Embed the labels, cluster them within each type, and have one stateless `gpt-4.1-mini` call per cluster return a canonical name and, for methods, a family. Write:

- `data/extract/canonical.jsonl` for tasks, methods, datasets, and metrics
- `data/extract/aliases.jsonl` mapping each label to a canonical id

No name list is written into source code. A later paper embeds its new labels against these files.

Exit: every label is either aliased or its own canonical node. A read of the largest clusters shows they are one method, not a grab bag.

### D5b. Embeddings

Paper, claim, and canonical Task and Method vectors, as in section 10. Spend is a few cents.

Exit: `data/extract/embeddings/` with the model name and dimension recorded, and a vector count that matches the node counts.

### D6. Freeze

Write `data/extract/manifest.json`: counts, prompt version, model, completion cap, how many papers, claims, canonical nodes, links by `link_source`, how many sentence rows used the compressed fallback, embedding model and dimension, license notes. This manifest is what the product loader is pointed at later.
