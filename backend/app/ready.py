"""Readiness compares live store counts with data/extract/manifest.json."""

import json
from dataclasses import dataclass

from app.core import Container
from app.models.queries import Q, SQL


@dataclass
class Check:
    name: str
    ok: bool
    expected: int | None = None
    actual: int | None = None
    detail: str | None = None

    def as_dict(self) -> dict:
        body = {"name": self.name, "ok": self.ok}
        if self.expected is not None:
            body["expected"] = self.expected
        if self.actual is not None:
            body["actual"] = self.actual
        if self.detail:
            body["detail"] = self.detail
        return body


def expected_counts(manifest: dict) -> dict[str, int]:
    """The manifest fields a ready corpus has to match. Claims without vectors are excluded."""
    nodes = manifest["canonical_nodes"]
    papers = manifest["papers"]
    return {
        "graph_papers": papers,
        "pg_papers": papers,
        "graph_foundation": manifest["foundation"],
        "pg_foundation": manifest["foundation"],
        "graph_recent": manifest["recent"],
        "pg_recent": manifest["recent"],
        "sentences": manifest["sentences"],
        "tasks": nodes["problem"],
        "methods": nodes["method"],
        "datasets": nodes["dataset"],
        "metrics": nodes["metric"],
        "aliases": manifest["alias_rows"],
        "claim_vectors": manifest["claims_embedded"],
        "r2_objects": papers,
        "corpus_private_nodes": 0,
        "papers_missing_vector": 0,
    }


def compare(expected: dict[str, int], actual: dict[str, int]) -> list[Check]:
    checks = []
    for name in expected:
        got = actual.get(name)
        checks.append(Check(name=name, ok=got == expected[name], expected=expected[name], actual=got))
    return checks


class ReadyService:
    """Collects counts from the three stores and compares them to the manifest."""

    def __init__(self, container: Container):
        self._container = container

    async def report(self) -> tuple[bool, list[Check]]:
        settings = self._container.settings
        if not settings.manifest.exists():
            return False, [Check("manifest", False, detail=f"missing {settings.manifest}")]
        manifest = json.loads(settings.manifest.read_text(encoding="utf-8"))
        expected = expected_counts(manifest)
        actual, failures = await self._actual()
        checks = compare(expected, actual)
        checks.extend(failures)
        return all(item.ok for item in checks), checks

    async def _actual(self) -> tuple[dict[str, int], list[Check]]:
        actual: dict[str, int] = {}
        failures: list[Check] = []
        graph = self._container.graph
        pg = self._container.pg
        corpus = self._container.settings.corpus_graph

        try:
            actual.update(await self._graph_counts(graph, corpus))
        except Exception as exc:
            failures.append(Check("falkordb", False, detail=f"{type(exc).__name__}: {exc}"))
        try:
            actual.update(await _postgres_counts(pg))
        except Exception as exc:
            failures.append(Check("postgres", False, detail=f"{type(exc).__name__}: {exc}"))
        try:
            actual["r2_objects"] = await self._container.blob.count_prefix("papers/")
        except Exception as exc:
            failures.append(Check("r2", False, detail=f"{type(exc).__name__}: {exc}"))
        return actual, failures

    async def _graph_counts(self, graph, corpus: str) -> dict[str, int]:
        async def one(query: str) -> int:
            rows = await graph.run(corpus, query, ro=True)
            return int(rows[0][0])

        layers = await graph.run(corpus, Q.LAYER_COUNTS, ro=True)
        by_layer = {_text(row[0]): int(row[1]) for row in layers}
        return {
            "graph_papers": await one(Q.PAPER_COUNT),
            "graph_foundation": by_layer.get("foundation", 0),
            "graph_recent": by_layer.get("recent", 0),
            "tasks": await one(Q.TASK_COUNT),
            "methods": await one(Q.METHOD_COUNT),
            "datasets": await one(Q.DATASET_COUNT),
            "metrics": await one(Q.METRIC_COUNT),
            "aliases": await one(Q.LABEL_COUNT),
            "claim_vectors": await one(Q.CLAIM_VECTORS),
            "papers_missing_vector": await one(Q.PAPERS_MISSING_VECTOR),
            "corpus_private_nodes": await one(Q.PRIVATE_NODES),
        }


async def _postgres_counts(pg) -> dict[str, int]:
    if pg.error or pg._pool is None:
        raise RuntimeError(pg.error or "postgres is not open")
    papers = await pg.fetch(SQL.PAPER_COUNT)
    sentences = await pg.fetch(SQL.SENTENCE_COUNT)
    layers = await pg.fetch(SQL.LAYER_COUNTS)
    by_layer = {row[0]: int(row[1]) for row in layers}
    return {
        "pg_papers": int(papers[0][0]),
        "sentences": int(sentences[0][0]),
        "pg_foundation": by_layer.get("foundation", 0),
        "pg_recent": by_layer.get("recent", 0),
    }


def _text(value):
    return value.decode() if isinstance(value, bytes) else value
