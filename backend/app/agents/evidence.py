"""Follow citations back from a paper. A shared origin is a private finding, not a corpus edit."""

import uuid
from collections import Counter
from datetime import datetime, timezone

from app.agents.base import Agent, answer, as_text
from app.models.queries import Q


class Evidence(Agent):
    name = "evidence"
    work_types = ("check_claim",)

    async def handle(self, ctx, item: dict) -> dict:
        payload = item.get("payload") or {}
        paper_id = str(payload.get("paper_id") or "")
        if not paper_id:
            return answer("Which paper should I trace?", [], ctx.trace)
        rows = await ctx.read_corpus(Q.PROVENANCE, {"id": paper_id})
        origins = Counter(as_text(row[2]) for row in rows if as_text(row[2]))
        cited = len({as_text(row[0]) for row in rows})
        ctx.trace.step("provenance_roots", {"paper_id": paper_id}, f"{cited} cited papers")
        collapsed = [(origin, count) for origin, count in origins.most_common(3) if count >= 2]
        if not collapsed:
            text = f"The papers cited by {paper_id} do not collapse onto one earlier paper."
            origin = ""
        else:
            origin, count = collapsed[0]
            text = (
                f"{count} papers cited by {paper_id} themselves cite {origin}. "
                "Those citations are not independent confirmations."
            )
        await ctx.workspace.query(
            Q.SAVE_FINDING,
            {
                "id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"provenance:{paper_id}:{origin}")),
                "at": datetime.now(timezone.utc).isoformat(),
                "kind": "provenance",
                "paper": paper_id,
                "summary": text[:500],
                "origin": origin,
            },
        )
        return answer(text, [{"ref_type": "paper", "ref_id": paper_id, "title": ""}], ctx.trace)
