"""Gap lifecycle and handoff gates. Both are single Cypher statements."""

import uuid
from datetime import datetime, timezone

from app.core import BadRequest, Conflict, NotFound
from app.models.queries import Q, SQL

ALLOWED = {
    "candidate": {"challenged", "scooped"},
    "challenged": {"alive", "killed", "scooped"},
    "alive": {"adopted", "scooped"},
}
PRECONDITIONS = {
    "adversary": "gap_ready_for_adversary",
    "chronicler": "gap_ready_for_chronicler",
}
ACCEPT = {
    "gap_ready_for_adversary": Q.ACCEPT_ADVERSARY,
    "gap_ready_for_chronicler": Q.ACCEPT_CHRONICLER,
}
REASONS = {
    "gap_ready_for_adversary": "gap must be a candidate with at least two evidence refs",
    "gap_ready_for_chronicler": "gap must already have a verdict",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode()
    return str(value)


class GapService:
    def __init__(self, graph, pg=None):
        self.graph = graph
        self.pg = pg

    async def get(self, handle, gap_id: str) -> dict:
        rows = await handle.query(Q.GAP_ONE, {"id": gap_id})
        if not rows:
            raise NotFound("not found")
        gap = _gap(rows[0])
        refs = await handle.query(Q.GAP_REFS, {"id": gap_id})
        gap["refs"] = [{"kind": _text(row[0]), "ref_id": _text(row[1])} for row in refs]
        attempts = await handle.query(Q.GAP_ATTEMPTS, {"id": gap_id})
        gap["checks"] = [
            {"result": _text(row[0]), "reason": _text(row[1]), "name": _text(row[2]), "at": _text(row[3])}
            for row in attempts
        ]
        return gap

    async def transition(self, handle, gap_id: str, to_status: str, version: int) -> dict:
        current = await self.get(handle, gap_id)
        if int(version) != int(current["version"]):
            raise Conflict("gap changed", _detail(current))
        allowed = ALLOWED.get(current["status"], set())
        if to_status not in allowed:
            raise BadRequest(f"cannot move from {current['status']} to {to_status}")
        rows = await handle.query(
            Q.TRANSITION_GAP,
            {
                "id": gap_id,
                "from": current["status"],
                "to": to_status,
                "version": int(version),
                "at": now_iso(),
                "event_id": str(uuid.uuid4()),
            },
        )
        if not rows:
            latest = await self.get(handle, gap_id)
            raise Conflict("gap changed", _detail(latest))
        await self._index_gap(handle.name, gap_id, to_status)
        return {"id": _text(rows[0][0]), "status": _text(rows[0][1]), "version": int(rows[0][2])}

    async def note_cell(self, graph_name: str, task_id: str, method_id: str, family: str, open_gap: bool) -> None:
        """Keep the cross-graph cell index in step with one workspace. Ids only."""
        if self.pg is None or getattr(self.pg, "error", None):
            return
        if not str(graph_name).startswith("frontier_ws_") or not task_id or not family:
            return
        user_id = str(uuid.UUID(hex=str(graph_name).removeprefix("frontier_ws_")))
        method_id = method_id or family
        if open_gap:
            await self.pg.execute(SQL.UPSERT_GAP_INDEX, (user_id, task_id, method_id, family))
        else:
            await self.pg.execute(SQL.DELETE_GAP_INDEX, (user_id, task_id, method_id))

    async def _index_gap(self, graph_name: str, gap_id: str, status: str) -> None:
        handle_rows = await self.graph.run(graph_name, Q.GAP_CELL, {"id": gap_id})
        if not handle_rows:
            return
        task, method, family = handle_rows[0]
        open_gap = status in {"candidate", "challenged", "alive"}
        await self.note_cell(graph_name, _text(task), _text(method), _text(family), open_gap)

    async def add_evidence(self, handle, gap_id: str, ref_id: str, kind: str) -> dict:
        if not ref_id:
            raise BadRequest("ref_id is required")
        rows = await handle.query(
            Q.ADD_EVIDENCE,
            {
                "id": gap_id,
                "kind": kind,
                "ref_id": ref_id,
                "at": now_iso(),
                "event_id": f"evidence-{gap_id}-{kind}-{ref_id}",
            },
        )
        if not rows:
            raise NotFound("not found")
        reopened = []
        if int(rows[0][1] or 0) >= 2:
            found = await handle.query(
                Q.REOPEN_HANDOFFS,
                {"id": gap_id, "precondition": "gap_ready_for_adversary"},
            )
            reopened = [_text(row[0]) for row in found]
        return {"id": gap_id, "evidence": int(rows[0][1] or 0), "reopened": reopened}

    async def open_handoff(self, handle, gap_id: str, to_agent: str, from_agent: str) -> dict:
        precondition = PRECONDITIONS.get(to_agent)
        if precondition is None:
            raise BadRequest("unknown handoff target")
        rows = await handle.query(
            Q.CREATE_HANDOFF,
            {
                "id": str(uuid.uuid4()),
                "gap_id": gap_id,
                "from_agent": from_agent or "gaphunter",
                "to_agent": to_agent,
                "precondition": precondition,
                "at": now_iso(),
            },
        )
        if not rows:
            raise NotFound("not found")
        return _handoff(rows[0])

    async def resolve(self, handle, handoff_id: str) -> dict:
        current = await self._one(handle, handoff_id)
        if current["status"] != "pending":
            return current
        query = ACCEPT.get(current["precondition"])
        if query is None:
            raise BadRequest("unknown precondition")
        accepted = await handle.query(query, {"id": handoff_id})
        if accepted:
            return _handoff(accepted[0])
        reason = REASONS.get(current["precondition"], "precondition was not met")
        blocked = await handle.query(Q.BLOCK_HANDOFF, {"id": handoff_id, "reason": reason})
        if blocked:
            return _handoff(blocked[0])
        return await self._one(handle, handoff_id)

    async def list_handoffs(self, handle) -> dict:
        rows = await handle.query(Q.LIST_HANDOFFS)
        return {"items": [_handoff(row) for row in rows]}

    async def _one(self, handle, handoff_id: str) -> dict:
        rows = await handle.query(Q.HANDOFF_ONE, {"id": handoff_id})
        if not rows:
            raise NotFound("not found")
        return _handoff(rows[0])


def _detail(gap: dict) -> str:
    return f"{gap['status']}:{gap['version']}"


def _gap(row) -> dict:
    return {
        "id": _text(row[0]),
        "status": _text(row[1]),
        "version": int(row[2] or 1),
        "score": row[3],
        "task_id": _text(row[4]),
        "text": _text(row[5]),
        "at": _text(row[6]),
        "evidence": int(row[7] or 0),
    }


def _handoff(row) -> dict:
    return {
        "id": _text(row[0]),
        "status": _text(row[1]),
        "reason": _text(row[2]),
        "precondition": _text(row[3]),
        "gap_id": _text(row[4]),
        "from_agent": _text(row[5]),
        "to_agent": _text(row[6]),
    }
