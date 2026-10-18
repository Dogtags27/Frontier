# Frontier

A research assistant for computer science papers. Agents query one shared FalkorDB graph and keep each student's memory in a private graph.

**Track 1: Agents That Act on Connected Data.** **Track 2: Agent Memory and Coordination.**

The participant built the corpus, decided the graph model, and wrote the product requirements. Cursor was the coding assistant for the backend. The participant reviewed the code and can explain the model, the queries, and the architecture.

## Run

The server is the `backend/` directory. `data/` is not deployed with it. The corpus already lives in FalkorDB, Postgres, and R2.

```
cd backend
python -m venv .venv
.venv\Scripts\pip install -e ".[dev]"
copy .env.example .env
.venv\Scripts\uvicorn app.main:app --host 0.0.0.0 --port 8000
.venv\Scripts\python -m app.utilities.worker
```

`GET /healthz` is liveness. `GET /readyz` checks the three stores. The first boot applies `migrations/`.

## AWS

Copy `backend/` to the instance. Fill `.env` from `.env.example`. Point `FALKORDB_HOST`, `DATABASE_URL`, and `R2_*` at the existing stores. Set `SUPABASE_URL`, `SUPABASE_JWT_ISSUER`, `OPENAI_API_KEY`, and `ADMIN_EMAILS`. Set `MCP_ALLOWED_HOSTS` to the public hostname. Open port 8000.

```
docker compose -f docker-compose.aws.yml up -d --build
```

That starts the API and the worker. It does not start FalkorDB or Postgres.

## Use the tools from a coding agent (MCP)

The server speaks MCP over HTTP at `https://frontier-backend-api.duckdns.org/mcp/` (keep the trailing slash). Sign-in uses OAuth, so there is no token to copy. Add the server to the agent and approve the browser prompt with a student account (Google or email).

```json
{ "mcpServers": { "frontier": { "url": "https://frontier-backend-api.duckdns.org/mcp/" } } }
```

The agent gets a `401` that points to `/.well-known/oauth-protected-resource`, finds Supabase Auth as the authorization server, and sends you to `/oauth/consent` on the web app. After you allow it, Supabase issues the token and the agent refreshes it on its own. The tools act on that student's private graph only. Supervisor accounts are refused.

## Graph

`frontier_corpus` is shared: papers, tasks, methods, datasets, metrics, and claims. The edges the product uses are `CITES`, `ADDRESSES`, `USES_METHOD`, `COMPARES_TO`, `EVALUATED_ON`, `REPORTS_METRIC`, and `HAS_CLAIM`. Embeddings stay here.

`frontier_ws_<user>` is private: gaps, reads, decisions, memories, a reading path, and an experiment plan. Those nodes store corpus ids, not copies. A supervisor sees progress, not chats.

A gap moves `candidate → challenged → alive | killed → adopted | scooped`. A scoop adds `SCOOPED_BY` and closes the old belief. `as_of` uses `valid_from` and `valid_to`.

Episodic memory is reads, decisions, and events. Semantic memory is a fact with a validity window. Procedural memory is the reading path and the experiment plan.

Cypher and SQL live only in `backend/app/models/queries.py`. The product depends on the gap-cell queries, `algo.SPpaths` for citation paths, the single-statement work claim, and the scoop update.

Without FalkorDB, search, gaps, citation paths, memory, and scoop stop. Postgres holds accounts, usage, and the open-gap index.
