"""Note to a ranked gap to a verdict. GapHunter does not call a model."""

import uuid

import pytest
from redis.exceptions import ResponseError

from app.agents.base import AgentContext, Trace
from app.agents.scout import Scout
from app.agents.tools import GraphToolkit
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
        self.settings = get_settings().model_copy(
            update={"work_hint_key": f"wq:hints:b6:{uuid.uuid4().hex}"}
        )
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


@pytest.mark.asyncio
async def test_a_note_becomes_a_ranked_gap_and_a_verdict():
    box = Box()
    name = _name()
    other = _name()
    try:
        before = await box.graph.run(box.settings.corpus_graph, Q.PRIVATE_NODES, ro=True)
        await box.graph.ensure_workspace(name)
        await box.graph.ensure_workspace(other)
        handle = GraphHandle(box.graph, name, "write")
        await box.memory.read(handle, PAPER, "read", "labeling cost is the limit")
        job = await box.queue.enqueue(
            name,
            "find_gaps",
            {"paper_id": PAPER, "note": "I read 2211.05920. Labeling defect data is expensive."},
        )
        finished = await Worker(box).run_graph(name)
        assert finished == 2
        found = await box.queue.get(name, job["id"])
        assert found["status"] == "done"
        assert found["result"]["caveats"]
        gaps = found["result"]["evidence"]
        assert gaps
        scores = [item["score"] for item in gaps]
        assert scores == sorted(scores, reverse=True)
        tools = [step["tool"] for step in found["result"]["trace"]]
        assert "seed" in tools and "rank" in tools

        challenge = await box.queue.get(name, found["result"]["job_id"])
        assert challenge["status"] == "done"
        assert challenge["result"]["status"] in {"alive", "killed"}
        judged = [step for step in challenge["result"]["trace"] if step["tool"] == "judge"]
        assert judged and judged[0]["result_summary"]
        attempts = await box.graph.run(name, Q.GAP_ATTEMPTS, {"id": challenge["result"]["gap_id"]})
        assert attempts

        untouched = await box.graph.run(other, Q.COUNT_GAPS, ro=True)
        assert int(untouched[0][0]) == 0
        after = await box.graph.run(box.settings.corpus_graph, Q.PRIVATE_NODES, ro=True)
        assert int(before[0][0]) == int(after[0][0]) == 0
    finally:
        await _drop(box, name, other)


@pytest.mark.asyncio
async def test_scout_follows_citations_without_a_model():
    box = Box()
    try:
        tools = GraphToolkit(box.graph, box.settings.corpus_graph)
        scout = Scout(tools)
        ctx = AgentContext(
            graph=box.graph,
            corpus=box.settings.corpus_graph,
            workspace=None,
            memory=None,
            gaps=None,
            queue=None,
            settings=box.settings,
            trace=Trace(),
        )
        result = await scout.handle(ctx, {"payload": {"paper_id": PAPER, "q": "defect"}})
        assert result["evidence"]
        assert any(step["tool"] == "expand_neighbors" for step in result["trace"])
        assert any(step["tool"] == "search_papers" for step in result["trace"])
        neighbors = await tools.expand_neighbors({"paper_id": PAPER})
        assert neighbors["cites"]
    finally:
        await box.graph.close()
