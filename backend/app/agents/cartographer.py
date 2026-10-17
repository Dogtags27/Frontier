"""Build a reading path from the corpus around one paper.

The order is the citation walk: papers this one cites, papers that cite it,
then other papers on the same tasks. A note that marks a paper read removes it
from the next path.
"""

from datetime import datetime, timezone

from app.agents.base import Agent, answer, as_text
from app.models.queries import Q


class Cartographer(Agent):
    name = "cartographer"
    work_types = ("map_field",)

    async def handle(self, ctx, item: dict) -> dict:
        payload = item.get("payload") or {}
        paper_id = str(payload.get("paper_id") or "")
        tasks = await self._tasks(ctx, paper_id)
        reads = await self._reads(ctx)
        ctx.trace.step("field_map", {"paper_id": paper_id, "tasks": len(tasks)}, f"{len(tasks)} tasks in reach")
        steps = await self._steps(ctx, paper_id, tasks, reads)
        if not steps:
            return answer("Nothing unread is linked to that paper yet.", [], ctx.trace)
        summary = _summary(steps)
        await self._write_path(ctx, steps, summary)
        ctx.trace.step("reading_path", {"steps": [step["arxiv_id"] for step in steps]}, summary[:180])
        return answer(summary, [{"ref_type": "paper", "ref_id": step["arxiv_id"], "title": step["title"]} for step in steps], ctx.trace)

    async def _tasks(self, ctx, paper_id: str) -> list[str]:
        known = await ctx.workspace.query(Q.KNOWN_TASKS)
        tasks = [as_text(row[0]) for row in known if row[0]]
        if paper_id:
            rows = await ctx.read_corpus(Q.PAPER_TASKS, {"id": paper_id})
            tasks.extend(as_text(row[0]) for row in rows)
        return list(dict.fromkeys(tasks))

    async def _steps(self, ctx, paper_id: str, tasks: list[str], reads: set[str]) -> list[dict]:
        skip = list(reads) or ["__none__"]
        rows = []
        if paper_id:
            rows.extend(await ctx.read_corpus(Q.CITED_BY_PAPER, {"id": paper_id, "skip": skip}))
            rows.extend(await ctx.read_corpus(Q.CITES_PAPER, {"id": paper_id, "skip": skip}))
        if tasks:
            rows.extend(await ctx.read_corpus(Q.PAPERS_ON_TASKS, {"tasks": tasks, "skip": skip}))
        steps = []
        seen = set()
        for row in rows:
            arxiv_id = as_text(row[0])
            if not arxiv_id or arxiv_id in seen or arxiv_id in reads:
                continue
            seen.add(arxiv_id)
            steps.append({"arxiv_id": arxiv_id, "title": as_text(row[1]), "year": row[2]})
        if paper_id and paper_id not in reads and paper_id not in seen:
            titled = await ctx.read_corpus(Q.PAPER_NODE, {"id": paper_id})
            title = as_text(titled[0][1]) if titled else paper_id
            steps.append({"arxiv_id": paper_id, "title": title, "year": titled[0][2] if titled else None})
        return steps[:8]

    async def _reads(self, ctx) -> set[str]:
        rows = await ctx.workspace.query(Q.READ_IDS)
        return {as_text(row[0]) for row in rows if row[0]}

    async def _write_path(self, ctx, steps: list[dict], summary: str) -> None:
        at = datetime.now(timezone.utc).isoformat()
        await ctx.workspace.query(Q.CLEAR_PATH)
        for order, step in enumerate(steps):
            await ctx.workspace.query(
                Q.ADD_PATH_STEP,
                {"id": step["arxiv_id"], "order": order, "at": at, "summary": summary[:500]},
            )
        for earlier, later in zip(steps, steps[1:]):
            await ctx.workspace.query(Q.LINK_NEXT, {"src": earlier["arxiv_id"], "dst": later["arxiv_id"]})


def _summary(steps: list[dict]) -> str:
    if not steps:
        return "The reading path is empty."
    titles = [step["title"] or step["arxiv_id"] for step in steps[:4]]
    return "Reading path: " + " → ".join(titles) + "."
