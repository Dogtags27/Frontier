"""A note changes what is known, and the reading path is rebuilt from the graph."""

import uuid

import pytest
from redis.exceptions import ResponseError

from app.agents.cartographer import Cartographer
from app.agents.evidence import Evidence
from app.constants import get_settings
from app.models.queries import Q
from app.services.gaps import GapService
from app.services.memory import MemoryService
from app.services.queue import WorkQueue
from app.services.workspace import GraphHandle
from app.utilities.stores import GraphStore
from app.utilities.worker import Worker

PAPER = "2211.05920"


class Box:
    def __init__(self):
        self.settings = get_settings().model_copy(update={"work_hint_key": f"wq:hints:b9:{uuid.uuid4().hex}"})
        self.graph = GraphStore(self.settings)
        self.queue = WorkQueue(self.graph, None, self.settings)
        self.gaps = GapService(self.graph)
        self.memory = MemoryService(self.graph)


def _name() -> str:
    return f"frontier_ws_{uuid.uuid4().hex}"


async def _drop(box: Box, *names: str) -> None:
    for name in names:
        try:
            await box.graph.delete_graph(name)
        except ResponseError:
            pass
    await box.graph.close()


def _path(rows) -> list[str]:
    return [row[0] if not isinstance(row[0], bytes) else row[0].decode() for row in rows]


@pytest.mark.asyncio
async def test_a_note_rebuilds_the_reading_path_and_records_provenance():
    box = Box()
    name = _name()
    other = _name()
    try:
        before = await box.graph.run(box.settings.corpus_graph, Q.PRIVATE_NODES, ro=True)
        await box.graph.ensure_workspace(name)
        await box.graph.ensure_workspace(other)
        from app.agents.roster import context_for

        ctx = context_for(box, name)
        first = await Cartographer().handle(ctx, {"payload": {"paper_id": PAPER}})
        path = _path(await box.graph.run(name, Q.LIST_PATH))
        assert path[0] != PAPER and PAPER in path
        assert "Reading path" in first["text"]
        opened = path[0]

        await box.queue.enqueue(name, "ingest_note", {"note": f"I understood {opened}. The limit is labeling cost."})
        finished = await Worker(box).run_graph(name)
        assert finished == 3
        rebuilt = _path(await box.graph.run(name, Q.LIST_PATH))
        assert opened not in rebuilt
        assert rebuilt
        remembered = await box.memory.recall(GraphHandle(box.graph, name, "summary"), "labeling", 5)
        assert any("labeling" in item["text"] for item in remembered["memories"])

        checked = await Evidence().handle(context_for(box, name), {"payload": {"paper_id": PAPER}})
        assert checked["text"]
        findings = await box.graph.run(name, Q.FINDING_COUNT)
        assert findings[0][0] == 1

        other_path = await box.graph.run(other, Q.LIST_PATH)
        assert other_path == []
        after = await box.graph.run(box.settings.corpus_graph, Q.PRIVATE_NODES, ro=True)
        leaked = await box.graph.run(box.settings.corpus_graph, Q.STUDENT_WRITES, ro=True)
        assert after[0][0] == before[0][0] == 0
        assert leaked[0][0] == 0
    finally:
        await _drop(box, name, other)
