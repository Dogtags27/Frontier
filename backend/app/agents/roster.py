"""Wires agents to work-item types. Adding an agent registers its types here."""

from app.agents.adversary import Adversary
from app.agents.base import AgentContext, Trace
from app.agents.cartographer import Cartographer
from app.agents.chronicler import Chronicler
from app.agents.evidence import Evidence
from app.agents.gaphunter import GapHunter
from app.agents.memory_writer import MemoryWriter
from app.agents.reader import Reader
from app.services.workspace import GraphHandle


def context_for(container, graph_name: str) -> AgentContext:
    return AgentContext(
        graph=container.graph,
        corpus=container.settings.corpus_graph,
        workspace=GraphHandle(container.graph, graph_name, "write"),
        memory=container.memory,
        gaps=container.gaps,
        queue=container.queue,
        settings=container.settings,
        search=getattr(container, "search", None),
        llm=getattr(container, "llm", None),
        papers=getattr(container, "papers", None),
        trace=Trace(),
    )


def worker_handlers(container) -> dict:
    hunter = GapHunter()
    adversary = Adversary()
    chronicler = Chronicler()
    cartographer = Cartographer()
    reader = Reader()
    evidence = Evidence()
    memory_writer = MemoryWriter()

    async def find_gaps(item, graph_name):
        return await hunter.handle(context_for(container, graph_name), item)

    async def challenge_gap(item, graph_name):
        return await adversary.handle(context_for(container, graph_name), item)

    async def write_brief(item, graph_name):
        return await chronicler.handle(context_for(container, graph_name), item)

    async def map_field(item, graph_name):
        return await cartographer.handle(context_for(container, graph_name), item)

    async def ingest_note(item, graph_name):
        return await reader.handle(context_for(container, graph_name), item)

    async def check_claim(item, graph_name):
        return await evidence.handle(context_for(container, graph_name), item)

    async def summarize_turn(item, graph_name):
        return await memory_writer.handle(context_for(container, graph_name), item)

    async def ingest_paper(item, graph_name):
        payload = item.get("payload") or {}
        ids = payload.get("arxiv_ids") or []
        if not ids:
            return {"papers": [], "skipped": True}
        return await container.ingest.write(ids)

    async def reassess_gap(item, graph_name):
        return await container.ingest.reassess(graph_name, item.get("payload") or {})

    async def resolve_handoff(item, graph_name):
        handoff_id = str(item.get("payload", {}).get("handoff_id") or "")
        if not handoff_id:
            raise ValueError("handoff_id is required")
        handle = GraphHandle(container.graph, graph_name, "write")
        return await container.gaps.resolve(handle, handoff_id)

    return {
        "find_gaps": find_gaps,
        "challenge_gap": challenge_gap,
        "write_brief": write_brief,
        "map_field": map_field,
        "ingest_note": ingest_note,
        "check_claim": check_claim,
        "summarize_turn": summarize_turn,
        "ingest_paper": ingest_paper,
        "reassess_gap": reassess_gap,
        "resolve_handoff": resolve_handoff,
    }
