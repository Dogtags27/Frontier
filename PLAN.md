# Frontier: Plan v2 (Track 2: Agent Memory and Coordination)

Status: early ideation, nothing frozen except the items marked LOCKED.
Supersedes the earlier "Epigraph" canvas, which is kept only as reference.

## 1. One-line pitch

A persistent research companion for a student starting out in CS research. A team of role-specific agents shares one FalkorDB instance with two kinds of graph: `frontier_corpus` holds the field (papers, claims, methods, open questions, and the only copy of the embeddings), and `frontier_ws_<id>` holds that workspace's memory (what they have read, believed, tried, and ruled out) as ids into the corpus. A research gap is not a one-time suggestion. It is a tracked hypothesis with a lifecycle that the memory keeps current as new papers arrive.

Core idea: a gap lives where the student's knowledge frontier meets the field's open frontier.

## 2. Hackathon constraints that shape the design (from the official page)

- Window: 15 Oct 12:01 AM IST to 18 Oct 11:59 PM IST. In US Eastern that is the deadline Sunday 18 Oct 2:29 PM EDT. Plan to submit by 1:00 PM EDT.
- FalkorDB must be primary and central. If the product works the same without it, the project is disqualified (Rules 2, 3).
- Main FalkorDB implementation must be new work during the window (Rules 8, 9).
- Data must be public, synthetic, or our own. No paywalled, login-protected, private, or personal data (Rule 6).
- Submission needs: public repo, README with setup and graph data model, the Cypher queries or graph algorithms the product depends on, demo video, live deployment or full local setup, the track named, AI-assistant use disclosed (Rules 10, 11).
- We must be able to explain the graph model, queries, architecture, and decisions (Rules 12, 13).
- Enter Track 2 only.

Track 2 official bullets, and where we meet each one:

| Track 2 bullet | Where it lives in Frontier |
|---|---|
| Episodic memory | Reading sessions, hypothesis decisions, kill reasons |
| Semantic memory | Field graph: papers, claims, methods, tasks, datasets, future-work and limitation statements |
| Procedural memory | Reading paths and validation checklists that worked, replayed as step graphs |
| Persistent conversation history | The Chronicler resumes an investigation after a gap in time |
| Shared state and handoffs | Gap lifecycle with gated handoffs between agents |
| High-concurrency reads and writes | Parallel Readers writing to one graph, with conflict handling |
| Separate memory per user or tenant | One private graph per workspace. The corpus and its embeddings stay one shared graph. Private nodes store ids, not copies |

## 3. Staying in Track 2, not Track 1

Gap analysis is graph reasoning, which is Track 1 territory. Our defence is what the product is about:

- The contribution is the memory architecture: persistence, revision, handoff, isolation, concurrency.
- Gap discovery is the workload that exercises the memory.
- The demo spends most of its time on resume, scoop invalidation, handoff gating, tenant isolation, and concurrency. Gap ranking is shown briefly.
- The README names each memory type explicitly and says where it lives.

## 4. Stakeholders

LOCKED: two roles only.

- Student: the primary user. All agents serve this person.
- Supervisor (research-assisting professor): read-only. Sees the student's progress as a timeline over the student's own graph. No supervisor-specific agents, notifications, or functions in this version.

Supervisor implementation notes:
- Same workspace graph, accessed through read-only queries only (`GRAPH.RO_QUERY`, verified: a write errors). Titles are resolved from `frontier_corpus` by the API.
- One page: a timeline of events (papers read, gaps proposed, challenged, killed, adopted, scooped) and current open items.
- If time is short this becomes a static timeline query rendered as a list. It is not allowed to grow.

## 5. Domain and corpus

LOCKED: CS only. Any `cs.*` subfield. Papers are public arXiv preprints. We do not crawl the open web for PDFs.

The MAG-id / ogbn-arxiv slice and the 2025-2026 Kaggle CSV are retired. The corpus starts from arXiv ids.

### Corpus on disk

997 papers in `data/extract/corpus.jsonl`. Every row has an arXiv id, title, abstract, categories, year, and layer, and a staging PDF. 967 citation edges are in `data/extract/cites.csv` (`citing_arxiv_id`, `cited_arxiv_id`). PDFs are in `data/pdfs/{arxiv_id}.pdf` as a local staging copy. That folder is gitignored and is not where the running system reads them. Three ids returned HTTP 404 from arXiv and were removed: `0807.3223`, `2106.09974`, `2403.01085`. They are listed in `data/extract/dropped.json`.

| Layer | Years | Papers |
|---|---|---|
| Foundation | 2007-2019 | 299 |
| Recent | 2020 | 90 |
| Recent | 2021 | 89 |
| Recent | 2022 | 90 |
| Recent | 2023 | 100 |
| Recent | 2024 | 99 |
| Recent | 2025 | 110 |
| Recent | 2026 | 120 |

The foundation layer is the highest-cited `cs.*` papers in that span, capped per subfield and per year. Each recent paper cites at least one foundation paper. 89 cite at least two. 104 papers, mostly older foundation papers, have no edge inside this set. The demo scoop is one later paper filling one gap. Ingest itself accepts any number of papers.

Sources: Cornell arXiv metadata (Kaggle, CC0) for identity and abstracts. Semantic Scholar for citation counts and citation lists. arXiv for PDFs.

### Where a paper lives

The PDF bytes live in Cloudflare R2. Postgres stores the paper row and the object key. `frontier_corpus` stores the shared structure and the embeddings, once. A workspace graph stores that student's research state and the ids of the corpus nodes it refers to.

| Store | Holds | Copied per workspace? |
|---|---|---|
| Cloudflare R2 | The PDF, key `papers/{arxiv_id}.pdf` | No. Not in the container, not in git |
| Postgres on Render, one row per arXiv id, plus one row per sentence | title, year, categories, abstract, `r2_key`, and per sentence the compressed text the model saw and the recovered original sentence | No |
| FalkorDB `frontier_corpus` | arXiv id, title, year, category, embedding, citations, tasks, methods, claims | No. One graph for every user |
| FalkorDB `frontier_ws_<id>` | notes, hypotheses, decisions, agent memory, and `Ref` nodes that store a corpus id | This graph is the private copy. It does not contain paper embeddings |

An agent downloads a PDF from R2 only when it is about to extract or inspect that paper. The address for that download is one row per arXiv id in `data/extract/r2_index.jsonl`: `arxiv_id`, object key `papers/{arxiv_id}.pdf`, and the S3 URL built from the endpoint, bucket, and key. Postgres stores the same `r2_key`. The download uses the S3 client and the credentials in `.env`. The URL is not a public link, and the secret is not part of it. Showing a span reads the extracted text from Postgres. Similarity is a vector on the paper node inside FalkorDB. Postgres is not a second system of record: gap state, handoffs, and history are Cypher only.

R2 is S3-compatible. The free allowance is 10 GB-month of standard storage and egress is not billed. Past 10 GB, standard storage is $0.015 per GB-month. `DATABASE_URL` and the R2 credentials stay in the environment.

## 6. Student persona (drives the demo and every design decision)

Maya, first-year MSc student. Knows Python, has taken ML and databases courses, can implement a model from a tutorial. She has never read a research paper end to end and does not know how to pick a research question. Her supervisor, Prof. Rao, meets her weekly for 30 minutes and is busy.

Her real problems, in the order she hits them (these come from published studies of novice researchers: narrowing a question, finding a genuine gap, knowing when she has read enough, overload, and uncertainty):

| Stage | What Maya says | What goes wrong today | What Frontier does | Memory written |
|---|---|---|---|---|
| 1. Orient | "I don't even know what the field looks like." | Dozens of tabs, no map, unknown vocabulary | Cartographer builds a field map from the corpus and a prerequisite ladder for the topics she picks | Semantic: field graph. Procedural: reading path |
| 2. Read | "I read ten papers and remember none of them." | No record of what she read or understood | Reader extracts structured facets per paper (problem, method, assumptions, datasets, metrics, limitations, future work), keeps a reading queue, records what she has read | Episodic: reading events. Learner model |
| 3. Synthesize | "Papers disagree and I can't tell who is right." | Contradictions and repeated citations look like consensus | Evidence agent links claims to papers with support, contradict, or qualify, and flags when several confirmations share one origin | Semantic: claims with valid_from and valid_to, revised not overwritten |
| 4. Find a question | "Is there anything left to do?" | Gaps are guessed from vibes | GapHunter ranks candidate gaps with an evidence path, and a learning distance from what Maya already knows | Gap candidates with provenance |
| 5. Validate | "Has someone already done this?" | Fear of being scooped, fear of wasting weeks | Prior-art Adversary tries to kill each gap, stores near misses and the kill reason | Episodic: attempts. Decisions |
| 6. Plan | "What would my first experiment be?" | Scope too big | Scoper proposes the smallest experiment using open datasets and baselines already in the graph | Procedural: experiment plan |
| 7. Continue | "Where was I last Tuesday?" | Context lost between sessions | Chronicler produces a resume brief: open question, killed ideas, unread items, next step | Persistent history |
| 8. Report | "What do I tell Prof. Rao?" | Weekly update is written from memory | Prof. Rao opens the read-only timeline and sees what changed since last week | None (read-only) |

Persona script used for the demo (scripted so it is repeatable):

1. Day 1. Maya picks a topic. Frontier shows the map and a reading path. She reads four papers. Each read is recorded.
2. Day 1, later. The Evidence agent shows two claims in conflict. GapHunter proposes three candidate gaps. The Adversary challenges them, and one is killed with a named near-miss paper.
3. Session ends.
4. Day 3. Maya returns. The Chronicler resumes with no transcript replay: her open gap, the killed idea and why, the unread papers.
5. A later paper from the held-out set arrives that fills her favourite gap. The gap closes with a visible path. Frontier proposes the next best gap that overlaps what she already learned.
6. Prof. Rao opens the timeline and sees the change.
7. A second student, Dev, works in the same deployment. He sees none of Maya's hypotheses.
8. Parallel Readers add papers at once. Two agents update the same gap at the same time and the conflict is resolved, not duplicated.

## 7. Gap lifecycle (the core object)

`candidate -> challenged -> alive | killed -> adopted | scooped`

- Every transition is written by a named agent and is a graph write with a provenance path.
- Preconditions are Cypher checks. Example: a gap cannot move to `adopted` until the Adversary has logged an attempt to kill it.
- `scooped` happens when a newly ingested paper addresses the gap's required elements.
- A killed gap is never deleted. It keeps the kill reason and the paper that killed it.

## 8. Gap signals (structural and auditable, not narrated by an LLM)

1. Orphaned future work: a paper states future work and no later paper addresses it.
2. Empty facet cell: method, task, and condition pairs all appear but the triple does not.
3. Unresolved contradiction.
4. Unrelaxed assumption.
5. Supporting signals only: community detection for isolated clusters, PageRank for load-bearing papers.

Ranking: evidence strength, survival of the Adversary, learning distance from the student's known concepts (shortest path in the concept graph), and feasibility (open datasets, small compute).

Rule: every gap is labeled a candidate. "Unobserved" does not mean "novel," and the UI says so.

## 9. Agents

LOCKED: coordination only through graph state. No planner agent, no free-form agent chat.

| Agent | Job | Writes |
|---|---|---|
| Cartographer | Field map, prerequisite ladder | Concepts, prerequisites, reading paths |
| Reader | Structured extraction, reading queue | Facets, read events |
| Evidence | Claims, contradictions, independence | Claim stances, revisions |
| GapHunter | Candidate gaps with evidence paths | Gap nodes |
| Adversary | Tries to kill each gap | Attempts, near misses, kill reasons |
| Chronicler | Resume brief | Session summaries from graph state |

Scoper is a stretch item. Cut first if time is short.

## 10. Graph model (draft)

Field nodes: Paper, Task, Method, Dataset, Metric, Claim (kind: result, quantitative, ablation, failure, limit, future_work, assumption, contribution, question, setup, reproducibility), and Concept for the curriculum. `LLD.md` section 3 is the source for the final model.
Learner nodes, only in `frontier_ws_<id>`: Student, ReadEvent, Gap, Attempt, Decision, Session, Handoff, WorkItem, Event, and `Ref` (a corpus id, with no embedding and no text). Concept stays on the corpus. A `KNOWS` edge points at a `Ref`.
Key edges on the corpus: direct paper edges `(Paper)-[:ADDRESSES]->(Task)`, `USES_METHOD`, `COMPARES_TO`, `EVALUATED_ON`, `REPORTS_METRIC`, which carry the paper's overall setup and are what a gap cell counts. `(Paper)-[:HAS_CLAIM]->(Claim)`, and from a claim `ABOUT_METHOD`, `ON_DATASET`, `MEASURED_BY`. `(Paper)-[:CITES]->(Paper)`, `(Concept)-[:PREREQ_OF]->(Concept)`. Claim-to-claim `SUPPORTS`, `CHALLENGES`, `CONTRADICTS` are thin and only with recorded conditions. Key edges on the workspace: `(Student)-[:KNOWS]->(Ref)`, `(Gap)-[:EVIDENCED_BY]->(Ref)`, `(Attempt)-[:AGAINST]->(Gap)`, `(Attempt)-[:FOUND]->(Ref)`, `(Gap)-[:SCOOPED_BY]->(Ref)`. A gap stores `task_id` and `method_family_id`. It does not copy the Task or Method.
Claims and Gaps carry `valid_from`, `valid_to`, `tx_time`. A claim's text is never on the node. Its `span` is a sentence number into Postgres.

Details are settled in `LLD.md`. The README must contain the final model and the queries.

## 11. Tenancy and concurrency

- One shared corpus graph, `frontier_corpus`, plus one private graph per workspace, `frontier_ws_<id>`. FalkorDB queries one graph at a time and has no cross-graph vector index, so the application searches the corpus and the workspace separately and joins on ids. `GRAPH.COPY` was tested, keeps vectors, and is not used for tenants.
- A new paper is written only into the corpus. Each workspace then reassesses its own open gaps against that paper. That is the stale-propagation test: both students see the new paper, and neither student's nodes move.
- Concurrency: FalkorDB serializes writes per graph. Tested: 20 claimers, one winner, and two gap writers, one winner. Conflict handling is a version check on Gap status inside one query.
- Isolation test: a query run in Dev's graph returns nothing of Maya's hypotheses. The corpus returns the shared paper and nothing private.
- The API maps a workspace id to a graph name. It does not accept a graph name from the client. The demo has no account system. The map is fixed.

## 12. Evaluation

- Temporal backtest: build from papers before a cutoff, rank gaps, check whether later held-out papers filled them. Report the number with its sample size. At this scale it is a demonstration, not statistical proof.
- Hand-labeled gold set of about 30 extracted items. Report extraction precision.
- Failure-mode tests from a 2026 shared-memory taxonomy (cited via a Mem0 blog, verify at the source before citing): unauthorized leakage, stale propagation, contradiction persistence, provenance collapse. Map them to isolation, scoop, claim revision, and provenance path.
- Concurrency test: N parallel writers on one gap and one claim. Expected result stated in advance.

## 13. Work phases

Deadline is still Sunday 18 Oct, 1:00 PM EDT. Phases are ordered by dependency. The product does not start until the data phases have a frozen manifest.

Suggested sequence from Friday evening, with about 40 hours left: Friday night, D4b to D6 (data only, no product code). Saturday morning, WP0 platform checks, then WP1 and WP2 loads. Saturday afternoon, WP3 backtest, which decides the demo story, then WP4 and WP5. Saturday night and Sunday morning, WP6 and WP7, then WP9 proof, README, and video. Submit before Sunday noon. If WP0 or WP3 slips, cut in the order in section 14 rather than shortening the proof package.

| Phase | What | Done means |
|---|---|---|
| D2 | PDFs are in R2. Map is `data/extract/r2_index.jsonl` | One object per corpus id. Local `data/pdfs/` is not the runtime store |
| D3 | Token report and compression report written. No document cap | `token_report.json`, `compression_report.json` |
| D0 | 10-paper pilot, three prompt generations, prompt frozen at `d0-6` | Done |
| D4 | Extract all 997, one paper per call, eight in flight | Done. 997 of 997, 48,654 items, $9.10 at list price. `data/extract/{foundation,recent}/facets.jsonl` |
| D4b | Sentence table: the compressed sentence the model saw and the recovered original, per paper | Numbering check passes for every paper, or the paper is listed with a fallback |
| D4c | Clean-up and survey flag | Repeats dropped, survey-like papers listed and read once |
| D4d | Claim linking: sentence number and lexical matching first, the model only for what is left | Sample of 40 claims hand-checked. Model step runs on all papers only at 80% precision or better |
| D5 | Vocabulary: cluster the labels, name the clusters, write canonical and alias files | Every label is aliased or canonical. Largest clusters read |
| D5b | Embeddings: paper, claim, and canonical Task and Method vectors | Counts match node counts. Model and dimension recorded |
| D6 | Freeze `data/extract/manifest.json` | Loader can point at one manifest |
| WP0 | FalkorDB platform checks on synthetic data | Done. Client, atomic claim, read-only query, vector query, and copy-keeps-vectors all passed. Copy is not the tenant design. A filter applies after the nearest k, and a vector score is a distance |
| WP1 | Load structure into `frontier_corpus` only. No abstract or PDF body on the node | Counts match the manifest. Reload does not duplicate. No workspace graph exists yet |
| WP2 | Load facets and embeddings onto `frontier_corpus` | Alias edges exist. A near-miss query returns neighbors. Embeddings exist in one graph |
| WP3 | Backtest: gaps from 2007-2019, see which 2020-2026 papers fill them | One real scoop written down, or the demo story changes |
| WP4 | Create Maya's and Dev's workspace graphs with private nodes and corpus ids | Dev's graph has none of Maya's gaps. The corpus has no workspace nodes and is the only copy of the embeddings |
| WP5 | Work queue, handoff precondition, events | Parallel claim has one winner. A blocked handoff stays visible |
| WP6 | Agents on that queue | A note becomes a ranked gap and an Adversary verdict |
| WP7 | Scoop and revision | One ingested paper scoops one gap. An as-of query returns the old belief |
| WP8 | Backend APIs only | Student actions and the timeline are queries |
| WP9 | Isolation, concurrency, README, video | Every README claim points at a query or a test |

## 14. Scope rules

Must have:
- Field graph, learner model, gap lifecycle with a Cypher-gated handoff.
- Chronicler resume, scoop invalidation, two-tenant isolation, concurrency test.
- Read-only supervisor timeline.

Cut order if behind: Scoper, link-prediction scoring, blog, prerequisite ladder polish, Cartographer polish.

Never: second track, supervisor-specific functions, a fifth agent, real student data, auth system, full corpus scale.

## 15. Submission checklist

- [ ] Registered on the WeMakeDevs page
- [ ] Public repo
- [ ] README: setup, graph data model, memory-type mapping, AI-assistant disclosure
- [ ] The Cypher queries and graph algorithms the product depends on
- [ ] Demo video from the persona script
- [ ] Live deployment, or complete local setup instructions
- [ ] Track named: Agent Memory and Coordination
- [ ] Data is public or synthetic, with source notes
- [ ] We can explain every query and design decision

## 16. Open items

- Product name. "Frontier" is a working title.
- Which of the 2020-2026 papers is the one scoop in the demo. Chosen in WP3 from the backtest, not before.
- Render `DATABASE_URL` has not been provided. Development can use a local Postgres in Docker with the same schema.
- Whether the model linking pass is worth running on all papers. Decided by precision on a 40-claim hand-checked sample.
- Embedding dimension stays 1,536 unless the single corpus graph does not fit. There is no per-user copy to size for.
- Survey-like papers: nine list 20 or more techniques. They are flagged and use `MENTIONS_METHOD` until reviewed.
