"""Student workspace routes. A supervisor can open progress and nothing else here."""

import json

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import StreamingResponse

from app.api.deps import container, current_principal, limited
from app.core import BadRequest, Container, NotFound
from app.constants import CHAT, READ, WRITE
from app.models.schemas import (
    AgentBody,
    ConversationBody,
    DecisionBody,
    EvidenceBody,
    GapBody,
    HandoffBody,
    JobBody,
    MemoryBody,
    NoteBody,
    ReadBody,
    TransitionBody,
    TurnBody,
)
from app.agents.adversary import review_text_gap
from app.models.queries import Q
from app.services.chat import ChatService
from app.services.intent import word_count
from app.utilities.security import Principal

router = APIRouter()


async def _self(student_id: str, principal: Principal, store: Container):
    return await store.workspace.open(principal, student_id, "self")


async def _ready(student_id: str, principal: Principal, store: Container):
    handle = await _self(student_id, principal, store)
    await store.graph.ensure_workspace(handle.name)
    return handle


@router.get("/students/{student_id}/progress")
async def progress(
    student_id: str,
    principal: Principal = Depends(limited(READ)),
    store: Container = Depends(container),
):
    handle = await store.workspace.open(principal, student_id, "progress")
    return await store.workspace.progress(handle)


@router.get("/students/{student_id}/timeline")
async def timeline(
    student_id: str,
    principal: Principal = Depends(limited(READ)),
    store: Container = Depends(container),
):
    handle = await _self(student_id, principal, store)
    body = await store.workspace.progress(handle)
    return {"items": body["timeline"]}


@router.get("/students/{student_id}/brief")
async def brief(
    student_id: str,
    principal: Principal = Depends(limited(READ)),
    store: Container = Depends(container),
):
    handle = await _self(student_id, principal, store)
    snapshot = await store.workspace.progress(handle)
    return await store.memory.brief(handle, snapshot)


@router.get("/students/{student_id}/reading")
async def reading(
    student_id: str,
    principal: Principal = Depends(limited(READ)),
    store: Container = Depends(container),
):
    handle = await _self(student_id, principal, store)
    body = await store.workspace.progress(handle)
    return body["reading"]


@router.get("/students/{student_id}/gaps")
async def gaps(
    student_id: str,
    principal: Principal = Depends(limited(READ)),
    store: Container = Depends(container),
):
    handle = await _self(student_id, principal, store)
    return await store.memory.gaps(handle)


@router.post("/students/{student_id}/reads")
async def record_read(
    student_id: str,
    body: ReadBody,
    principal: Principal = Depends(limited(WRITE)),
    store: Container = Depends(container),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    handle = await _self(student_id, principal, store)
    return await store.memory.read(handle, body.paper_id.strip(), body.depth, body.note.strip(), idempotency_key or "")


@router.post("/students/{student_id}/notes")
async def record_note(
    student_id: str,
    body: NoteBody,
    principal: Principal = Depends(limited(WRITE)),
    store: Container = Depends(container),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    handle = await _self(student_id, principal, store)
    return await store.memory.note(handle, body.text.strip(), idempotency_key or "")


@router.post("/students/{student_id}/decisions")
async def record_decision(
    student_id: str,
    body: DecisionBody,
    principal: Principal = Depends(limited(WRITE)),
    store: Container = Depends(container),
):
    handle = await _self(student_id, principal, store)
    return await store.memory.decide(handle, body.kind.strip(), body.reason.strip(), body.gap_id.strip())


@router.post("/students/{student_id}/gaps")
async def open_gap(
    student_id: str,
    body: GapBody,
    principal: Principal = Depends(limited(WRITE)),
    store: Container = Depends(container),
):
    handle = await _ready(student_id, principal, store)
    created = await store.memory.open_gap(handle, body.text.strip(), body.task_id.strip())
    try:
        ctx = ChatService(store)._ctx(principal)
        reviewed = await review_text_gap(ctx, created["id"])
    except Exception:
        return created
    return {**created, "status": reviewed["status"], "review": reviewed["summary"]}


@router.get("/students/{student_id}/gaps/{gap_id}")
async def gap(
    student_id: str,
    gap_id: str,
    principal: Principal = Depends(limited(READ)),
    store: Container = Depends(container),
):
    handle = await _ready(student_id, principal, store)
    return await store.gaps.get(handle, gap_id)


@router.post("/students/{student_id}/gaps/{gap_id}/transition")
async def transition_gap(
    student_id: str,
    gap_id: str,
    body: TransitionBody,
    principal: Principal = Depends(limited(WRITE)),
    store: Container = Depends(container),
):
    handle = await _ready(student_id, principal, store)
    return await store.gaps.transition(handle, gap_id, body.to, body.version)


@router.post("/students/{student_id}/gaps/{gap_id}/challenge", status_code=202)
async def challenge_gap(
    student_id: str,
    gap_id: str,
    principal: Principal = Depends(limited(WRITE)),
    store: Container = Depends(container),
):
    handle = await _ready(student_id, principal, store)
    rows = await handle.query(Q.GAP_SIGNAL, {"id": gap_id})
    if rows and not rows[0][4]:
        reviewed = await review_text_gap(ChatService(store)._ctx(principal), gap_id)
        return {"handoff": None, "job_id": "", "status": reviewed["status"], "review": reviewed["summary"]}
    created = await store.gaps.open_handoff(handle, gap_id, "adversary", "student")
    job = await store.queue.enqueue(handle.name, "challenge_gap", {"gap_id": gap_id, "handoff_id": created["id"]})
    return {"handoff": created, "job_id": job["id"]}


@router.post("/students/{student_id}/gaps/{gap_id}/evidence")
async def add_evidence(
    student_id: str,
    gap_id: str,
    body: EvidenceBody,
    principal: Principal = Depends(limited(WRITE)),
    store: Container = Depends(container),
):
    handle = await _ready(student_id, principal, store)
    recorded = await store.gaps.add_evidence(handle, gap_id, body.ref_id.strip(), body.kind)
    for handoff_id in recorded["reopened"]:
        await store.queue.enqueue(handle.name, "resolve_handoff", {"handoff_id": handoff_id})
    return recorded


@router.get("/students/{student_id}/handoffs")
async def handoffs(
    student_id: str,
    principal: Principal = Depends(limited(READ)),
    store: Container = Depends(container),
):
    handle = await _ready(student_id, principal, store)
    return await store.gaps.list_handoffs(handle)


@router.post("/students/{student_id}/handoffs", status_code=202)
async def open_handoff(
    student_id: str,
    body: HandoffBody,
    principal: Principal = Depends(limited(WRITE)),
    store: Container = Depends(container),
):
    handle = await _ready(student_id, principal, store)
    created = await store.gaps.open_handoff(handle, body.gap_id.strip(), body.to_agent, body.from_agent.strip())
    job = await store.queue.enqueue(handle.name, "resolve_handoff", {"handoff_id": created["id"]})
    return {"handoff": created, "job_id": job["id"]}


@router.get("/students/{student_id}/jobs")
async def jobs(
    student_id: str,
    principal: Principal = Depends(limited(READ)),
    store: Container = Depends(container),
):
    handle = await _ready(student_id, principal, store)
    return await store.queue.list_jobs(handle.name)


@router.get("/students/{student_id}/jobs/{job_id}")
async def job(
    student_id: str,
    job_id: str,
    principal: Principal = Depends(limited(READ)),
    store: Container = Depends(container),
):
    handle = await _ready(student_id, principal, store)
    return await store.queue.get(handle.name, job_id)


@router.post("/students/{student_id}/jobs", status_code=202)
async def enqueue_job(
    student_id: str,
    body: JobBody,
    principal: Principal = Depends(limited(WRITE)),
    store: Container = Depends(container),
):
    handle = await _ready(student_id, principal, store)
    return await store.queue.enqueue(handle.name, body.type, body.payload)


@router.get("/students/{student_id}/memory")
async def recall(
    student_id: str,
    q: str = "",
    limit: int = Query(10, ge=1, le=20),
    principal: Principal = Depends(limited(READ)),
    store: Container = Depends(container),
):
    handle = await _self(student_id, principal, store)
    return await store.memory.recall(handle, q, limit)


@router.get("/students/{student_id}/memory/as-of")
async def memory_as_of(
    student_id: str,
    at: str,
    principal: Principal = Depends(limited(READ)),
    store: Container = Depends(container),
):
    handle = await _self(student_id, principal, store)
    return await store.memory.as_of(handle, at)


@router.post("/students/{student_id}/memory")
async def remember(
    student_id: str,
    body: MemoryBody,
    principal: Principal = Depends(limited(WRITE)),
    store: Container = Depends(container),
):
    handle = await _self(student_id, principal, store)
    return await store.memory.remember(handle, body.kind, body.text.strip(), body.entity.strip())


@router.delete("/students/{student_id}/memory/{memory_id}")
async def forget(
    student_id: str,
    memory_id: str,
    principal: Principal = Depends(limited(WRITE)),
    store: Container = Depends(container),
):
    handle = await _self(student_id, principal, store)
    return await store.memory.forget(handle, memory_id)


@router.get("/students/{student_id}/conversations")
async def conversations(
    student_id: str,
    principal: Principal = Depends(limited(READ)),
    store: Container = Depends(container),
):
    handle = await _self(student_id, principal, store)
    return await store.memory.conversations(handle)


@router.post("/students/{student_id}/conversations")
async def open_conversation(
    student_id: str,
    body: ConversationBody,
    principal: Principal = Depends(limited(WRITE)),
    store: Container = Depends(container),
):
    handle = await _self(student_id, principal, store)
    return await store.memory.open_conversation(handle, body.title.strip() or "Conversation")


@router.get("/students/{student_id}/conversations/{conversation_id}")
async def conversation(
    student_id: str,
    conversation_id: str,
    principal: Principal = Depends(limited(READ)),
    store: Container = Depends(container),
):
    handle = await _self(student_id, principal, store)
    return await store.memory.conversation(handle, conversation_id)


@router.delete("/students/{student_id}/conversations/{conversation_id}")
async def delete_conversation(
    student_id: str,
    conversation_id: str,
    principal: Principal = Depends(limited(WRITE)),
    store: Container = Depends(container),
):
    handle = await _self(student_id, principal, store)
    return await store.memory.delete_conversation(handle, conversation_id)


@router.post("/students/{student_id}/conversations/{conversation_id}/turns")
async def add_turn(
    student_id: str,
    conversation_id: str,
    body: TurnBody,
    principal: Principal = Depends(limited(WRITE)),
    store: Container = Depends(container),
):
    handle = await _self(student_id, principal, store)
    return await store.memory.add_turn(handle, conversation_id, body.text.strip())


@router.post("/agents/{name}")
async def run_agent(
    name: str,
    body: AgentBody,
    principal: Principal = Depends(limited(WRITE)),
    store: Container = Depends(container),
):
    if principal.signup_role != "student":
        raise NotFound("not found")
    if name not in {"cartographer", "reader", "evidence", "scoper"}:
        raise BadRequest("unknown agent")
    handle = await _ready(principal.user_id, principal, store)
    del handle
    return await ChatService(store).run_agent(
        principal,
        name,
        body.model_dump(),
    )


@router.post("/chat")
async def chat(
    request: Request,
    principal: Principal = Depends(current_principal),
    store: Container = Depends(container),
):
    if principal.signup_role != "student":
        raise NotFound("not found")
    await store.limiter.allow(request, principal, CHAT, llm=True)
    message, conversation_id = await _chat_body(request, store.settings.chat_max_words)
    return StreamingResponse(
        ChatService(store).stream(principal, message, conversation_id),
        media_type="text/event-stream",
    )


async def _chat_body(request: Request, max_words: int) -> tuple[str, str]:
    raw = await request.body()
    if not raw:
        raise BadRequest("message is required")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise BadRequest("message is required") from exc
    if not isinstance(payload, dict):
        raise BadRequest("message is required")
    message = str(payload.get("message") or "").strip()
    if not message:
        raise BadRequest("message is required")
    if word_count(message) > max_words:
        raise BadRequest(f"A message can be at most {max_words} words.")
    return message, str(payload.get("conversation_id") or "")
