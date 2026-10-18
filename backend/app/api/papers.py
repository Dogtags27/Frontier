"""Corpus search and the paper reads a search hit opens."""

from fastapi import APIRouter, Depends, Query, Response

from app.api.deps import container, limited
from app.core import Container
from app.constants import READ
from app.models.schemas import SearchQuery
from app.utilities.security import Principal

router = APIRouter()


def search_query(
    q: str = "",
    mode: str = Query("hybrid", pattern="^(semantic|metadata|hybrid)$"),
    year_from: int | None = None,
    year_to: int | None = None,
    category: str = "",
    layer: str = "",
    paper_kind: str = "",
    task: str = "",
    method: str = "",
    dataset: str = "",
    metric: str = "",
    cites: str = "",
    cited_by: str = "",
    unread_only: bool = False,
    limit: int = Query(10, ge=1, le=20),
    cursor: int = Query(0, ge=0),
    sort: str = Query("relevance", pattern="^(relevance|year_desc|year_asc|title|citations)$"),
) -> SearchQuery:
    return SearchQuery(
        q=q,
        mode=mode,  # type: ignore[arg-type]
        year_from=year_from,
        year_to=year_to,
        category=category,
        layer=layer,
        paper_kind=paper_kind,
        task=task,
        method=method,
        dataset=dataset,
        metric=metric,
        cites=cites,
        cited_by=cited_by,
        unread_only=unread_only,
        limit=limit,
        cursor=cursor,
        sort=sort,  # type: ignore[arg-type]
    )


@router.get("/papers/search")
async def search_papers(
    request: SearchQuery = Depends(search_query),
    principal: Principal = Depends(limited(READ)),
    store: Container = Depends(container),
):
    return await store.search.search(principal, request)


@router.get("/vocab/suggest")
async def suggest(
    kind: str,
    q: str = "",
    limit: int = Query(8, ge=1, le=20),
    principal: Principal = Depends(limited(READ)),
    store: Container = Depends(container),
):
    return await store.search.suggest(kind, q, limit)


@router.get("/papers/{arxiv_id}")
async def paper(
    arxiv_id: str,
    principal: Principal = Depends(limited(READ)),
    store: Container = Depends(container),
):
    return await store.papers.get(arxiv_id)


@router.get("/papers/{arxiv_id}/facets")
async def facets(
    arxiv_id: str,
    principal: Principal = Depends(limited(READ)),
    store: Container = Depends(container),
):
    return await store.papers.facets(arxiv_id)


@router.get("/papers/{arxiv_id}/sentences")
async def sentences(
    arxiv_id: str,
    n: int | None = None,
    limit: int = Query(10, ge=1, le=80),
    offset: int = Query(0, ge=0),
    principal: Principal = Depends(limited(READ)),
    store: Container = Depends(container),
):
    return await store.papers.sentences(arxiv_id, n, limit, offset)


@router.get("/papers/{arxiv_id}/neighbors")
async def neighbors(
    arxiv_id: str,
    principal: Principal = Depends(limited(READ)),
    store: Container = Depends(container),
):
    return await store.papers.neighbors(arxiv_id)


@router.get("/papers/{arxiv_id}/pdf")
async def pdf(
    arxiv_id: str,
    principal: Principal = Depends(limited(READ)),
    store: Container = Depends(container),
):
    return await store.papers.pdf(arxiv_id)


@router.get("/papers/{arxiv_id}/article")
async def article(
    arxiv_id: str,
    principal: Principal = Depends(limited(READ)),
    store: Container = Depends(container),
):
    return await store.papers.article(arxiv_id)


@router.get("/papers/{arxiv_id}/pdf/file")
async def pdf_file(
    arxiv_id: str,
    principal: Principal = Depends(limited(READ)),
    store: Container = Depends(container),
):
    body = await store.papers.pdf_bytes(arxiv_id)
    return Response(
        content=body,
        media_type="application/pdf",
        headers={"Cache-Control": "private, max-age=600", "Content-Disposition": f'inline; filename="{arxiv_id.replace("/", "_")}.pdf"'},
    )


@router.get("/papers/{arxiv_id}/claims")
async def claims(
    arxiv_id: str,
    principal: Principal = Depends(limited(READ)),
    store: Container = Depends(container),
):
    return await store.papers.claims(arxiv_id)


@router.get("/papers/{arxiv_id}/provenance")
async def provenance(
    arxiv_id: str,
    principal: Principal = Depends(limited(READ)),
    store: Container = Depends(container),
):
    return await store.papers.provenance(arxiv_id)
