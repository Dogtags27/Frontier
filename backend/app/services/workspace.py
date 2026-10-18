"""Workspace graphs. The client never supplies a graph name."""

import uuid

from app.core import NotFound
from app.models.queries import Q, RESEARCH_EVENT_KINDS, SQL
from app.utilities.security import Principal


def graph_name_for(user_id: str) -> str:
    """One private graph per user id. The id is a uuid, so the name stays a single token."""
    token = uuid.UUID(user_id).hex
    return f"frontier_ws_{token}"


class GraphHandle:
    """A graph opened for one request. Summary mode can only run read-only queries."""

    def __init__(self, store, name: str, mode: str):
        self.store = store
        self.name = name
        self.mode = mode

    async def query(self, cypher: str, params: dict | None = None):
        read_only = self.mode != "write"
        return await self.store.run(self.name, cypher, params, ro=read_only)


class WorkspaceResolver:
    """The only place that turns a user id into a graph handle."""

    def __init__(self, graph, pg):
        self.graph = graph
        self.pg = pg

    async def ensure(self, user_id: str, display_name: str) -> str:
        name = graph_name_for(user_id)
        await self.graph.run(name, Q.ENSURE_STUDENT, {"id": user_id, "name": display_name or "student"})
        await self.pg.execute(SQL.SET_GRAPH_READY, (name, user_id))
        return name

    async def open(self, principal: Principal, student_id: str, purpose: str) -> GraphHandle:
        target = principal.user_id if student_id == "me" else student_id
        if purpose == "self":
            if target != principal.user_id:
                raise NotFound("not found")
            return GraphHandle(self.graph, principal.graph_name, "write")
        if target == principal.user_id:
            return GraphHandle(self.graph, principal.graph_name, "write")
        if principal.signup_role != "supervisor" and principal.role != "supervisor":
            raise NotFound("not found")
        rows = await self.pg.fetch(SQL.ACTIVE_ENROLLMENT, (principal.user_id, target))
        if not rows:
            raise NotFound("not found")
        student = await self.pg.fetch(SQL.USER_BY_ID, (target,))
        if not student or not student[0][6]:
            raise NotFound("not found")
        return GraphHandle(self.graph, student[0][6], "summary")

    async def progress(self, handle: GraphHandle) -> dict:
        """Fixed research queries. Conversations and chat traces are not in this set."""
        gaps = await handle.query(Q.GAP_COUNTS)
        by_status = {str(row[0]): int(row[1]) for row in gaps}
        open_gaps = sorted(await handle.query(Q.OPEN_GAPS), key=lambda row: (-(row[2] or 0), _text(row[0])))
        reads = await handle.query(Q.RECENT_READS)
        decisions = await handle.query(Q.RECENT_DECISIONS)
        timeline = await handle.query(Q.TIMELINE, {"kinds": list(RESEARCH_EVENT_KINDS)})
        plans = await handle.query(Q.LIST_PLANS)
        totals = [
            int((await handle.query(Q.COUNT_GAPS))[0][0]),
            int((await handle.query(Q.COUNT_READS))[0][0]),
            int((await handle.query(Q.COUNT_DECISIONS))[0][0]),
            int((await handle.query(Q.COUNT_KNOWS))[0][0]),
        ]
        recent = [_read(row) for row in reads]
        path_rows = await handle.query(Q.LIST_PATH)
        path_ids = [_text(row[0]) for row in path_rows]
        paper_ids = [item["paper_id"] for item in recent if item["paper_id"]]
        paper_ids.extend(_text(row[2]) for row in timeline)
        paper_ids.extend(path_ids)
        titles = await self.graph.titles_for(paper_ids)
        for item in recent:
            item["title"] = titles.get(item["paper_id"], "")
        path = [{"paper_id": paper_id, "title": titles.get(paper_id, "")} for paper_id in path_ids]
        return {
            "gaps": {status: by_status.get(status, 0) for status in ("candidate", "challenged", "alive", "killed", "adopted", "scooped")},
            "open_gaps": [
                {
                    "id": _text(row[0]),
                    "status": _text(row[1]),
                    "score": row[2],
                    "task_id": _text(row[3]),
                    "title": _text(row[4]),
                    "evidence": int(row[5] or 0),
                }
                for row in open_gaps
            ],
            "reading": {
                "count": totals[1],
                "recent": recent,
                "path": path,
                "plans": [{"gap_id": _text(row[0]), "summary": _text(row[1])} for row in plans],
            },
            "notes": [item for item in recent if item["note"]][:10],
            "decisions": [
                {
                    "id": _text(row[0]),
                    "at": _text(row[1]),
                    "kind": _text(row[2]),
                    "reason": _text(row[3]),
                    "invalidated": bool(row[4]),
                }
                for row in decisions
            ],
            "timeline": [
                {
                    "at": _text(row[0]),
                    "kind": _text(row[1]),
                    "ref": _text(row[2]),
                    "title": titles.get(_text(row[2]), ""),
                }
                for row in timeline
            ],
            "graph": {
                "gaps": totals[0],
                "reads": totals[1],
                "decisions": totals[2],
                "concepts": totals[3],
                "plans": len(plans),
            },
        }

    async def profile(self, handle: GraphHandle) -> dict:
        """Display fields for the student profile. Research text stays on the graph."""
        body = await self.progress(handle)
        known = [_text(row[0]) for row in await handle.query(Q.KNOWN_TASKS) if _text(row[0])]
        read_ids = [_text(row[0]) for row in await handle.query(Q.READ_IDS) if row[0]]
        days = await handle.query(Q.READ_DAYS)
        interest = await handle.query(Q.INTEREST_LINE)
        from_reads = await self.graph.tasks_for(read_ids)
        names = await self.graph.task_names(known)
        topics: list[str] = []
        for _slug, name, _count in from_reads:
            if name and name not in topics:
                topics.append(name)
        for slug in known:
            label = names.get(slug) or slug
            if label not in topics:
                topics.append(label)
        return {
            "reads_by_day": _day_counts(days),
            "tasks": topics[:30],
            "gaps": body["gaps"],
            "reading": body["reading"],
            "graph": body["graph"],
            "interest": _text(interest[0][0]) if interest else "",
        }

    async def resume_pending(self, accounts) -> None:
        """Finish provisioning for any signup that stopped before the graph was ready."""
        for row in await self.pg.fetch(SQL.PENDING_USERS):
            user = accounts.user_from(row)
            await self.ensure(user["id"], user["display_name"])
            if user["signup_role"] == "supervisor" and not user["org_id"]:
                await accounts.ensure_org(user["id"], user["display_name"])


def _text(value):
    if value is None:
        return ""
    return value.decode() if isinstance(value, bytes) else str(value)


def _read(row) -> dict:
    note = _text(row[3])[:280]
    paper_id = _text(row[4]) if len(row) > 4 else ""
    return {"id": _text(row[0]), "at": _text(row[1]), "depth": _text(row[2]), "note": note, "paper_id": paper_id}


def _day_counts(rows) -> list[dict]:
    counts: dict[str, int] = {}
    for row in rows:
        stamp = _text(row[0])
        if len(stamp) < 10:
            continue
        day = stamp[:10]
        counts[day] = counts.get(day, 0) + 1
    return [{"day": day, "count": counts[day]} for day in sorted(counts)]
