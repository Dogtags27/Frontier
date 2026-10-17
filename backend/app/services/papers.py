"""One paper: its text, facets, citation neighbors, and a short-lived PDF link."""

import asyncio
import re

from app.core import NotFound, Upstream
from app.models.queries import Q, SQL

ARXIV_ID = re.compile(r"^[A-Za-z0-9./_-]{3,40}$")


class PaperService:
    def __init__(self, graph, pg, blob, settings):
        self.graph = graph
        self.pg = pg
        self.blob = blob
        self.settings = settings

    async def get(self, arxiv_id: str) -> dict:
        self._check(arxiv_id)
        rows = await self.pg.fetch(SQL.PAPER_ROW, (arxiv_id,))
        if not rows:
            raise NotFound("paper not found")
        row = rows[0]
        graph_rows = await self._rows(Q.PAPER_NODE, {"id": arxiv_id})
        paper_kind = _text(graph_rows[0][5]) if graph_rows else ""
        return {
            "arxiv_id": row[0],
            "title": row[1],
            "year": row[2],
            "category": row[3],
            "categories": row[4],
            "layer": row[5],
            "paper_kind": paper_kind,
            "abstract": row[6] or "",
        }

    async def sentences(self, arxiv_id: str, n: int | None, limit: int, offset: int) -> dict:
        self._check(arxiv_id)
        await self.get(arxiv_id)
        if n is not None:
            rows = await self.pg.fetch(SQL.SENTENCE_ONE, (arxiv_id, n))
            items = [{"n": row[0], "original": row[1] or ""} for row in rows]
            return {"arxiv_id": arxiv_id, "items": items}
        limit = min(max(limit, 1), 30)
        offset = max(offset, 0)
        rows = await self.pg.fetch(SQL.SENTENCE_PAGE, (arxiv_id, limit, offset))
        return {
            "arxiv_id": arxiv_id,
            "items": [{"n": row[0], "original": row[1] or ""} for row in rows],
        }

    async def facets(self, arxiv_id: str) -> dict:
        self._check(arxiv_id)
        rows = await self._rows(Q.FACETS, {"id": arxiv_id})
        if not rows:
            raise NotFound("paper not found")
        tasks, methods, datasets, metrics = rows[0]
        return {
            "arxiv_id": arxiv_id,
            "tasks": _pairs(tasks),
            "methods": _pairs(methods),
            "datasets": _pairs(datasets),
            "metrics": _pairs(metrics),
        }

    async def neighbors(self, arxiv_id: str) -> dict:
        self._check(arxiv_id)
        node = await self._rows(Q.PAPER_NODE, {"id": arxiv_id})
        if not node:
            raise NotFound("paper not found")
        cites = await self._rows(Q.CITES_OUT, {"id": arxiv_id})
        cited_by = await self._rows(Q.CITES_IN, {"id": arxiv_id})
        return {
            "arxiv_id": arxiv_id,
            "cites": [_neighbor(row) for row in cites],
            "cited_by": [_neighbor(row) for row in cited_by],
        }

    def presign(self, arxiv_id: str, r2_key: str) -> dict:
        self._check(arxiv_id)
        if not r2_key:
            raise NotFound("paper not found")
        try:
            url = self.blob.presign(r2_key, expires=120)
        except Exception as exc:
            raise Upstream("the pdf link could not be signed", type(exc).__name__) from exc
        return {"arxiv_id": arxiv_id, "url": url, "expires_in": 120}

    async def pdf(self, arxiv_id: str) -> dict:
        self._check(arxiv_id)
        rows = await self.pg.fetch(SQL.PAPER_ROW, (arxiv_id,))
        if not rows:
            raise NotFound("paper not found")
        return self.presign(arxiv_id, rows[0][7])

    async def pdf_bytes(self, arxiv_id: str) -> bytes:
        """Stream the PDF through the API so the browser never needs bucket CORS."""
        self._check(arxiv_id)
        rows = await self.pg.fetch(SQL.PAPER_ROW, (arxiv_id,))
        if not rows or not rows[0][7]:
            raise NotFound("paper not found")
        try:
            return await asyncio.to_thread(self.blob.get, rows[0][7])
        except Exception as exc:
            raise Upstream("the pdf could not be read", type(exc).__name__) from exc

    async def claims(self, arxiv_id: str) -> dict:
        """Claims the extractor found, each with the original sentence it came from."""
        self._check(arxiv_id)
        node = await self._rows(Q.PAPER_NODE, {"id": arxiv_id})
        if not node:
            raise NotFound("paper not found")
        rows = await self._rows(Q.PAPER_CLAIMS, {"id": arxiv_id})
        spans = [int(row[3]) for row in rows if row[3] is not None]
        found = {}
        if spans:
            for row in await self.pg.fetch(SQL.SENTENCES_FOR, ([arxiv_id] * len(spans), spans)):
                found[int(row[1])] = _text(row[2])
        items = []
        for row in rows:
            span = int(row[3]) if row[3] is not None else None
            items.append(
                {
                    "id": _text(row[0]),
                    "kind": _text(row[1]),
                    "label": _text(row[2]),
                    "span": span,
                    "sentence": found.get(span, "") if span is not None else "",
                }
            )
        return {"arxiv_id": arxiv_id, "items": items}

    async def provenance(self, arxiv_id: str) -> dict:
        self._check(arxiv_id)
        node = await self._rows(Q.PAPER_NODE, {"id": arxiv_id})
        if not node:
            raise NotFound("paper not found")
        claims = await self._rows(Q.PAPER_CLAIMS, {"id": arxiv_id})
        sentence = ""
        if claims:
            sentence = _text(claims[0][2]) or _text(claims[0][3])
        rows = await self._rows(Q.STRIP, {"id": arxiv_id})
        groups: dict[str, dict] = {}
        order: list[str] = []
        for row in rows:
            later_id = _text(row[0])
            earlier_id = _text(row[3])
            if earlier_id == arxiv_id:
                earlier_id = ""
            key = earlier_id or ""
            if key not in groups:
                groups[key] = {
                    "earlier": (
                        {"arxiv_id": earlier_id, "title": _text(row[4]), "year": int(row[5] or 0)}
                        if earlier_id
                        else None
                    ),
                    "later": [],
                }
                order.append(key)
            seen = {item["arxiv_id"] for item in groups[key]["later"]}
            if later_id and later_id not in seen:
                groups[key]["later"].append(
                    {"arxiv_id": later_id, "title": _text(row[1]), "year": int(row[2] or 0)}
                )
        return {
            "arxiv_id": arxiv_id,
            "sentence": sentence,
            "groups": [groups[key] for key in order],
        }

    async def _rows(self, query, params):
        return await self.graph.run(self.settings.corpus_graph, query, params, ro=True)

    def _check(self, arxiv_id: str) -> None:
        if not ARXIV_ID.match(arxiv_id or ""):
            raise NotFound("paper not found")


def _text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode()
    return str(value)


def _pairs(items) -> list[dict]:
    found = []
    seen = set()
    for item in items or []:
        if isinstance(item, dict):
            slug, name = item.get("slug"), item.get("name")
        else:
            slug, name = item[0], item[1]
        slug, name = _text(slug), _text(name)
        if not slug or slug in seen:
            continue
        seen.add(slug)
        found.append({"slug": slug, "name": name})
    return found


def _neighbor(row) -> dict:
    return {"arxiv_id": _text(row[0]), "title": _text(row[1]), "year": int(row[2] or 0)}
