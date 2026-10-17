# Frontier Backend Plan (v3)

Status: plan only, no backend code yet. Written 16 Oct 2026, after the data phase closed.
Scope: Python backend API, agents, auth, rate limiting. No frontend.
Targets: Track 1 (Agents That Act on Connected Data) and Track 2 (Agent Memory and Coordination). Not Track 3.
Deadline: Sun 18 Oct, submit by 1:00 PM EDT (hard stop 2:29 PM EDT).

This file supersedes `PLAN.md` sections 3, 4, 9, 11, 14 and `LLD.md` sections 2, 6, 11, 12 wherever they disagree (see section 1). Graph model, extraction, vocabulary, and the gap/scoop logic from `LLD.md` sections 3, 5, 8, 9, 10 stay valid and are reused.

---

## 1. What changed from the older plans

| Older plan said | Now |
|---|---|
| Track 2 only, and "never a second track" | Track 1 and Track 2. Track 1 is carried by graph-algorithm tools, MCP tool selection, multi-hop answers, and explainable traces. Track 2 is carried by the memory and coordination layers |
| Supervisor is read-only with no functions | Supervisor is a real account with one organisation and a class code. An enrolled student's progress is one high-level summary (gaps, reading, decisions, notes, timeline, graph counts). No chats, no raw graph dump, no write |
| No auth system, fixed workspace map | Supabase Auth issues identity. Our API verifies that JWT on every protected route, then checks role and enrollment in our own tables. A per-user graph is created at first sign-in. The client never names a graph |
| No planner agent, no free-form agent chat | Still no agent-to-agent chat and no planner that coordinates agents. A stateless **intent engine** (LLM) classifies the request and fills slots. Agents still coordinate only through graph state |
| Postgres holds no student data | Postgres now holds **account and operational** data only (users, orgs, tokens, usage). All research state still lives in the graph |
| Four fixed demo personas | Any number of users. Maya and Dev become seed users created through the real signup path |
| Demo needs one scripted scoop | Kept. The held-out paper `2007.15251` is ingested through the admin ingest endpoint |

Unchanged and locked: one shared `frontier_corpus` graph holding the only copy of embeddings; one private graph per user; private nodes store ids, not copies; gap lifecycle enforced in Cypher; claim and transition are single atomic queries; evidence text comes from the Postgres sentence table.

---

## 2. Goals, and how each requirement maps

| Requirement from the brief | Where it is met |
|---|---|
| Semantic and metadata search of papers | `SearchService` with three channels (vector, fulltext/metadata, Postgres abstract text) fused by rank. Section 7 |
| Assist a research student in many ways | Intent catalog in section 6, each intent backed by tools and an agent |
| Student-in-charge sees enrolled students' progress | Organisation, class code, `AccessPolicy`, one summary built from an allowlisted query set. Section 5 |
| Auth and rate limiting | `Auth`, `RateLimiter`, and a per-user LLM budget. Section 9 |
| LLM for intent discovery and query building | `IntentEngine`, plus tool selection inside each agent. Section 6 |
| One corpus graph plus one graph per signup | `GraphStore` and `WorkspaceService.provision`. Section 4 |
| Postgres, FalkorDB, R2 | `Stores` layer, one class per backend. Section 4 |
| Main agents live here | Agent roster on a shared base class. Section 8 |
| No repetition, short comments, class-based, few folders | Conventions in section 3 |

Track 1 coverage:

| Track 1 bullet | Where |
|---|---|
| Multi-hop reasoning | Tools: `citation_chain`, `shortest_path`, `learning_distance`, `gap_cells`, `near_miss`. The agent chains them and the answer carries the path |
| Graph queries and algorithms as agent tools | `GraphToolkit` exposes PageRank, weakly connected components, shortest path (all passed WP0), and community detection and BFS (VERIFY before promising) |
| Tool selection through MCP | The same toolkit is served as an MCP server at `/mcp`. The in-app agent and an external MCP client (Cursor, Claude Desktop) see identical tools |
| Actions based on what the graph shows | Gap proposals, kill verdicts, reading-path updates, scoop invalidation. All writes are graph transitions |
| Explainable results | Every answer returns `evidence[]` (ids and original sentences) and `trace[]` (tool calls and graph paths) |

Track 2 coverage is the table in `LLD.md` section 14, extended in section 10 below with conversation history and per-user memory management.

---

## 3. Engineering conventions (how the code stays small and non-repeating)

1. **One definition, many uses.** A tool is one class with a Pydantic input model. That single class produces the OpenAI function schema, the MCP tool schema, the FastAPI request body where the tool is also a REST endpoint, and the validation. No tool is described twice.
2. **Registries by decorator.** `@agent`, `@tool`, `@intent` register a class. Adding an agent, tool, or intent is one class in one file. Nothing else is edited.
3. **All query text lives in `queries.py`** as named constants (`Q.CLAIM_WORK_ITEM`, `Q.CELL_COUNT`, `SQL.PAPER_BY_ID`). Services call names, not strings. Cypher is parameterized always, never formatted with user text.
4. **One choke point per store.** `GraphStore.run(graph, query, params, ro)`, `Pg.fetch/execute`, `Blob.presign/get`. Timeouts, retries, logging, and the read-only rule are written once there.
5. **Services own domain logic, routers own HTTP only.** A router function is: parse, resolve access, call one service method, return. No query and no LLM call in a router.
6. **One access path to a user graph:** `WorkspaceResolver.open(principal, student_id, need="write"|"summary")`. `write` is the student on their own graph. `summary` is an enrolled supervisor and can run only the named progress queries. Nothing else can construct a graph name.
7. **Dependency container.** A single `Container` built in the app lifespan holds the stores, LLM client, limiter, and services. Routers and workers get it by dependency injection. Tests swap it.
8. **Comments:** a one-line docstring on every class and any non-obvious function, stating its job and its one gotcha. No long prose in code.
9. **Config:** `pydantic-settings`, one `Settings` class, reads `.env`. Two model names only, `chat` (`gpt-4.1-mini`) and `embed` (`text-embedding-3-small`), read from settings. No stronger model. Hosts for FalkorDB, Postgres, Supabase, and R2 are settings too, so nothing in services hardcodes `localhost`.
10. **Errors:** a small `AppError` hierarchy (`NotFound`, `Forbidden`, `Conflict`, `RateLimited`, `Upstream`) mapped to HTTP in one handler.

---

## 4. Architecture and data stores

```
 client / MCP client
        |
   FastAPI app (api/*)  ----  Auth, RateLimiter, AccessPolicy (dependencies)
        |
   Services (accounts, workspace, search, papers, memory, gaps, ingest)
        |                 \
   IntentEngine -> Agents -> GraphToolkit (tools)      <- also served at /mcp
        |                         |
   Stores:  GraphStore (FalkorDB)   Pg (Postgres)   Blob (R2)   LLM (OpenAI)
        ^
   worker.py (same code, same container) drains WorkItems
```

One Docker image, two entry points: `uvicorn app.main:app` and `python -m app.worker`. For development, a compose file runs FalkorDB, Postgres, the API, and the worker on localhost. `GraphStore` takes host, port, and password from `Settings`, so pointing the same code at a VM later is an env change. The compose FalkorDB service is the piece removed at deploy time. No service contains a literal host.

### 4.1 What lives where

| Store | Holds | Never holds |
|---|---|---|
| FalkorDB `frontier_corpus` | Papers, claims, Task/Method/Dataset/Metric/Concept, citations, canonical vocabulary, the only embeddings, corpus WorkItems | Any user or workspace node |
| FalkorDB `frontier_ws_<user>` | One user's memory: Student, Session, Conversation, Turn, ReadEvent, Gap, Attempt, Decision, ReadingPath, Memory facts, WorkItem, Handoff, Event, `Ref` | Paper text, paper embeddings, other users' data |
| Postgres | Papers (metadata, abstract, `r2_key`), 658k sentence rows, **plus new:** user profiles, orgs, enrollments, class invites, llm_usage, idempotency keys | Passwords, refresh tokens, research state, gaps, memory, handoffs, PDFs, chat text |
| R2 | PDFs under `papers/{arxiv_id}.pdf` | Anything else |
| Redis protocol on the FalkorDB instance | Rate-limit counters and worker wake-up hints (`rl:*`, `wq:*` keys). Disposable | Any truth. Losing it loses nothing |

Rate limiting on the FalkorDB Redis instance avoids a fourth service. If the host blocks plain keys, fall back to Postgres counters (slower, same interface).

### 4.2 Graph naming and provisioning

- Graph name: `frontier_ws_<user_uuid_hex>`. Derived only from the authenticated user id, in `WorkspaceResolver`.
- **Signup saga (idempotent):** insert user row with `graph_status='pending'` -> create graph, run schema bootstrap (constraints, indexes, `Student` node) -> set `graph_status='ready'`. A startup sweeper and the first login retry any `pending` row. Re-running bootstrap on an existing graph is a no-op.
- Workspace schema bootstrap lives in one `WorkspaceSchema.ensure(graph)` method, and the same method is used by tests and the seed script.
- Workspace vector index only on the small private nodes (`Memory`, `Turn` summaries, `Gap` hypothesis text). Dimension 1536, same model as the corpus, recorded on the graph.
- Delete account: delete the graph, delete Postgres rows, keep an anonymised usage ledger.

### 4.3 Two-graph reads

FalkorDB cannot join across graphs, so every cross-graph answer is two queries merged in Python. This is wrapped once in `GraphStore.join_refs(rows, id_key)`: take ids from the workspace result, fetch titles or cells from the corpus in one batched query, attach. Services never hand-roll this.

---

## 5. Auth, roles, organisations, access

### 5.1 Roles

Two stakeholders only, as before, plus an operational `admin` flag for ingest and usage endpoints.

| Role | Can |
|---|---|
| student | Everything on their own graph. Search the corpus. Chat with agents |
| supervisor ("student in charge") | Create an organisation and a class code with a shareable join link. See each enrolled student's progress as one summary. Search the corpus. Cannot open chats, conversations, raw memory, or jobs, and cannot write any student graph |
| admin | Ingest papers, view usage and queue. Granted only when every check in section 5.5 passes. The email allow-list is one of those checks |

### 5.2 Postgres account tables (new)

`users(id, email, role, display_name, org_id?, graph_name, graph_status, created_at, disabled)`. `id` is the Supabase user id. `email` is stored normalized (trim, lowercase). No password and no refresh token
`orgs(id, name, owner_supervisor_id)`
`enrollments(supervisor_id, student_id, org_id, status, created_at)` primary key on the pair
`invites(code_hash, org_id, created_by, expires_at, max_uses, used, revoked)`. One live class code per org. Many students can use it until it expires, hits `max_uses`, or the supervisor revokes it
`llm_usage(id, user_id, endpoint, model, prompt_tokens, completion_tokens, usd, at)`
`idempotency(key, user_id, response_hash, at)` for retried writes

There is no access log and no endpoint that tells a student who looked at their progress.

Migrations are plain numbered SQL files applied by a ten-line runner. No ORM. Queries use `psycopg` with a pool.

### 5.3 Auth flow (Supabase)

Supabase Auth owns signup, password, email verification, sessions, and token refresh. This API does not hash passwords and does not store refresh tokens.

- The client signs in with Supabase and sends the Supabase access token as `Authorization: Bearer`.
- `current_principal` runs on every route except `GET /healthz` and `GET /readyz`. It verifies the JWT against the Supabase JWKS (issuer and audience checked), rejects expired tokens, and reads `sub` and `email`.
- Email is normalized before it is stored or compared. `email_confirmed` must be true before the account can provision a graph or call any product route. An unverified token gets `403`.
- First verified request upserts the `users` row and runs the graph provisioning saga in section 4.2. Role is chosen at signup (`student` or `supervisor`) and stored in our table. Supabase app metadata is not trusted for authorization.
- A supervisor's first verified request also creates their org and one class invite. The response includes the code and a join path, `/join/{code}`. The raw code is shown once at creation and again to the owning supervisor. Only its hash is stored.
- A student joins by `POST /orgs/join` with that code, or later by opening the shareable link, which carries the same code. Joining creates the enrollment. A student can join after signup. A bad, expired, exhausted, or revoked code returns the same `404`.

`Principal` is a dataclass built per request: `user_id`, `email`, `email_verified`, `role`, `org_id`. Role and org come from our tables, not from the token.

### 5.4 Access policy (the only place that decides)

`AccessPolicy.check(principal, student_id) -> Access(mode)`:

1. `student_id == principal.user_id` -> `write`.
2. Principal is a supervisor and an `enrollments` row is `active` for that pair -> `summary`.
3. Otherwise `404`, so the response does not confirm that the user exists.

Enrollment is read from Postgres on every request. Removing a student takes effect on the next call.

`summary` is not a general read of the student's graph. `WorkspaceResolver` in that mode exposes one method, `progress()`, which runs a fixed set of named queries:

- gap counts by status, plus the open gaps with title, score, and evidence count
- reading counts and the recent reading list (paper id, depth, short note)
- recent decisions (kind, reason, whether invalidated)
- a timeline of research events only (`gap_opened`, `challenged`, `alive`, `killed`, `adopted`, `scooped`, `decided`, `evidence_added`, `read`)
- graph totals: counts of gaps, reads, decisions, and known concepts

Those queries do not match `Conversation`, `Turn`, chat events, or raw memory facts. A supervisor token on `/chat`, `/conversations`, `/memory`, or `/jobs` is `404`. The summary handle uses `GRAPH.RO_QUERY`, so a write fails at the database as well as at the policy.

Student routes stay under `/students/{student_id}/...` with `student_id` of `me`. Supervisor progress is `GET /students/{student_id}/progress` and nothing else on that graph.

### 5.5 Admin authorization

`ADMIN_EMAILS` is a comma-separated env allow-list. It is not sufficient on its own. `require_admin` runs on every admin route, including ingest, and requires all of the following:

1. A valid Supabase JWT from section 5.3.
2. `email_confirmed` is true.
3. The normalized email is currently in `ADMIN_EMAILS`.
4. `users.role` is `admin` and `disabled` is false. The role is set on the verified request that first finds the email on the allow-list, and cleared on the next request if the email is no longer listed.
5. The route's rate limit and body limits.

A token, a database role, or an allow-list hit alone is denied. Tests cover an unverified allow-listed email, a verified email that was removed from the list, and a verified admin whose row was disabled.

---

## 6. User intent discovery and how a student can use the product

### 6.1 Intent catalog

Each intent is one `@intent` class naming: a description (used for classification), slot schema, the agent that serves it, whether it is interactive or a queued job, and whether it writes memory.

| # | Intent | Example | Slots | Served by | Mode |
|---|---|---|---|---|---|
| 1 | `explore_topic` | "I'm new to federated learning" | topic | Cartographer | job + stream |
| 2 | `find_papers` | "papers on graph coloring after 2020 using LLMs" | query, filters | Scout (search tools) | interactive |
| 3 | `lookup_paper` | "what is 1409.1556 about" | paper | Reader | interactive |
| 4 | `compare` | "compare ResNet and VGG on ImageNet" | methods or papers | Reader + Evidence | interactive |
| 5 | `trace_lineage` | "what does this paper build on", "path between A and B" | paper(s) | Scout (graph tools) | interactive |
| 6 | `find_gaps` | "what is unexplored around coloring?" | task/method seeds | GapHunter | job + stream |
| 7 | `validate_idea` | "has anyone done defective list coloring for small messages?" | idea text | Adversary | interactive |
| 8 | `check_evidence` | "do papers agree on X?" | claim or topic | Evidence | interactive |
| 9 | `plan_reading` | "what should I read next?" | goal | Cartographer | interactive |
| 10 | `plan_experiment` | "smallest experiment for this gap" | gap | Scoper (stretch) | interactive |
| 11 | `record` | "I read paper X, I think the main limit is Y" | note, paper, depth | Reader (note path) | interactive |
| 12 | `resume` | "where was I last Tuesday?" | since | Chronicler | interactive |
| 13 | `progress_report` | "what do I tell my supervisor?" | period | Chronicler | interactive |
| 14 | `ask_memory` | "what did I decide about the coloring gap and why?" | query | Memory recall | interactive |
| 15 | `clarify` / `smalltalk` | ambiguous or off-topic | none | none | interactive |

There is no supervisor chat intent. A supervisor does not talk to an agent about a student. Their view is the progress summary in section 5.4.

### 6.2 IntentEngine (LLM used for quality)

`IntentEngine.understand(principal, message, conversation) -> Plan`:

1. **Context pull (no LLM):** last turns, open gaps, current reading path, top recalled memories (section 10). Cheap and bounded by a token budget.
2. **Classify and fill slots (`gpt-4.1-mini`, structured output):** returns `intent`, `confidence`, `slots`, `needs_clarification`. The system prompt is generated from the `@intent` registry, so adding an intent updates the prompt automatically. There is no second, larger model. Quality comes from the structured schema, the shortcut in step 5, and a short prompt.
3. **Entity resolution (no LLM):** free-text task, method, dataset, and paper titles are resolved to canonical ids by alias lookup then vector nearest neighbour on the corpus. Unresolved entities are returned to the user as a clarification, not guessed.
4. **Plan:** `Plan(intent, slots, resolved_entities, steps?)`. A low-confidence plan routes to `clarify` and asks one question.
5. **Cost control:** exact-match shortcuts (paper id pasted, slash commands such as `/resume`) skip the LLM. Embedding similarity against cached intent exemplars is tried first; the LLM is called only below a threshold or when slots are needed.

### 6.3 Query building

The LLM never writes Cypher or SQL. It chooses tools and fills their typed arguments; tools run fixed parameterized queries. This is both the safety design (no injection, no cross-tenant access) and the explainability design (a tool call is a readable step).

---

## 7. Search design (semantic and metadata)

`SearchService.search(SearchRequest)` where `SearchRequest` has `q`, `mode` (`semantic`, `metadata`, `hybrid`), and filters: `year_from`, `year_to`, `category`, `layer`, `paper_kind`, `task`, `method`, `dataset`, `metric`, `cites`, `cited_by`, `unread_only`, `limit`, `cursor`.

| Channel | Source | Notes |
|---|---|---|
| Vector | FalkorDB `db.idx.vector.queryNodes` on `Paper` and `Claim` embeddings | The score is a distance (smaller is nearer). A filter runs after the nearest k (WP0), so the service **over-fetches** (`k = limit * 5`, capped) and filters, and retries with a larger k if too few survive |
| Fulltext and structure | FalkorDB fulltext index on titles and canonical names, plus Cypher filters on year, category, and edges to canonical Task/Method/Dataset/Metric | Filters by canonical node use alias resolution first |
| Abstract text | Postgres `tsvector` GIN index on `papers.abstract` (added by a migration) | Covers keyword matches on abstract that the graph does not hold |

Fusion: reciprocal rank fusion across the channels that ran. Each result reports `matched_by` (which channels), the matched claim or sentence if any, and a short original-sentence snippet from Postgres. Titles and snippets are joined in with one batched lookup.

Personalization in the same call: the user's graph returns the `Ref` ids they have read, are queued, or have ruled out; the service tags each hit (`read`, `queued`, `unread`) and supports `unread_only`. This is the two-graph join of section 4.3.

Query embeddings are cached in a small TTL cache keyed by text hash. Search endpoints are not LLM-heavy, except one embedding call, so they cost 1 rate-limit unit. Also served: `GET /vocab/suggest?kind=task|method&q=` for filter autocomplete from canonical nodes.

---

## 8. Agents

### 8.1 Shape

One `Agent` base class:

```
class Agent:
    name, work_types, tools (subset of the registry)
    async def handle(self, ctx, item) -> AgentResult   # one job
    async def stream(self, ctx, plan)  -> events       # interactive path
```

`AgentContext` carries principal, access mode, the workspace handle, corpus handle, LLM client, memory, and a `Trace` recorder. The base class implements: the tool-call loop (bounded steps, bounded tokens), result validation, trace and evidence collection, `Event` writing, usage ledger. Each concrete agent only declares prompt, tools, and its specific writes. This is where repeated code is prevented.

### 8.2 Roster

The six agents from `PLAN.md` section 9 stay, plus `Scout` for search and graph navigation because the product now has direct search and lineage use cases. Scoper stays a stretch item.

| Agent | Serves intents | Tools it may use | Writes (workspace) | LLM |
|---|---|---|---|---|
| Scout | 2, 5 | `search_papers`, `expand_neighbors`, `citation_chain`, `shortest_path`, `pagerank_in_topic` | Search `Event`, optional reading-queue entries | Tool choice and summary |
| Cartographer | 1, 9 | `field_map`, `communities`, `pagerank_in_topic`, `prereq_ladder`, `learning_distance` | `ReadingPath` (ordered `NEXT` edges on `Ref`), `KNOWS` hints | Cluster naming, narration |
| Reader | 3, 4, 11 | `get_paper`, `get_sentences`, `compare_papers`; note path writes memory | `ReadEvent`, `KNOWS`, `Memory` | Extract depth/knowledge from notes, narration |
| Evidence | 4, 8 | `claims_for`, `claim_stance`, `provenance_roots` (walks `CITES`) | Stance edges (corpus, admin only) or private findings | Narrow pair compare |
| GapHunter | 6 | `gap_cells`, `neighbor_strength`, `learning_distance` | `Gap` (candidate), `EVIDENCED_BY` refs | Narration only. **Detection is deterministic Cypher** |
| Adversary | 7 | `cell_lookup`, `near_miss`, `citation_chain` | `Attempt`, gap transition, kill reason | Judges near misses |
| Chronicler | 12, 13 | `timeline`, `session_summary`, `open_items`, `since` | `Session.summary`, brief | Phrasing. Content chosen by query. Student graph only |

The intent engine is not an agent in the coordination sense: it classifies and dispatches, holds no state, and never talks to other agents. Agents never call each other. If one needs another's work it enqueues a `WorkItem` (section 10).

### 8.3 Tools (`GraphToolkit`)

Each tool: `name`, Pydantic `Input`, `Output`, `scope` (`corpus`, `workspace_rw`), `run(ctx, input)`. Supervisor tokens are not given the toolkit. Their only student-graph read is `progress()`.

Corpus tools: `search_papers`, `get_paper`, `get_sentences`, `expand_neighbors`, `citation_chain`, `shortest_path`, `pagerank_in_topic`, `communities`, `gap_cells`, `cell_lookup`, `near_miss`, `claims_for`, `provenance_roots`, `prereq_ladder`, `compare_papers`.
Workspace tools: `recall_memory`, `my_gaps`, `my_reading`, `timeline`, `open_items`, plus write tools `record_read`, `record_note`, `propose_gap`, `transition_gap`, `record_decision`, `queue_reading`.

**MCP:** the toolkit is mounted at `/mcp` (streamable HTTP, official `mcp` Python SDK). The MCP session reuses the same bearer-token auth, principal, rate limiter, and policy. Per-tool access mode is enforced identically. Selecting tools through MCP is then a demo: point an external client at the server and it can run the same multi-hop investigation.

### 8.4 Explainability contract

Every agent result and every chat final message has this shape:

```
Answer { text, evidence[ {ref_type, ref_id, title, span, original_sentence} ],
         trace[ {step, tool, args, result_summary, graph_path?} ],
         caveats[ ] }       # e.g. "a gap means not found in these 997 papers"
```

Graph paths are lists of node ids and edge types so a client can draw them. The trace is stored on the student's own conversation. Research state changes are separate `Event` nodes, and those are what the supervisor summary lists. Chat traces are not.

### 8.5 Safety

- Paper text and student notes are untrusted. Tool outputs go to the model inside delimited data blocks with a fixed instruction not to follow instructions inside them.
- Hard limits per request: max tool steps (8), max tokens, max wall time. Exceeded = stop with a partial answer and a caveat.
- Models are called with structured output and validated; invalid output retries once, then fails with a typed error.

---

## 9. Rate limiting, quotas, and cost control

Three layers, all in one `RateLimiter` class used as a dependency:

| Layer | Rule | Key |
|---|---|---|
| Request rate | Token bucket per user and per IP. Auth endpoints are stricter and keyed by IP and email to slow credential stuffing | `rl:user:<id>`, `rl:ip:<ip>` |
| Cost weight | Each route declares a cost in units (`@limit(cost=1)` for reads, 5 for a chat turn, 20 for gap discovery or topic mapping). A bucket spends the cost | same bucket |
| LLM budget | Daily token and dollar cap per user (and per org), checked before an LLM-heavy call from the `llm_usage` ledger summary. A global monthly circuit breaker disables LLM routes and leaves read routes up | Postgres, cached 30 s |
| Concurrency | Max concurrent streaming agent runs per user (default 2) | `rl:conc:<id>` |

- Tiers (`student`, `supervisor`, `admin`) are config, not code.
- Replies: `429` with `Retry-After` and a body naming which limit fired.
- Atomic increments with a Lua script on Redis so multiple API workers agree. In-memory fallback in tests.
- Every LLM call goes through `LLM`, which writes the ledger row, so the budget and the admin usage report share one source.
- Safety extras: request body size limit, query `limit` caps, max batch size on ingest, idempotency keys on write endpoints.

---

## 10. Memory and coordination (Track 2 in the backend)

### 10.1 Memory taxonomy in the user's graph

| Memory type | Nodes | Written by | Read by |
|---|---|---|---|
| Episodic | `Session`, `Conversation`, `Turn`, `ReadEvent`, `Attempt`, `Decision`, `Event` | Every route and agent through one `Memory.event(...)` call | Chronicler and `resume` see all of it. The supervisor summary sees research events, reads, and decisions only |
| Semantic | `Memory` fact (`kind`: interest, belief, preference, constraint, `valid_from`, `valid_to`, `tx_time`, embedding), `KNOWS` to `Ref`, `Gap` | `MemoryWriter` after a turn, and the Reader note path | `recall_memory`, intent context |
| Procedural | `ReadingPath` (ordered `NEXT`), `Playbook` (steps that worked: a validation checklist that killed or confirmed a gap) | Cartographer, Adversary | Cartographer replays or adapts it |

`MemoryService` is one class with `event()`, `remember()` (dedupes by vector similarity and entity, closes the old fact with `valid_to` on contradiction instead of overwriting), `recall(query, budget)` (vector over private nodes, recency boost, open gaps always included), `forget(id)` (user control), and `as_of(date)`.

After each chat turn, a background item `summarize_turn` writes a short episodic summary and any durable semantic facts. This keeps request latency low and memory current. Conversation history persists across sessions and restarts because it is graph data, not process state.

### 10.2 Coordination without a planner

Unchanged from `LLD.md` section 6, now with concrete placement:

- `WorkItem` nodes live in the graph they affect. Corpus items (`ingest_paper`, `extract_paper`) on `frontier_corpus`. User items (`map_field`, `find_gaps`, `challenge_gap`, `reassess_gap`, `write_brief`, `summarize_turn`) on that user's graph.
- Claim is one Cypher statement (match open or expired lease, set claimed, return). Complete and fail are version-checked.
- `Handoff` nodes with a Cypher precondition gate the Adversary and Chronicler pickups. A blocked handoff stays visible with its reason and is returned by the API.
- Gap transitions are single versioned queries. A stale writer matches zero rows and receives a `409 Conflict` with the current state.

### 10.3 Worker and job discovery

Polling every user graph is wasteful. The worker uses a hint plus truth design:

1. Whoever creates a `WorkItem` also `LPUSH`es the graph name to `wq:hints`.
2. A worker `BRPOP`s a hint, then claims in that graph by the atomic query. If it loses the race, it moves on.
3. A sweeper every 30 s finds graphs with expired leases or items older than a threshold and re-pushes hints. Losing Redis only delays work.
4. Each worker holds a small concurrency pool (default 4). Per-graph writes are serialized by FalkorDB, so workers do not need locks.
5. Interactive routes that start a job return `202` with a `job_id`; progress arrives by `GET /jobs/{id}` and by the SSE stream when the caller asked to follow it.

### 10.4 High concurrency

The tests in section 13 state the expected outcomes in advance: N parallel claimers, one winner; two writers on one gap, one wins, the other gets 409; parallel `record_read` on one paper dedupes by key; two users writing at once never touch each other's graph.

### 10.5 Scoop and revision

Reused from `LLD.md` section 9. `IngestService.ingest(papers)` writes into the corpus only, then enqueues `reassess_gap` for each user graph that has an open gap in an affected cell. The query finding "which users have open gaps in this cell" is the one exception to the per-graph rule. It is answered from a small Postgres table `open_gap_index(user_id, task_id, method_family_id)` maintained by gap transitions (id pairs only, no content). That is an index, not a second source of truth, and it can be rebuilt by scanning graphs.

---

## 11. API surface

Auth required except where noted. Cost is in rate-limit units.

| Group | Endpoints |
|---|---|
| Health | `GET /healthz` (public), `GET /readyz` (checks the three stores) |
| Auth | No password routes. `POST /me/bootstrap` (verified Supabase token) provisions the profile, graph, and, for a supervisor, the org and class code. Signup and login stay in Supabase |
| Account | `GET/PATCH/DELETE /me` |
| Organisation | `POST /orgs/{id}/invites` rotates the class code. `GET /orgs/{id}/invite` returns the code and join path to the owning supervisor. `POST /orgs/join` takes the code. `GET /orgs/{id}/students`, `DELETE /orgs/{id}/students/{sid}` |
| Corpus | `GET /papers/search`, `GET /papers/{id}`, `/papers/{id}/facets`, `/papers/{id}/sentences?n=`, `/papers/{id}/neighbors`, `/papers/{id}/pdf` (short-lived presigned R2 URL), `GET /vocab/suggest`, `GET /graph/path?from&to`, `GET /graph/explore?id&depth` |
| Student workspace (self only) | `GET /overview`, `/timeline`, `/gaps`, `/gaps/{id}`, `/reading`, `/memory`, `/brief`, `/graph`, `/conversations`, `/conversations/{id}`. Writes: `POST /notes`, `/reads`, `/gaps/{id}/transition`, `/decisions`, `/reading/queue`, `DELETE /memory/{id}` |
| Chat and agents (self only) | `POST /chat` (SSE: `intent`, `tool_call`, `tool_result`, `token`, `final`), `POST /agents/{name}/run` (job), `GET /jobs`, `GET /jobs/{id}` |
| Supervisor | `GET /students/{sid}/progress` for an enrolled student. One summary object, as specified in section 5.4. No ask route and no conversation route |
| Admin | `POST /admin/papers` (ingest batch), `GET /admin/queue`, `GET /admin/usage` |
| MCP | `/mcp` (same auth and limits) |

Conventions: Pydantic request and response models for every route, cursor pagination, `Idempotency-Key` header on writes, error body `{code, message, detail}`, request id on every response.

---

## 12. Repository layout

One backend folder, four subfolders, roughly 30 files. A folder exists only where it groups many files of one kind.

```
backend/
  pyproject.toml            deps and tool config
  Dockerfile  docker-compose.yml  .env.example
  migrations/               001_accounts.sql, 002_usage.sql, 003_search.sql ...
  scripts/                  seed_demo.py (Maya, Dev, supervisor), bootstrap.py (indexes), smoke.py
  tests/                    pytest, one file per area
  app/
    main.py                 create_app(), lifespan, router mounting, error handler
    config.py               Settings
    core.py                 Container, AppError hierarchy, Registry helper, Trace, ids/clock
    stores.py               GraphStore, Pg, Blob (R2)
    llm.py                  LLM client: chat, structured, embed, cache, retry, ledger
    security.py             SupabaseTokenVerifier, Principal, AccessPolicy, require_admin, RateLimiter
    queries.py              all Cypher (Q) and SQL (SQL) text
    schemas.py              Pydantic models shared by API, tools, agents, MCP
    intent.py               IntentEngine and @intent classes
    tools.py                GraphToolkit, @tool classes, MCP mounting
    worker.py               Worker loop, sweeper
    services/
      accounts.py           AccountService, OrgService
      workspace.py          WorkspaceResolver, WorkspaceSchema, provisioning
      search.py             SearchService
      papers.py             PaperService (facets, sentences, presign), IngestService
      memory.py             MemoryService, MemoryWriter
      gaps.py               GapService (signals, lifecycle, reassess, scoop)
    agents/
      base.py               Agent base class, tool loop, registry
      roster.py             Scout, Cartographer, Reader, Evidence, GapHunter, Adversary, Chronicler
    api/
      deps.py               current_principal, container, limiter dependencies
      auth.py  papers.py  students.py  chat.py  admin.py   routers, thin
```

Python choices: FastAPI with async routes, `falkordb` async client, `psycopg` 3 pool, `boto3` for R2 presigning (run in a thread), the official `openai` SDK, `mcp` SDK, `pyjwt` with Supabase JWKS, `pydantic-settings`, `structlog`, `pytest` and `pytest-asyncio`. Passwords stay in Supabase, so there is no password-hashing library here.

Each service is a class constructed once with the `Container`. Approximate sizes keep each file readable; if `queries.py` or `roster.py` grows past about 600 lines it is split, and not before.

---

## 13. Testing and proof (maps to hackathon rules 12 and 13)

| Test | Expected result (stated in advance) |
|---|---|
| Isolation | A query as Dev returns nothing of Maya's. The corpus contains no workspace nodes. Embeddings exist only on the corpus |
| Supervisor matrix | An enrolled supervisor receives the progress summary and no conversation, turn, or chat-trace fields. The same token on `/chat` and `/conversations` gets 404. A non-enrolled supervisor gets 404. A write through the summary handle errors at `RO_QUERY` |
| Class code | A valid code enrolls the student. An expired, revoked, exhausted, or unknown code all return 404. Rotating the code invalidates the old link |
| Un-enroll takes effect immediately | The next request after deletion returns 404 with the same token |
| Auth | Expired Supabase token rejected. Unverified email rejected. Role taken from our table, not from token metadata |
| Admin | Ingest requires a verified token, a current allow-list hit, and `role = admin` with `disabled = false`. Each of the three missing on its own is denied |
| Rate limit | Burst over a bucket returns 429 with `Retry-After`. Cost weight is honored. LLM budget exhaustion blocks only LLM routes |
| Provisioning | Kill the process between graph create and `ready`. Next login completes it. No duplicate graph |
| Concurrency | 20 parallel claimers, one winner. Two gap writers, one 409. Parallel `record_read` creates one node |
| Search | Semantic query finds a known paper. Metadata filters match a hand count. Over-fetch returns `limit` results under a restrictive filter |
| Intent | A fixed set of 30 phrasings maps to the right intent and slots at a stated accuracy. Ambiguous ones ask a clarifying question |
| Explainability | Every agent answer has evidence ids that exist in Postgres and a trace whose tool calls replay to the same result |
| Persistence | Restart the API, the conversation, memory, and timeline are identical |
| Scoop | Ingest `2007.15251` through `/admin/papers`. Maya's gap becomes `scooped`, her decision is invalidated, Dev is unchanged. As-of query returns the old belief |
| Graph removal | List which features stop working without FalkorDB (for the README) |

---

## 14. Build order (about 39 hours remain)

Priority: P0 must ship, P1 should ship, P2 is cut first. Each step has an exit test.

| Step | Work | Priority | Exit |
|---|---|---|---|
| B0 | Repo skeleton, `Settings`, `Container`, stores, compose, health. Counts checked against `manifest.json` | P0 | Done. `/healthz` and `/readyz` return 200. Graph, Postgres, and R2 match the manifest (997 papers, 658,126 sentences, 26,346 claim vectors, no private nodes on the corpus) |
| B1 | Migrations, Supabase JWT verification, `AccessPolicy`, `WorkspaceResolver`, provisioning saga, org, class code, `require_admin` | P0 | Done. Expired and unconfirmed tokens are rejected. Admin needs the allow-list, a verified token, and an enabled admin row. Class codes enroll, and expired, revoked, or exhausted codes return 404. A supervisor gets the progress summary only. Workspace graphs stay isolated |
| B2 | `RateLimiter`, `LLM` client with ledger and budgets | P0 | Done. A burst returns 429 with `Retry-After`. Chat costs more than a read. Daily, org, and monthly budgets block chat and leave reads up. The ledger records each model call |
| B3 | `PaperService`, `SearchService` (three channels, fusion, personalization), presign | P0 | Done. Semantic, title and name, and abstract search run alone or together. Filters and sort apply to all three. Tests use a stored vector, so they do not call OpenAI |
| B4 | `MemoryService`, conversations, events, timeline, brief, and `progress()` | P0 | Done. Reads, gaps, memories, and conversations survive a new process. The supervisor summary lists research events and omits chats and raw memory. The brief is built from the graph with no model call |
| B5 | Work queue, worker, sweeper, handoffs, gap lifecycle in Cypher | P0 | Done. Twenty claimers produce one winner, an expired lease can be claimed again, and the first writer loses. Two gap writers produce one 409. Parallel reads of one paper create one node. A handoff with too little evidence stays blocked, with the reason, until the gate passes |
| B6 | `GraphToolkit`, `Agent` base, Scout, GapHunter, Adversary, Chronicler | P0 | Done. A note on a seed paper becomes ranked gaps and an Adversary verdict, with a trace. GapHunter is deterministic: empty cells and unresolved claims, using citations, datasets, metrics, and baselines. No model call |
| B7 | `IntentEngine`, `/chat` SSE | P0 | Done. Ordinary messages are classified by the model. Attack patterns are refused first and are not quoted. Chat is capped at 1000 words |
| B8 | MCP server over the toolkit | P1 (Track 1 centrepiece, so promote if B6 is early) | Done. `/mcp` gives a signed-in student the chat turn plus the same research operations: search, citations, lookup, compare, reading path, evidence, notes, memory, progress, and queued gap search. A supervisor token is refused |
| B9 | Cartographer, Reader note path, Evidence provenance, `MemoryWriter` background | P1 | Done. A note marks the paper read and the tasks known, and the reading path is rebuilt without that paper first. Evidence writes a private finding from the citation walk. The memory writer stores the note. The corpus stays shared |
| B10 | Ingest and scoop through `/admin/papers`, `open_gap_index`, as-of query | P0 (demo beat) | Done. An admin ingest of `2007.15251` fills the cell from the saved facets, scoops the indexed workspace, invalidates its decision, and leaves the other workspace unchanged. An as-of query still returns the earlier belief |
| B11 | Seed script, README (graph model, queries, memory mapping, AI disclosure), deploy or local setup | P0 | Done. The backend directory runs without the data folder. AWS starts the API and worker only. The README names both tracks, the graph, the queries, and the Cursor disclosure |
| B12 | Scoper, claim-to-claim stances, passage embeddings, per-org usage views | P2 | Scoper is done. It plans the smallest experiment for an open gap from a dataset, metric, and baseline already in the corpus, and stores that plan on the student graph. The other three items stay cut |

Dependency order: B0 -> B1 -> B2 -> B3. B4 and B5 can run after B1. B6 needs B3, B4, B5. B7 needs B6. B10 needs B5 and B6. If time slips, cut in this order: B12, Cartographer polish, `communities`/BFS tools, MCP stays unless B6 is late. The progress summary is not on the cut list.

Parallelism that makes sense: B3 (search) and B4/B5 (memory and queue) are independent after B1, so they can be worked at the same time, or by separate teammates if any.

---

## 15. Risks

| Risk | Mitigation |
|---|---|
| Scope is larger than 39 hours | The P0/P1/P2 tiers above. Search, memory, auth, gap lifecycle, and scoop are the floor |
| Judges ask whether FalkorDB is decorative | Gap cells, learning distance, handoff preconditions, scoop invalidation, shortest path, and PageRank are traversals. Show the Cypher in the README and the graph-removal list |
| Track 1 vs Track 2 dilution | One story: the agent acts on a connected field graph (Track 1) and remembers the student in a private graph (Track 2). The demo has one beat for each |
| LLM cost and abuse | One chat model, `gpt-4.1-mini`. Rate limits, budgets, step caps, cached embeddings, and the intent shortcut that skips the model |
| Prompt injection from paper text | Delimited data blocks, tool-only actions, no raw query generation |
| Vector filter after nearest-k | Over-fetch and retry in `SearchService` |
| Cross-user "who has this gap open" needs a cross-graph answer | `open_gap_index` in Postgres, id pairs only, rebuildable |
| FalkorDB moves off the laptop onto a VM | `GraphStore` already reads host, port, and password from settings. Deploy deletes the compose FalkorDB service and sets those three values. If that host refuses extra Redis keys, `RateLimiter` switches to its Postgres counter through the same interface |
| Community detection and BFS yield fields not verified | Verified in B0 on a throwaway graph, then deleted. `algo.labelPropagation()` yields `node, communityId`. `algo.BFS(source, maxDepth, relationshipType)` yields `nodes`. `algo.pageRank(label, rel)` yields `node, score`. `algo.WCC()` yields `node, componentId`. `algo.SPpaths({sourceNode, targetNode})` yields `path` |

---

## 16. Decisions locked (16 Oct 2026)

1. **Supervisor visibility.** A supervisor sees one progress summary per enrolled student: gaps, reading, decisions, notes, research timeline, and graph counts. They do not see chats, conversations, or raw memory. The student is not shown who viewed their progress. There is no access-log endpoint.
2. **Joining a class.** The supervisor gets one class code and a shareable join path. The student submits the code. Many students can use the same code until it expires, is used up, or is revoked. Only the hash is stored.
3. **Auth.** Supabase Auth. This API verifies the Supabase JWT on every protected route and stores profiles, roles, orgs, and enrollments itself.
4. **Models.** `gpt-4.1-mini` for every chat and intent call. `text-embedding-3-small` for embeddings. No stronger model.
5. **FalkorDB hosting.** Developed against local Docker. Connection settings are env-only. Moving to a VM is a config change, and the local compose service is removed at deploy.
6. **Admin.** `ADMIN_EMAILS` is an allow-list of normalized emails. Every admin route also requires a valid verified Supabase token and `users.role = admin` with the account enabled. The allow-list is checked on every request, not only when the role is granted.
7. **Uploads.** Students do not upload papers. Not in scope.

Still settled and not reopened: CS corpus only, embeddings 1,536-dim on the corpus only, six agents plus Scout, gap lifecycle and scoop logic as in `LLD.md`.
