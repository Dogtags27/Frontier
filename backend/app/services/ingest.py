"""Write extracted papers into the shared corpus, then reassess open gaps.

The facets are already on disk. This does not call a model. A filled cell
scoops only the workspaces listed in the open-gap index.
"""

import asyncio
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.core import BadRequest
from app.models.queries import Q, SQL
from app.services.workspace import GraphHandle

BATCH = 20
REPO = Path(__file__).resolve().parents[3]


class IngestService:
    def __init__(self, graph, pg, queue, gaps, settings):
        self.graph = graph
        self.pg = pg
        self.queue = queue
        self.gaps = gaps
        self.settings = settings

    async def write(self, arxiv_ids: list[str]) -> dict:
        ids = _ids(arxiv_ids)
        loaded = await self.graph.run(self.settings.corpus_graph, Q.ALL_IDS, ro=True)
        known = [_text(row[0]) for row in loaded]
        built = await asyncio.to_thread(_assemble, ids, known)
        corpus = self.settings.corpus_graph
        tx = datetime.now(timezone.utc).isoformat()
        await self.graph.run(corpus, Q.MERGE_PAPER, {"rows": built["papers"], "tx": tx})
        for rel, query in Q.PAPER_EDGE.items():
            rows = [row for row in built["paper_edges"] if row["rel"] == rel]
            if rows:
                await self.graph.run(corpus, query, {"rows": rows})
        if built["claims"]:
            await self.graph.run(corpus, Q.MERGE_CLAIM, {"rows": built["claims"]})
        if built["cites"]:
            await self.graph.run(corpus, Q.MERGE_CITES, {"rows": built["cites"]})
        cells = await self.graph.run(corpus, Q.PAPER_CELLS, {"ids": ids}, ro=True)
        queued = await self._queue_reassess(cells)
        return {"papers": ids, "cells": len(cells), "reassess": queued}

    async def reassess(self, graph_name: str, payload: dict) -> dict:
        scooped = []
        handle = GraphHandle(self.graph, graph_name, "write")
        for cell in payload.get("cells") or []:
            task = str(cell.get("task_id") or "")
            family = str(cell.get("method_family") or "")
            method_id = str(cell.get("method_family_id") or "")
            if not task or not family:
                continue
            count = await self.graph.run(self.settings.corpus_graph, Q.CELL_COUNT, {"task": task, "family": family}, ro=True)
            if not count or int(count[0][0] or 0) < 1:
                continue
            paper = await self.graph.run(self.settings.corpus_graph, Q.FILLING_PAPER, {"task": task, "family": family}, ro=True)
            if not paper:
                continue
            gaps = await handle.query(Q.OPEN_CELL_GAPS, {"task": task, "family": family})
            at = datetime.now(timezone.utc).isoformat()
            for gap in gaps:
                rows = await handle.query(
                    Q.SCOOP_GAP,
                    {
                        "id": _text(gap[0]),
                        "at": at,
                        "paper": _text(paper[0][0]),
                        "event": f"scoop-{_text(gap[0])}",
                    },
                )
                if rows:
                    scooped.append(_text(rows[0][0]))
            if scooped:
                await self.gaps.note_cell(graph_name, task, method_id, family, False)
        return {"scooped": scooped}

    async def _queue_reassess(self, cells) -> list[str]:
        grouped: dict[str, list[dict]] = {}
        for row in cells:
            task, family, method_id = _text(row[0]), _text(row[1]), _text(row[2])
            if not task or not family:
                continue
            found = await self.pg.fetch(SQL.GRAPHS_FOR_CELL, (task, family))
            for graph_name, indexed_method in found:
                grouped.setdefault(graph_name, [])
                cell = {"task_id": task, "method_family": family, "method_family_id": indexed_method or method_id}
                if cell not in grouped[graph_name]:
                    grouped[graph_name].append(cell)
        queued = []
        for graph_name, items in grouped.items():
            job = await self.queue.enqueue(graph_name, "reassess_gap", {"cells": items})
            queued.append(job["id"])
        return queued


def _ids(arxiv_ids: list[str]) -> list[str]:
    cleaned = []
    for raw in arxiv_ids:
        value = str(raw).strip()
        if value and value not in cleaned:
            cleaned.append(value)
    if not cleaned:
        raise BadRequest("arxiv_ids is required")
    if len(cleaned) > BATCH:
        raise BadRequest(f"at most {BATCH} papers")
    return cleaned


def _assemble(ids: list[str], loaded: list[str]) -> dict:
    data = REPO / "data"
    if not (data / "load_corpus.py").exists():
        raise BadRequest("paper extract files are not on this server")
    if str(data) not in sys.path:
        sys.path.insert(0, str(data))
    from load_corpus import build

    try:
        return build(ids, loaded)
    except SystemExit as exc:
        raise BadRequest(str(exc)) from exc


def _text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode()
    return str(value)
