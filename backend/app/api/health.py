"""Liveness and readiness. Readiness is the store-count check."""

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.api.deps import container
from app.core import Container
from app.ready import ReadyService
from app.models.schemas import CheckBody, ReadyBody

router = APIRouter()


@router.get("/healthz")
async def healthz():
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(store: Container = Depends(container)):
    ok, checks = await ReadyService(store).report()
    body = ReadyBody(
        status="ready" if ok else "not_ready",
        checks=[CheckBody(**item.as_dict()) for item in checks],
    )
    return JSONResponse(status_code=200 if ok else 503, content=body.model_dump())
