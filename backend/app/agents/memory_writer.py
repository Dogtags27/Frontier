"""Turn a saved note into one durable memory. The text stays the student's, not a model's."""

from app.agents.base import Agent, answer


class MemoryWriter(Agent):
    name = "memory_writer"
    work_types = ("summarize_turn",)

    async def handle(self, ctx, item: dict) -> dict:
        payload = item.get("payload") or {}
        text = str(payload.get("text") or "").strip()
        paper_id = str(payload.get("paper_id") or "")
        if not text:
            return answer("Nothing new to remember.", [], ctx.trace)
        kind = "belief" if any(word in text.lower() for word in ("limit", "think", "because")) else "interest"
        saved = await ctx.memory.remember(ctx.workspace, kind, text[:500], paper_id or "note")
        ctx.trace.step("remember", {"kind": kind, "paper_id": paper_id}, "memory updated" if not saved.get("duplicate") else "already remembered")
        return answer("I kept that in your research memory.", [], ctx.trace) | {"id": saved["id"], "duplicate": saved["duplicate"]}
