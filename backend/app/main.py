"""FastAPI app. Stores are opened for the process lifetime."""

from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.accounts import router as accounts_router
from app.api.admin import router as admin_router
from app.api.health import router as health_router
from app.api.mcp_server import build_server
from app.api.papers import router as papers_router
from app.api.students import router as students_router
from app.constants import DISCOVERY
from app.core import AppError, Container, RateLimited

log = structlog.get_logger()


def configure_logging() -> None:
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),
        ],
    )


def create_app(settings=None, verifier=None, transport=None) -> FastAPI:
    configure_logging()
    from app.constants import get_settings

    configured = settings or get_settings()
    mcp_server, mcp_app = build_server()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        box = Container.build(configured, verifier, transport)
        await box.open()
        app.state.container = box
        log.info("stores open", corpus=box.settings.corpus_graph, rate_backend=box.limiter.backend)
        async with mcp_server.session_manager.run():
            yield
        await box.close()

    app = FastAPI(title="Frontier", lifespan=lifespan)
    app.mount("/mcp", mcp_app)
    app.include_router(health_router)
    app.include_router(accounts_router)
    app.include_router(students_router)
    app.include_router(papers_router)
    app.include_router(admin_router)

    @app.middleware("http")
    async def mcp_gate(request, call_next):
        if request.url.path != "/mcp" and not request.url.path.startswith("/mcp/"):
            return await call_next(request)
        from app.api.mcp_server import caller

        header = request.headers.get("authorization") or ""
        if not header.lower().startswith("bearer "):
            return JSONResponse(
                status_code=401,
                content={"code": "unauthorized", "message": "missing token", "detail": None},
            )
        box = request.app.state.container
        try:
            who = box.verifier.verify(header.split(" ", 1)[1].strip())
            principal = await box.accounts.principal_for(who)
            if principal.disabled or not principal.ready or principal.signup_role != "student":
                return JSONResponse(
                    status_code=403,
                    content={"code": "forbidden", "message": "the research tools are for students", "detail": None},
                )
            await box.limiter.allow(request, principal, DISCOVERY)
        except RateLimited as exc:
            return JSONResponse(
                status_code=429,
                content={"code": exc.code, "message": exc.message, "detail": exc.detail},
                headers={"Retry-After": str(exc.retry_after)},
            )
        except AppError as exc:
            return JSONResponse(
                status_code=exc.status,
                content={"code": exc.code, "message": exc.message, "detail": exc.detail},
            )
        token = caller.set((box, principal))
        try:
            return await call_next(request)
        finally:
            caller.reset(token)

    @app.middleware("http")
    async def body_limit(request, call_next):
        raw = request.headers.get("content-length")
        if raw and raw.isdigit() and int(raw) > configured.max_body_bytes:
            return JSONResponse(
                status_code=413,
                content={"code": "payload_too_large", "message": "request body is too large", "detail": None},
            )
        return await call_next(request)

    origins = [item.strip() for item in configured.cors_origins.split(",") if item.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(AppError)
    async def on_app_error(_request, exc: AppError):
        headers = {}
        if exc.status == 429:
            headers["Retry-After"] = str(exc.retry_after)
        return JSONResponse(
            status_code=exc.status,
            content={"code": exc.code, "message": exc.message, "detail": exc.detail},
            headers=headers,
        )

    return app


app = create_app()
