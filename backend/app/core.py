"""Shared types: errors, the dependency container, and ids."""

from dataclasses import dataclass

from app.constants import Settings, get_settings


class AppError(Exception):
    """Base error mapped to one HTTP response by the app handler."""

    status = 500
    code = "error"

    def __init__(self, message: str, detail: str | None = None):
        self.message = message
        self.detail = detail
        super().__init__(message)


class NotFound(AppError):
    status = 404
    code = "not_found"


class BadRequest(AppError):
    status = 400
    code = "bad_request"


class Unauthorized(AppError):
    status = 401
    code = "unauthorized"


class Forbidden(AppError):
    status = 403
    code = "forbidden"


class Conflict(AppError):
    status = 409
    code = "conflict"


class RateLimited(AppError):
    status = 429
    code = "rate_limited"

    def __init__(self, message: str, detail: str | None = None, retry_after: int = 1):
        super().__init__(message, detail)
        self.retry_after = max(1, int(retry_after))


class Upstream(AppError):
    status = 502
    code = "upstream"


@dataclass
class Container:
    """Holds the process-wide stores. Built once in the app lifespan."""

    settings: Settings
    graph: object
    pg: object
    blob: object
    verifier: object
    accounts: object
    orgs: object
    workspace: object
    limiter: object
    llm: object
    papers: object
    search: object
    memory: object
    queue: object
    gaps: object
    ingest: object

    @classmethod
    def build(
        cls,
        settings: Settings | None = None,
        verifier: object | None = None,
        transport: object | None = None,
    ) -> "Container":
        from app.constants import Budget, RateLimiter
        from app.utilities.llm import LLM
        from app.utilities.security import SupabaseTokenVerifier
        from app.services.accounts import AccountService, OrgService
        from app.services.gaps import GapService
        from app.services.ingest import IngestService
        from app.services.memory import MemoryService
        from app.services.papers import PaperService
        from app.services.queue import WorkQueue
        from app.services.search import SearchService
        from app.services.workspace import WorkspaceResolver
        from app.utilities.stores import Blob, GraphStore, Pg

        settings = settings or get_settings()
        graph = GraphStore(settings)
        pg = Pg(settings)
        blob = Blob(settings)
        workspace = WorkspaceResolver(graph, pg)
        orgs = OrgService(pg)
        budget = Budget(pg, settings)
        llm = LLM(settings, pg, budget, transport)
        queue = WorkQueue(graph, pg, settings)
        gaps = GapService(graph, pg)
        ingest = IngestService(graph, pg, queue, gaps, settings)
        return cls(
            settings=settings,
            graph=graph,
            pg=pg,
            blob=blob,
            verifier=verifier or SupabaseTokenVerifier.from_settings(settings),
            accounts=AccountService(pg, settings, workspace, orgs),
            orgs=orgs,
            workspace=workspace,
            limiter=RateLimiter(settings, pg, graph, budget),
            llm=llm,
            papers=PaperService(graph, pg, blob, settings),
            search=SearchService(graph, pg, llm, settings),
            memory=MemoryService(graph),
            queue=queue,
            gaps=gaps,
            ingest=ingest,
        )

    async def open(self) -> None:
        from app.models.migrate import apply

        await self.pg.open()
        if not self.pg.error:
            await apply(self.pg)
            await self.workspace.resume_pending(self.accounts)
        await self.limiter.open()

    async def close(self) -> None:
        await self.pg.close()
        await self.graph.close()
