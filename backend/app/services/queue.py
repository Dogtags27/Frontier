"""Work items live in the graph they change. Redis only holds a wake-up hint."""

import json
import time
import uuid

import structlog

from app.core import BadRequest, NotFound
from app.models.queries import Q, SQL

log = structlog.get_logger()

WORKSPACE_TYPES = (
    "map_field",
    "find_gaps",
    "challenge_gap",
    "reassess_gap",
    "write_brief",
    "summarize_turn",
    "ingest_note",
    "check_claim",
    "resolve_handoff",
)
CORPUS_TYPES = ("ingest_paper", "extract_paper", "link_paper", "check_claim")


def now_ms() -> int:
    return int(time.time() * 1000)


def _text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode()
    return str(value)


def _loads(value) -> dict:
    raw = _text(value)
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


class WorkQueue:
    """Enqueue, claim, finish. Claim and finish are each one Cypher statement."""

    def __init__(self, graph, pg, settings):
        self.graph = graph
        self.pg = pg
        self.settings = settings

    async def enqueue(self, graph_name: str, job_type: str, payload: dict | None = None) -> dict:
        self._allowed(graph_name, job_type)
        body = payload or {}
        encoded = json.dumps(body)
        if len(encoded) > 4000:
            raise BadRequest("payload is too large")
        job_id = str(uuid.uuid4())
        await self.graph.run(
            graph_name,
            Q.CREATE_WORK,
            {"id": job_id, "type": job_type, "payload": encoded, "now": now_ms()},
        )
        await self._hint(graph_name)
        return {"id": job_id, "type": job_type, "status": "open"}

    async def claim(self, graph_name: str, worker_id: str, types: list[str], lease_sec: int | None = None) -> dict | None:
        if not types:
            return None
        now = now_ms()
        lease = self.settings.work_lease_sec if lease_sec is None else lease_sec
        rows = await self.graph.run(
            graph_name,
            Q.CLAIM_WORK,
            {
                "types": types,
                "now": now,
                "until": now + int(lease * 1000),
                "worker": worker_id,
            },
        )
        if not rows:
            return None
        row = rows[0]
        return {
            "id": _text(row[0]),
            "type": _text(row[1]),
            "payload": _loads(row[2]),
            "attempts": int(row[3] or 0),
            "graph": graph_name,
        }

    async def complete(self, graph_name: str, worker_id: str, job_id: str, result: dict) -> bool:
        rows = await self.graph.run(
            graph_name,
            Q.COMPLETE_WORK,
            {"id": job_id, "worker": worker_id, "now": now_ms(), "result": json.dumps(result)},
        )
        return bool(rows)

    async def fail(self, graph_name: str, worker_id: str, job_id: str, error: str) -> str:
        rows = await self.graph.run(
            graph_name,
            Q.FAIL_WORK,
            {
                "id": job_id,
                "worker": worker_id,
                "error": error[:300],
                "max": self.settings.work_attempts,
            },
        )
        if not rows:
            return "lost"
        status = _text(rows[0][1])
        if status == "open":
            await self._hint(graph_name)
        return status

    async def get(self, graph_name: str, job_id: str) -> dict:
        rows = await self.graph.run(graph_name, Q.WORK_ONE, {"id": job_id})
        if not rows:
            raise NotFound("not found")
        return _job(rows[0], include_payload=True)

    async def list_jobs(self, graph_name: str, limit: int = 20) -> dict:
        rows = await self.graph.run(graph_name, Q.LIST_WORK, {"limit": min(max(limit, 1), 50)})
        return {"items": [_job(row, include_payload=True) for row in rows]}

    async def snapshot(self, limit_graphs: int = 40) -> dict:
        """Admin view: status and type only. Payloads stay on the private graph."""
        names = await self.ready_graphs()
        return await self._snapshot(names[:limit_graphs])

    async def store_brief(self, graph_name: str, job_id: str, summary: str) -> None:
        await self.graph.run(
            graph_name,
            Q.STORE_BRIEF,
            {"id": f"brief-{job_id}", "summary": summary[:2000], "at": now_ms()},
        )

    async def claimable(self, graph_name: str, types: list[str]) -> int:
        rows = await self.graph.run(
            graph_name,
            Q.CLAIMABLE_COUNT,
            {"types": types, "now": now_ms()},
        )
        return int(rows[0][0]) if rows else 0

    async def ready_graphs(self) -> list[str]:
        rows = await self.pg.fetch(SQL.READY_GRAPHS)
        names = [_text(row[0]) for row in rows if row[0]]
        if self.settings.corpus_graph not in names:
            names.append(self.settings.corpus_graph)
        return names

    def _allowed(self, graph_name: str, job_type: str) -> None:
        corpus = graph_name == self.settings.corpus_graph
        if corpus and job_type not in CORPUS_TYPES:
            raise BadRequest("that job does not run on the corpus")
        if not corpus and job_type not in WORKSPACE_TYPES:
            raise BadRequest("unknown job type")
        if not corpus and not str(graph_name).startswith("frontier_ws_"):
            raise BadRequest("unknown graph")

    async def _hint(self, graph_name: str) -> None:
        try:
            await self.graph.push_hint(self.settings.work_hint_key, graph_name)
        except Exception as exc:
            log.info("work hint not pushed", error=type(exc).__name__)

    async def _snapshot(self, names: list[str]) -> dict:
        items = []
        for name in names:
            try:
                rows = await self.graph.run(name, Q.OPEN_WORK, {"limit": 10})
            except Exception as exc:
                log.info("queue snapshot skipped", graph=name, error=type(exc).__name__)
                continue
            for row in rows:
                items.append(
                    {
                        "id": _text(row[0]),
                        "type": _text(row[1]),
                        "status": _text(row[2]),
                        "graph": name,
                        "created": int(row[3] or 0),
                        "error": _text(row[4]),
                    }
                )
        return {"items": items}


def _job(row, include_payload: bool) -> dict:
    body = {
        "id": _text(row[0]),
        "type": _text(row[1]),
        "status": _text(row[2]),
        "result": _loads(row[4]),
        "error": _text(row[5]),
        "created": int(row[6] or 0),
        "finished": int(row[7] or 0),
        "attempts": int(row[8] or 0),
    }
    if include_payload:
        body["payload"] = _loads(row[3])
    return body
