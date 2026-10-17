"""Phrase the brief from graph rows. The wording source is the graph, not a model."""

from app.agents.base import Agent, answer
from app.services.workspace import WorkspaceResolver


class Chronicler(Agent):
    name = "chronicler"
    work_types = ("write_brief",)

    async def handle(self, ctx, item: dict) -> dict:
        snapshot = await WorkspaceResolver(ctx.graph, None).progress(ctx.workspace)
        brief = await ctx.memory.brief(ctx.workspace, snapshot)
        await ctx.queue.store_brief(ctx.workspace.name, item["id"], brief["text"])
        reading = (snapshot.get("reading") or {}).get("recent") or []
        ctx.trace.step(
            "brief",
            {"gaps": len(snapshot.get("open_gaps") or []), "reads": len(reading)},
            brief["text"][:180],
        )
        return answer(brief["text"], [], ctx.trace) | {"summary": brief["text"], "source": brief["source"]}
