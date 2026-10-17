"""Request dependencies."""

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core import Container, Forbidden, Unauthorized
from app.constants import READ
from app.utilities.security import Identity, Principal, require_admin

bearer = HTTPBearer(auto_error=False)


def container(request: Request) -> Container:
    return request.app.state.container


def identity(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    store: Container = Depends(container),
) -> Identity:
    if credentials is None:
        raise Unauthorized("missing token")
    return store.verifier.verify(credentials.credentials)


async def current_principal(
    who: Identity = Depends(identity),
    store: Container = Depends(container),
) -> Principal:
    principal = await store.accounts.principal_for(who)
    if principal.disabled:
        raise Forbidden("account is disabled")
    if not principal.ready:
        raise Forbidden("account is not set up")
    return principal


def admin_principal(
    principal: Principal = Depends(current_principal),
    store: Container = Depends(container),
) -> Principal:
    require_admin(principal, store.settings)
    return principal


def limited(cost: int = READ):
    """Spend this route's cost from the caller's buckets."""

    async def dependency(
        request: Request,
        principal: Principal = Depends(current_principal),
        store: Container = Depends(container),
    ) -> Principal:
        await store.limiter.allow(request, principal, cost)
        return principal

    return dependency


async def auth_identity(
    request: Request,
    who: Identity = Depends(identity),
    store: Container = Depends(container),
) -> Identity:
    """Stricter bucket for signup, keyed by address and email."""
    await store.limiter.allow_auth(request, who.email)
    return who
