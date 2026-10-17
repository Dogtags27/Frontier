"""Admin routes. Authorization is checked again here, not only at login."""

from fastapi import APIRouter, Depends, Request

from app.api.deps import admin_principal, container
from app.core import Container
from app.constants import READ, WRITE
from app.models.schemas import IngestBody
from app.services.ingest import _ids
from app.utilities.security import Principal

router = APIRouter()


@router.get("/admin/whoami")
async def whoami(
    request: Request,
    principal: Principal = Depends(admin_principal),
    store: Container = Depends(container),
):
    await store.limiter.allow(request, principal, READ)
    return {"id": principal.user_id, "email": principal.email, "role": principal.role}


@router.get("/admin/queue")
async def queue(
    request: Request,
    principal: Principal = Depends(admin_principal),
    store: Container = Depends(container),
):
    await store.limiter.allow(request, principal, READ)
    return await store.queue.snapshot()


@router.post("/admin/papers", status_code=202)
async def papers(
    body: IngestBody,
    request: Request,
    principal: Principal = Depends(admin_principal),
    store: Container = Depends(container),
):
    await store.limiter.allow(request, principal, WRITE)
    ids = _ids(body.arxiv_ids)
    job = await store.queue.enqueue(store.settings.corpus_graph, "ingest_paper", {"arxiv_ids": ids})
    return {"job_id": job["id"], "papers": body.arxiv_ids}
