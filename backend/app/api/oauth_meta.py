"""OAuth discovery for MCP clients (RFC 9728).

A client that gets a 401 from /mcp/ reads the WWW-Authenticate header, fetches
this document, and learns that Supabase Auth is the authorization server.
Supabase issues the tokens; the existing verifier already accepts them.
"""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.api.deps import container
from app.core import Container

router = APIRouter()

MCP_PATH = "/mcp/"
META_PATH = "/.well-known/oauth-protected-resource"


def public_origin(request: Request, store: Container) -> str:
    """The https origin clients use. Behind the proxy the Host header is the public one."""
    if store.settings.public_url:
        return store.settings.public_url.rstrip("/")
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
    return f"{proto.split(',')[0].strip()}://{host.split(',')[0].strip()}"


def challenge(request: Request, store: Container) -> dict:
    """The WWW-Authenticate header that points an MCP client at the discovery document."""
    url = public_origin(request, store) + META_PATH + "/mcp"
    return {"WWW-Authenticate": f'Bearer resource_metadata="{url}"'}


def _document(request: Request, store: Container) -> JSONResponse:
    body = {
        "resource": public_origin(request, store) + MCP_PATH,
        "authorization_servers": [store.settings.jwt_issuer],
        "bearer_methods_supported": ["header"],
        "resource_name": "Frontier research tools",
    }
    return JSONResponse(body, headers={"Access-Control-Allow-Origin": "*", "Cache-Control": "public, max-age=300"})


@router.get(META_PATH)
async def protected_resource(request: Request, store: Container = Depends(container)):
    return _document(request, store)


@router.get(META_PATH + "/mcp")
async def protected_resource_for_mcp(request: Request, store: Container = Depends(container)):
    return _document(request, store)
