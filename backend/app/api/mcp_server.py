"""Student research tools for an external model.

The caller is already a signed-in student. These functions are the same
operations the chat box runs: search, citations, notes, memory, gaps,
reading path, evidence, and a full chat turn. They read and write that
student's graph only.
"""

import os
from contextvars import ContextVar

from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

from app.agents.cartographer import Cartographer
from app.agents.chronicler import Chronicler
from app.agents.evidence import Evidence
from app.agents.reader import Reader
from app.agents.scoper import Scoper
from app.agents.tools import GraphToolkit
from app.core import AppError
from app.services.chat import ChatService

caller: ContextVar = ContextVar("mcp_caller")


def _pair():
    return caller.get()


def _toolkit() -> GraphToolkit:
    box, _principal = _pair()
    return GraphToolkit(box.graph, box.settings.corpus_graph)


def _chat() -> tuple[object, object, ChatService]:
    box, principal = _pair()
    return box, principal, ChatService(box)


def _security() -> TransportSecuritySettings:
    hosts = [
        "localhost",
        "localhost:*",
        "127.0.0.1",
        "127.0.0.1:*",
        "testclient",
        "testclient:*",
        "testserver",
        "testserver:*",
    ]
    for host in os.environ.get("MCP_ALLOWED_HOSTS", "").split(","):
        host = host.strip()
        if not host:
            continue
        hosts.append(host)
        if ":" not in host:
            hosts.append(f"{host}:*")
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=hosts,
        allowed_origins=[],
    )


def build_server() -> tuple[MCPServer, object]:
    server = MCPServer("Frontier")

    @server.tool()
    async def research_chat(message: str) -> dict:
        """Send one message through the same research chat a student uses in the app."""
        box, principal, chat = _chat()
        try:
            await box.limiter.budget.assert_open(principal)
            return await chat.reply(principal, message)
        except AppError as exc:
            return {"text": exc.message, "error": exc.code}

    @server.tool()
    async def search_papers(q: str) -> dict:
        """Find papers whose titles match these words in the shared corpus."""
        return await _toolkit().search_papers({"q": q})

    @server.tool()
    async def lookup_paper(paper_id: str) -> dict:
        """Read one paper's title, year, and a short claim or passage."""
        _box, principal, chat = _chat()
        return await Reader().lookup(chat._ctx(principal), paper_id)

    @server.tool()
    async def compare_papers(left: str, right: str) -> dict:
        """Compare two papers by the tasks they both address."""
        _box, principal, chat = _chat()
        return await Reader().compare(chat._ctx(principal), {"left": left, "right": right})

    @server.tool()
    async def expand_neighbors(paper_id: str) -> dict:
        """List papers this one cites and papers that cite it."""
        return await _toolkit().expand_neighbors({"paper_id": paper_id})

    @server.tool()
    async def citation_chain(paper_id: str) -> dict:
        """Walk one step out along citation edges from this paper."""
        return await _toolkit().citation_chain({"paper_id": paper_id})

    @server.tool()
    async def shortest_path(src: str, dst: str) -> dict:
        """Shortest citation path between two papers, at most four hops."""
        return await _toolkit().shortest_path({"src": src, "dst": dst})

    @server.tool()
    async def plan_reading(paper_id: str) -> dict:
        """Build this student's reading path around one paper and save it on their graph."""
        _box, principal, chat = _chat()
        return await Cartographer().handle(chat._ctx(principal), {"payload": {"paper_id": paper_id}})

    @server.tool()
    async def check_evidence(paper_id: str) -> dict:
        """See whether this paper's citations collapse onto one earlier paper."""
        _box, principal, chat = _chat()
        return await Evidence().handle(chat._ctx(principal), {"payload": {"paper_id": paper_id}})

    @server.tool()
    async def record_note(text: str) -> dict:
        """Save a research note. A paper id in the note is marked read and the reading path is queued."""
        _box, principal, chat = _chat()
        return await Reader().note(chat._ctx(principal), text)

    @server.tool()
    async def recall_memory(query: str) -> dict:
        """Recall this student's saved notes and open gaps. Does not return chat transcripts."""
        box, principal, _chat_service = _chat()
        return await box.memory.recall(chat_handle(principal), query, 5)

    @server.tool()
    async def research_progress() -> dict:
        """Summarize this student's reading, gaps, and decisions. No chat text."""
        _box, principal, chat = _chat()
        return await Chronicler().handle(chat._ctx(principal), {"id": "mcp-brief", "payload": {}})

    @server.tool()
    async def plan_experiment(gap_id: str = "") -> dict:
        """Plan the smallest experiment for one open gap, using a dataset and metric already in the corpus."""
        _box, principal, chat = _chat()
        return await Scoper().handle(chat._ctx(principal), {"payload": {"gap_id": gap_id}})

    @server.tool()
    async def find_gaps(paper_id: str, note: str = "") -> dict:
        """Queue a gap search for this student. The worker writes the result; use job_status to read it."""
        box, principal, _chat_service = _chat()
        job = await box.queue.enqueue(
            principal.graph_name,
            "find_gaps",
            {"paper_id": paper_id, "note": note[:500]},
        )
        return {"text": "Gap search queued.", "job_id": job["id"]}

    @server.tool()
    async def job_status(job_id: str) -> dict:
        """Read one queued job on this student's graph."""
        box, principal, _chat_service = _chat()
        try:
            return await box.queue.get(principal.graph_name, job_id)
        except AppError as exc:
            return {"text": exc.message, "error": exc.code}

    app = server.streamable_http_app(
        streamable_http_path="/",
        json_response=True,
        stateless_http=True,
        transport_security=_security(),
    )
    return server, app


def chat_handle(principal):
    from app.services.workspace import GraphHandle

    box, _principal = _pair()
    return GraphHandle(box.graph, principal.graph_name, "write")
