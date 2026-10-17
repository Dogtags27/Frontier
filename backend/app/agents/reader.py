"""Read one paper, or turn a student note into knowledge on their graph.

Depth and the paper id come from the note. The concepts marked as known are the
task ids already linked to that paper. Nothing is copied off the corpus.
"""

import re

from app.agents.base import Agent, answer, as_text
from app.models.queries import Q

PAPER_ID = re.compile(r"\b\d{4}\.\d{4,5}\b")


class Reader(Agent):
    name = "reader"
    work_types = ("ingest_note",)

    async def handle(self, ctx, item: dict) -> dict:
        payload = item.get("payload") or {}
        if payload.get("mode") == "compare":
            return await self.compare(ctx, payload)
        if payload.get("paper_id") and not payload.get("note"):
            return await self.lookup(ctx, str(payload["paper_id"]))
        return await self.note(ctx, str(payload.get("note") or payload.get("text") or ""))

    async def lookup(self, ctx, paper_id: str) -> dict:
        rows = await ctx.read_corpus(Q.PAPER_NODE, {"id": paper_id})
        if not rows:
            return answer(f"I could not find {paper_id} in the corpus.", [], ctx.trace)
        title = as_text(rows[0][1])
        year = rows[0][2]
        claims = await ctx.read_corpus(Q.PAPER_CLAIMS, {"id": paper_id})
        snippet = ""
        if ctx.papers is not None:
            try:
                page = await ctx.papers.sentences(paper_id, None, 2, 0)
            except Exception:
                page = {}
            lines = [item.get("original") or "" for item in page.get("items") or []]
            snippet = " ".join(line for line in lines if line)[:400]
        text = f"{title} ({year})."
        if snippet:
            text += " " + snippet
        elif claims:
            text += " A claim from it: " + as_text(claims[0][2])[:180]
        ctx.trace.step("get_paper", {"paper_id": paper_id}, title[:180])
        return answer(text, [{"ref_type": "paper", "ref_id": paper_id, "title": title}], ctx.trace)

    async def compare(self, ctx, payload: dict) -> dict:
        left = str(payload.get("left") or "")
        right = str(payload.get("right") or "")
        if not left or not right:
            return answer("Name two papers to compare.", [], ctx.trace)
        shared = await self._shared_tasks(ctx, left, right)
        ctx.trace.step("compare_papers", {"left": left, "right": right}, f"{len(shared)} shared tasks")
        if not shared:
            text = f"{left} and {right} do not share a task in this corpus."
        else:
            text = f"{left} and {right} both address " + ", ".join(shared[:4]) + "."
        return answer(text, [{"ref_type": "paper", "ref_id": paper, "title": ""} for paper in (left, right)], ctx.trace)

    async def note(self, ctx, text: str) -> dict:
        papers = PAPER_ID.findall(text)
        depth = _depth(text)
        paper_id = papers[0] if papers else ""
        if paper_id:
            await ctx.memory.read(ctx.workspace, paper_id, depth, text[:280])
            tasks = await ctx.read_corpus(Q.PAPER_TASKS, {"id": paper_id})
            for row in tasks:
                await ctx.workspace.query(
                    Q.MARK_KNOWS,
                    {"student": "self", "kind": "task", "ref_id": as_text(row[0])},
                )
            await ctx.queue.enqueue(ctx.workspace.name, "map_field", {"paper_id": paper_id, "note": text[:300]})
        await ctx.queue.enqueue(
            ctx.workspace.name,
            "summarize_turn",
            {"text": text[:500], "paper_id": paper_id},
        )
        ctx.trace.step("ingest_note", {"paper_id": paper_id, "depth": depth}, "note saved and the reading path was queued")
        if paper_id:
            reply = f"I saved that as {depth} for {paper_id} and queued a new reading path."
        else:
            reply = "I saved that note and queued a memory update."
        return answer(reply, [{"ref_type": "paper", "ref_id": paper_id, "title": ""}] if paper_id else [], ctx.trace)

    async def _shared_tasks(self, ctx, left: str, right: str) -> list[str]:
        left_rows = await ctx.read_corpus(Q.PAPER_TASKS, {"id": left})
        right_rows = await ctx.read_corpus(Q.PAPER_TASKS, {"id": right})
        right_ids = {as_text(row[0]) for row in right_rows}
        names = []
        for row in left_rows:
            if as_text(row[0]) in right_ids:
                names.append(as_text(row[1]) or as_text(row[0]))
        return names


def _depth(text: str) -> str:
    lowered = text.lower()
    if "understood" in lowered:
        return "understood"
    if "skim" in lowered:
        return "skimmed"
    return "read"
