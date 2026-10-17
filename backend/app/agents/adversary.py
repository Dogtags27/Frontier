"""Try to kill a gap with a corpus check. A near miss is recorded and does not kill it."""

import uuid
from datetime import datetime, timezone

from app.agents.base import CAVEAT, Agent, answer, as_text
from app.core import NotFound
from app.models.queries import Q


class Adversary(Agent):
    name = "adversary"
    work_types = ("challenge_gap",)

    async def handle(self, ctx, item: dict) -> dict:
        payload = item.get("payload") or {}
        gap_id = str(payload.get("gap_id") or "")
        if not gap_id:
            raise NotFound("not found")
        gate = await self._gate(ctx, str(payload.get("handoff_id") or ""))
        if gate and gate["status"] == "blocked":
            ctx.trace.step("handoff", {"id": gate["id"]}, gate["reason"])
            return answer(gate["reason"], [], ctx.trace, [CAVEAT])
        gap = await self._load(ctx, gap_id)
        if gap["status"] in {"alive", "killed", "adopted", "scooped"}:
            return answer(f"Gap is already {gap['status']}.", [], ctx.trace, [CAVEAT])
        if gap["status"] == "candidate":
            moved = await ctx.gaps.transition(ctx.workspace, gap_id, "challenged", gap["version"])
            gap["version"] = moved["version"]
            gap["status"] = moved["status"]
        verdict, result, reason, papers = await self._judge(ctx, gap)
        await ctx.workspace.query(
            Q.RECORD_ATTEMPT,
            {
                "gap_id": gap_id,
                "id": str(uuid.uuid4()),
                "at": datetime.now(timezone.utc).isoformat(),
                "query": gap["signal"] or "cell",
                "result": result,
                "reason": reason[:400],
            },
        )
        final = await ctx.gaps.transition(ctx.workspace, gap_id, verdict, gap["version"])
        ctx.trace.step(
            "judge",
            {"signal": gap["signal"], "task": gap["task"], "family": gap["family"]},
            reason,
            papers,
        )
        return answer(
            reason,
            [{"ref_type": "paper", "ref_id": paper, "title": ""} for paper in papers],
            ctx.trace,
            [CAVEAT],
        ) | {"status": final["status"], "version": final["version"], "gap_id": gap_id}

    async def _gate(self, ctx, handoff_id: str) -> dict | None:
        if not handoff_id:
            return None
        return await ctx.gaps.resolve(ctx.workspace, handoff_id)

    async def _load(self, ctx, gap_id: str) -> dict:
        rows = await ctx.workspace.query(Q.GAP_SIGNAL, {"id": gap_id})
        if not rows:
            raise NotFound("not found")
        row = rows[0]
        return {
            "id": as_text(row[0]),
            "status": as_text(row[1]),
            "version": int(row[2] or 1),
            "task": as_text(row[3]),
            "family": as_text(row[4]),
            "signal": as_text(row[5]),
            "text": as_text(row[6]),
            "year": int(row[7] or 0),
            "score": row[8],
        }

    async def _judge(self, ctx, gap: dict) -> tuple[str, str, str, list[str]]:
        if not gap["task"] or not gap["family"]:
            return "alive", "found_nothing", "The gap has no task and method family to check.", []
        if gap["signal"] == "open_limitation":
            rows = await ctx.read_corpus(
                Q.LATER_PAPERS,
                {"task": gap["task"], "family": gap["family"], "year": gap["year"]},
            )
            papers = [as_text(row[0]) for row in rows]
            if papers:
                return "killed", "killed", f"A later paper uses this family on the task: {', '.join(papers)}.", papers
            return "alive", "found_nothing", "No later research paper revisits this limitation.", []
        rows = await ctx.read_corpus(Q.CELL_PAPERS, {"task": gap["task"], "family": gap["family"]})
        papers = [as_text(row[0]) for row in rows]
        if papers:
            return "killed", "killed", f"The cell is already occupied by {', '.join(papers)}.", papers
        nearby = await ctx.read_corpus(Q.TASK_PAPERS, {"task": gap["task"]})
        titles = [as_text(row[1]) for row in nearby[:2] if row[1]]
        reason = "No research paper occupies this cell."
        if titles:
            reason += " Papers on the task use other methods: " + "; ".join(titles)
        return "alive", "near_miss", reason, []
