"""Private memory, research events, conversations, and the graph-built brief.

Facts live in the student's graph. Nothing here copies a paper, and nothing here
is readable through the supervisor summary.
"""

import json
import uuid
from datetime import datetime, timezone

from app.core import BadRequest, NotFound
from app.models.queries import Q


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id() -> str:
    return str(uuid.uuid4())


class MemoryService:
    def __init__(self, graph):
        self.graph = graph

    async def read(self, handle, paper_id: str, depth: str, note: str, key: str = "") -> dict:
        if not paper_id:
            raise BadRequest("paper_id is required")
        await self._ready(handle)

        async def write():
            at = now_iso()
            read_id = f"read-{paper_id}"
            event_id = f"read-event-{paper_id}"
            await handle.query(
                Q.RECORD_READ,
                {
                    "id": read_id,
                    "event_id": event_id,
                    "at": at,
                    "paper_id": paper_id,
                    "depth": depth,
                    "note": note[:280],
                },
            )
            try:
                for _slug, _name, _count in await self.graph.tasks_for([paper_id]):
                    await handle.query(Q.MARK_KNOWS, {"student": "self", "kind": "task", "ref_id": _slug})
            except Exception:
                pass
            return {"id": read_id, "at": at, "paper_id": paper_id, "depth": depth}

        return await self._once(handle, key, write)

    async def note(self, handle, text: str, key: str = "") -> dict:
        await self._ready(handle)

        async def write():
            at = now_iso()
            note_id, event_id = new_id(), new_id()
            await handle.query(
                Q.RECORD_NOTE,
                {"id": note_id, "event_id": event_id, "at": at, "note": text[:280]},
            )
            return {"id": note_id, "at": at}

        return await self._once(handle, key, write)

    async def decide(self, handle, kind: str, reason: str, gap_id: str = "", key: str = "") -> dict:
        await self._ready(handle)

        async def write():
            at = now_iso()
            decision_id, event_id = new_id(), new_id()
            params = {
                "id": decision_id,
                "event_id": event_id,
                "at": at,
                "kind": kind,
                "reason": reason[:280],
                "gap_id": gap_id,
            }
            query = Q.RECORD_DECISION_ABOUT if gap_id else Q.RECORD_DECISION
            rows = await handle.query(query, params)
            if gap_id and not rows:
                raise NotFound("not found")
            return {"id": decision_id, "at": at, "kind": kind}

        return await self._once(handle, key, write)

    async def open_gap(self, handle, text: str, task_id: str, key: str = "") -> dict:
        await self._ready(handle)

        async def write():
            at = now_iso()
            gap_id, event_id = new_id(), new_id()
            await handle.query(
                Q.OPEN_GAP,
                {"id": gap_id, "event_id": event_id, "at": at, "text": text[:200], "task_id": task_id},
            )
            return {"id": gap_id, "at": at, "status": "candidate"}

        return await self._once(handle, key, write)

    async def remember(self, handle, kind: str, text: str, entity: str) -> dict:
        """Same fact is kept. A different fact for the same entity closes the old one."""
        await self._ready(handle)
        at = now_iso()
        found = await handle.query(Q.FIND_MEMORY, {"kind": kind, "entity": entity, "text": text})
        if found:
            return {"id": _text(found[0][0]), "valid_from": _text(found[0][1]), "duplicate": True}
        await handle.query(Q.CLOSE_MEMORIES, {"kind": kind, "entity": entity, "text": text, "at": at})
        memory_id = new_id()
        created = await handle.query(
            Q.CREATE_MEMORY,
            {"id": memory_id, "kind": kind, "entity": entity, "text": text[:500], "at": at},
        )
        return {"id": _text(created[0][0]), "valid_from": _text(created[0][1]), "duplicate": False}

    async def forget(self, handle, memory_id: str) -> dict:
        await self._ready(handle)
        rows = await handle.query(Q.FORGET_MEMORY, {"id": memory_id, "at": now_iso()})
        if not rows:
            raise NotFound("not found")
        return {"id": memory_id, "forgotten": True}

    async def recall(self, handle, query: str, limit: int = 10) -> dict:
        await self._ready(handle)
        limit = min(max(limit, 1), 20)
        rows = await handle.query(Q.RECALL_MEMORY, {"q": query.strip(), "limit": limit})
        gaps = sorted(await handle.query(Q.OPEN_GAPS), key=lambda row: (-(row[2] or 0), _text(row[0])))
        return {
            "memories": [_memory(row) for row in rows],
            "open_gaps": [_gap(row) for row in gaps],
        }

    async def as_of(self, handle, at: str) -> dict:
        await self._ready(handle)
        rows = await handle.query(Q.MEMORY_AS_OF, {"at": at})
        return {"at": at, "memories": [_memory(row) for row in rows]}

    async def gaps(self, handle) -> dict:
        rows = await handle.query(Q.LIST_GAPS)
        return {
            "items": [
                {
                    "id": _text(row[0]),
                    "status": _text(row[1]),
                    "score": row[2],
                    "task_id": _text(row[3]),
                    "text": _text(row[4]),
                    "at": _text(row[5]),
                    "version": int(row[6] or 1),
                }
                for row in rows
            ]
        }

    async def conversations(self, handle) -> dict:
        rows = await handle.query(Q.LIST_CONVERSATIONS)
        return {
            "items": [
                {"id": _text(row[0]), "at": _text(row[1]), "title": _text(row[2]), "turns": int(row[3] or 0)}
                for row in rows
            ]
        }

    async def find_conversation(self, handle, conversation_id: str) -> dict | None:
        if not conversation_id:
            return None
        rows = await handle.query(Q.GET_CONVERSATION, {"id": conversation_id})
        if not rows:
            return None
        return {"id": _text(rows[0][0]), "title": _text(rows[0][1]), "turns": int(rows[0][2] or 0)}

    async def recent_turns(self, handle, conversation_id: str, limit: int = 8) -> list[dict]:
        """Oldest first, so the list reads as the dialogue."""
        rows = await handle.query(Q.RECENT_TURNS, {"id": conversation_id, "limit": min(max(limit, 1), 30)})
        turns = [
            {"role": _text(row[0]), "text": _text(row[1]), "evidence": _evidence(row[2]), "seq": int(row[3] or 0)}
            for row in rows
        ]
        turns.reverse()
        return turns

    async def add_chat_turn(self, handle, conversation_id: str, role: str, text: str, evidence: list, intent: str = "") -> None:
        await handle.query(
            Q.ADD_CHAT_TURN,
            {
                "id": conversation_id,
                "turn_id": new_id(),
                "at": now_iso(),
                "role": role,
                "text": text[:6000],
                "evidence": _fit(evidence or []),
                "intent": intent,
            },
        )

    async def title_conversation(self, handle, conversation_id: str, title: str) -> None:
        await handle.query(Q.TITLE_CONVERSATION, {"id": conversation_id, "title": title[:80]})

    async def delete_conversation(self, handle, conversation_id: str) -> dict:
        if await self.find_conversation(handle, conversation_id) is None:
            raise NotFound("not found")
        await handle.query(Q.DELETE_CONVERSATION, {"id": conversation_id})
        return {"id": conversation_id, "deleted": True}

    async def search_turns(self, handle, words: list[str], exclude: str = "", limit: int = 6) -> list[dict]:
        cleaned = [word.lower() for word in words if len(word) > 2][:4]
        if not cleaned:
            return []
        rows = await handle.query(Q.SEARCH_TURNS, {"words": cleaned, "exclude": exclude, "limit": limit})
        return [
            {"conversation": _text(row[0]), "title": _text(row[1]), "role": _text(row[2]), "text": _text(row[3]), "at": _text(row[4])}
            for row in rows
        ]

    async def recent_conversations(self, handle, exclude: str = "", limit: int = 3) -> list[dict]:
        rows = await handle.query(Q.RECENT_CONVERSATIONS, {"exclude": exclude, "limit": limit})
        return [{"id": _text(row[0]), "title": _text(row[1]), "at": _text(row[2])} for row in rows]

    async def open_conversation(self, handle, title: str) -> dict:
        await self._ready(handle)
        created = await handle.query(Q.CREATE_CONVERSATION, {"id": new_id(), "at": now_iso(), "title": title[:80]})
        return {"id": _text(created[0][0]), "at": _text(created[0][1]), "title": _text(created[0][2])}

    async def conversation(self, handle, conversation_id: str) -> dict:
        rows = await handle.query(Q.CONVERSATION_TURNS, {"id": conversation_id})
        if not rows:
            raise NotFound("not found")
        turns = []
        for row in rows:
            if row[2] is None:
                continue
            turns.append(
                {
                    "id": _text(row[2]),
                    "at": _text(row[3]),
                    "role": _text(row[4]),
                    "text": _text(row[5]),
                    "evidence": _evidence(row[6]),
                    "intent": _text(row[7]),
                }
            )
        return {"id": _text(rows[0][0]), "title": _text(rows[0][1]), "turns": turns}

    async def add_turn(self, handle, conversation_id: str, text: str) -> dict:
        await self._ready(handle)
        rows = await handle.query(
            Q.ADD_TURN,
            {"id": conversation_id, "turn_id": new_id(), "at": now_iso(), "text": text[:2000]},
        )
        if not rows:
            raise NotFound("not found")
        return {"id": _text(rows[0][0]), "at": _text(rows[0][1])}

    async def brief(self, handle, progress: dict) -> dict:
        """Phrases the brief from graph rows only. No model call."""
        lines = []
        recent = progress["reading"]["recent"]
        if recent:
            top = recent[0]
            title = top.get("title") or top.get("paper_id") or "a paper"
            lines.append(f"Last reading: {title} ({top['depth']}).")
            if top.get("note"):
                lines.append(f"Note: {top['note']}")
        open_gaps = progress["open_gaps"]
        if open_gaps:
            names = ", ".join(gap.get("title") or gap["id"] for gap in open_gaps[:3])
            lines.append(f"Open gaps ({len(open_gaps)}): {names}.")
        else:
            lines.append("No open gaps.")
        plans = (progress.get("reading") or {}).get("plans") or []
        if plans:
            lines.append(f"Experiment plan: {plans[0]['summary']}")
        if progress["decisions"]:
            last = progress["decisions"][0]
            lines.append(f"Latest decision: {last['kind']}. {last['reason']}".strip())
        if not lines:
            lines.append("Nothing recorded yet.")
        return {"text": " ".join(lines), "source": "graph"}

    async def _ready(self, handle) -> None:
        await self.graph.ensure_workspace(handle.name)

    async def _once(self, handle, key: str, write):
        if not key:
            return await write()
        found = await handle.query(Q.IDEMPOTENT_GET, {"key": key})
        if found:
            return json.loads(_text(found[0][0]))
        body = await write()
        await handle.query(Q.IDEMPOTENT_PUT, {"key": key, "body": json.dumps(body), "at": now_iso()})
        return body


def _text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode()
    return str(value)


def _fit(evidence: list, limit: int = 12000) -> str:
    items = list(evidence)
    body = json.dumps(items, ensure_ascii=False)
    while len(body) > limit and items:
        items.pop()
        body = json.dumps(items, ensure_ascii=False)
    return body


def _evidence(value) -> list:
    try:
        found = json.loads(_text(value) or "[]")
    except json.JSONDecodeError:
        return []
    return found if isinstance(found, list) else []


def _memory(row) -> dict:
    return {
        "id": _text(row[0]),
        "kind": _text(row[1]),
        "text": _text(row[2]),
        "entity": _text(row[3]),
        "valid_from": _text(row[4]),
    }


def _gap(row) -> dict:
    return {
        "id": _text(row[0]),
        "status": _text(row[1]),
        "score": row[2],
        "task_id": _text(row[3]),
        "title": _text(row[4]),
        "evidence": int(row[5] or 0),
    }
