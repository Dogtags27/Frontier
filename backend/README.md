# Frontier

A research assistant for computer science research papers. Agents query one shared FalkorDB graph and keep each student's memory in a private graph.

**Track 1: Agents That Act on Connected Data.** **Track 2: Agent Memory and Coordination.**

I have built the data corpus of 900+ research papers, decided the graph model and data storage strategies. The ideation and feature development was also done organically. Cursor was the coding assistant used for implementation at multiple stages. I have reviewed the code and can explain the model, queries, and the underlying architectural choices.

## Run

Deploy the `backend/` directory only. `data/` is not part of the server. The corpus already lives in FalkorDB, Postgres, and R2.

From `backend/`:

```
python -m venv .venv
.venv\Scripts\pip install -e ".[dev]"
copy .env.example .env
.venv\Scripts\uvicorn app.main:app --host 0.0.0.0 --port 8000
.venv\Scripts\python -m app.utilities.worker
```

`GET /healthz` is liveness. `GET /readyz` checks the three stores. The first boot applies `migrations/`.

## Production

The running API is [frontier-backend-api.duckdns.org](https://frontier-backend-api.duckdns.org). The app is [frontend-frontier-delta.vercel.app](https://frontend-frontier-delta.vercel.app). A push to `main` that changes `backend/` rebuilds the API and the worker. FalkorDB stays up. The layout is in the repository [README](../README.md) and [GRAPH.md](../GRAPH.md).

## Graph

`frontier_corpus` is shared: papers, tasks, methods, datasets, metrics, and claims. The edges the product uses are `CITES`, `ADDRESSES`, `USES_METHOD`, `COMPARES_TO`, `EVALUATED_ON`, `REPORTS_METRIC`, and `HAS_CLAIM`. Embeddings stay here.

`frontier_ws_<user>` is private and user-specific: gaps, reads, decisions, memories, a reading path, and an experiment plan. Those nodes store corpus ids, not copies. A supervisor sees progress, not chats.

A gap moves `candidate → challenged → alive | killed → adopted | scooped`. A scoop adds `SCOOPED_BY` and closes the old belief. `as_of` uses `valid_from` and `valid_to`.

Episodic memory is reads, decisions, and events. Semantic memory is a fact with a validity window. Procedural memory is the reading path and the experiment plan.

Cypher and SQL live only in `app/models/queries.py`. The product depends on the gap-cell queries, `algo.SPpaths` for citation paths, the single-statement work claim, and the scoop update.

Without FalkorDB, search, gaps, citation paths, memory, and scoop stop. Postgres holds accounts, usage, and the open-gap index.
