"""A gap becomes a small experiment made only from corpus datasets and metrics."""

import uuid

import pytest
from redis.exceptions import ResponseError

from app.agents.roster import context_for
from app.agents.scoper import Scoper
from app.constants import get_settings
from app.models.queries import Q
from app.services.gaps import GapService
from app.services.memory import MemoryService
from app.services.queue import WorkQueue
from app.utilities.stores import GraphStore

TASK = "problem:1326"
FAMILY = "SMOTE for class imbalance handling"


class Box:
    def __init__(self):
        self.settings = get_settings().model_copy(update={"work_hint_key": f"wq:hints:scope:{uuid.uuid4().hex}"})
        self.graph = GraphStore(self.settings)
        self.queue = WorkQueue(self.graph, None, self.settings)
        self.gaps = GapService(self.graph)
        self.memory = MemoryService(self.graph)


def _name() -> str:
    return f"frontier_ws_{uuid.uuid4().hex}"


@pytest.mark.asyncio
async def test_an_open_gap_gets_a_corpus_backed_experiment():
    box = Box()
    name = _name()
    other = _name()
    gap_id = f"gap-{uuid.uuid4().hex[:12]}"
    try:
        before = await box.graph.run(box.settings.corpus_graph, Q.PRIVATE_NODES, ro=True)
        await box.graph.ensure_workspace(name)
        await box.graph.ensure_workspace(other)
        ctx = context_for(box, name)
        await ctx.workspace.query(
            Q.SAVE_GAP,
            {
                "id": gap_id,
                "at": "2026-10-17T00:00:00+00:00",
                "task": TASK,
                "family": FAMILY,
                "method": "method:6974",
                "score": 3,
                "text": "SMOTE is untested on this task",
                "signal": "empty_cell",
                "year": 2022,
                "event_id": f"opened-{gap_id}",
            },
        )
        await box.gaps.add_evidence(ctx.workspace, gap_id, "2211.05920", "paper")
        planned = await Scoper().handle(ctx, {"payload": {}})
        assert "714 open-source GitHub Java projects" in planned["text"]
        assert "score it with" in planned["text"]
        assert "2211.05920" in planned["text"]
        saved = await box.graph.run(name, Q.LIST_PLANS)
        assert saved and saved[0][0] == gap_id
        assert await box.graph.run(other, Q.LIST_PLANS) == []

        challenged = await box.gaps.transition(ctx.workspace, gap_id, "challenged", 1)
        await box.gaps.transition(ctx.workspace, gap_id, "killed", challenged["version"])
        closed = await Scoper().handle(context_for(box, name), {"payload": {"gap_id": gap_id}})
        assert "killed" in closed["text"]
        after = await box.graph.run(box.settings.corpus_graph, Q.PRIVATE_NODES, ro=True)
        assert int(after[0][0]) == int(before[0][0]) == 0
    finally:
        for graph_name in (name, other):
            try:
                await box.graph.delete_graph(graph_name)
            except ResponseError:
                pass
        await box.graph.close()
