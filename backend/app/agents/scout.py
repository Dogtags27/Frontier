"""Search and citation navigation. Tool choice here is structural, not a model call."""

from app.agents.base import Agent, answer


class Scout(Agent):
    name = "scout"
    work_types = ()

    def __init__(self, tools):
        self.tools = tools

    async def handle(self, ctx, item: dict) -> dict:
        payload = item.get("payload") or {}
        evidence = []
        query = str(payload.get("q") or "").strip()
        paper_id = str(payload.get("paper_id") or "").strip()
        if query:
            found = await self.use_tool(ctx, self.tools, "search_papers", {"q": query})
            evidence.extend(_hits(found.get("items") or []))
        if paper_id:
            neighbors = await self.use_tool(ctx, self.tools, "expand_neighbors", {"paper_id": paper_id})
            evidence.extend(_hits(neighbors.get("cites") or []))
            chain = await self.use_tool(ctx, self.tools, "citation_chain", {"paper_id": paper_id})
            destination = str(payload.get("dst") or "").strip()
            if destination:
                await self.use_tool(ctx, self.tools, "shortest_path", {"src": paper_id, "dst": destination})
            elif chain.get("items"):
                evidence.extend(_hits(chain["items"]))
        if not evidence:
            text = "Nothing in the corpus matched that search."
        else:
            text = f"Found {len(evidence)} related papers."
        return answer(text, evidence[:8], ctx.trace)


def _hits(items: list[dict]) -> list[dict]:
    hits = []
    for item in items:
        paper_id = str(item.get("arxiv_id") or "")
        if not paper_id:
            continue
        hits.append({"ref_type": "paper", "ref_id": paper_id, "title": item.get("title") or ""})
    return hits
