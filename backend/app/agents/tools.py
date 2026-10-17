"""Fixed corpus tools. The model never supplies the Cypher."""

from app.agents.base import as_text
from app.models.queries import Q
from app.services.search import fulltext_query


class GraphToolkit:
    """The tools Scout and the later agents share. Each one runs a named query."""

    def __init__(self, graph, corpus: str):
        self.graph = graph
        self.corpus = corpus
        self._tools = {
            "search_papers": self.search_papers,
            "expand_neighbors": self.expand_neighbors,
            "citation_chain": self.citation_chain,
            "shortest_path": self.shortest_path,
        }

    async def run(self, name: str, args: dict) -> dict:
        tool = self._tools.get(name)
        if tool is None:
            return {"summary": f"unknown tool {name}", "items": []}
        return await tool(args or {})

    async def search_papers(self, args: dict) -> dict:
        text = fulltext_query(str(args.get("q") or ""))
        if not text:
            return {"summary": "empty query", "items": []}
        rows = await self.graph.run(self.corpus, Q.FULLTEXT_PAPERS, {"q": text, "limit": 5}, ro=True)
        items = [{"arxiv_id": as_text(row[0]), "title": as_text(row[1]), "year": row[2]} for row in rows]
        return {"summary": f"{len(items)} title matches", "items": items}

    async def expand_neighbors(self, args: dict) -> dict:
        paper_id = str(args.get("paper_id") or "")
        outgoing = await self.graph.run(self.corpus, Q.CITES_OUT, {"id": paper_id}, ro=True)
        incoming = await self.graph.run(self.corpus, Q.CITES_IN, {"id": paper_id}, ro=True)
        cites = [_paper(row) for row in outgoing]
        cited_by = [_paper(row) for row in incoming]
        return {
            "summary": f"{len(cites)} cited, {len(cited_by)} citing",
            "cites": cites,
            "cited_by": cited_by,
        }

    async def citation_chain(self, args: dict) -> dict:
        paper_id = str(args.get("paper_id") or "")
        rows = await self.graph.run(self.corpus, Q.CITATION_CHAIN, {"id": paper_id}, ro=True)
        items = []
        for row in rows:
            items.append(
                {
                    "arxiv_id": as_text(row[0]),
                    "title": as_text(row[1]),
                    "year": row[2],
                    "next_id": as_text(row[3]),
                    "next_title": as_text(row[4]),
                }
            )
        return {"summary": f"{len(items)} citation steps", "items": items}

    async def shortest_path(self, args: dict) -> dict:
        src = str(args.get("src") or "")
        dst = str(args.get("dst") or "")
        try:
            rows = await self.graph.run(self.corpus, Q.SHORTEST_CITES, {"src": src, "dst": dst}, ro=True)
        except Exception as exc:
            return {"summary": f"no path ({type(exc).__name__})", "path": []}
        if not rows or not rows[0][0]:
            return {"summary": "no citation path within 4 hops", "path": []}
        path = [as_text(node) for node in rows[0][0]]
        return {"summary": f"path length {len(path)}", "path": path}


def _paper(row) -> dict:
    return {"arxiv_id": as_text(row[0]), "title": as_text(row[1]), "year": row[2]}
