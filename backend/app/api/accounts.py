"""Profile, class code, and join routes."""

from fastapi import APIRouter, Depends

from app.api.deps import auth_identity, container, limited
from app.core import Container
from app.constants import READ, WRITE
from app.models.schemas import BootstrapBody, JoinBody
from app.utilities.security import Identity, Principal

router = APIRouter()


@router.post("/me/bootstrap")
async def bootstrap(
    body: BootstrapBody,
    who: Identity = Depends(auth_identity),
    store: Container = Depends(container),
):
    name = body.display_name.strip() or who.email.split("@", 1)[0]
    return await store.accounts.bootstrap(who, body.role, name)


@router.get("/me")
async def me(principal: Principal = Depends(limited(READ)), store: Container = Depends(container)):
    user = store.accounts.user_from(await store.accounts._row(principal.user_id))
    return store.accounts._public(user)


@router.get("/me/profile")
async def profile(principal: Principal = Depends(limited(READ)), store: Container = Depends(container)):
    handle = await store.workspace.open(principal, "me", "self")
    await store.graph.ensure_workspace(handle.name)
    return await store.workspace.profile(handle)


@router.post("/orgs/join")
async def join(
    body: JoinBody,
    principal: Principal = Depends(limited(WRITE)),
    store: Container = Depends(container),
):
    return await store.orgs.join(principal, body.code)


@router.post("/orgs/{org_id}/invites")
async def rotate_invite(
    org_id: str,
    principal: Principal = Depends(limited(WRITE)),
    store: Container = Depends(container),
):
    await store.orgs._owned(org_id, principal.user_id)
    return await store.orgs.rotate(org_id, principal.user_id)


@router.get("/orgs/{org_id}/invite")
async def current_invite(
    org_id: str,
    principal: Principal = Depends(limited(READ)),
    store: Container = Depends(container),
):
    return await store.orgs.current_invite(org_id, principal.user_id)


@router.get("/orgs/{org_id}/students")
async def students(
    org_id: str,
    principal: Principal = Depends(limited(READ)),
    store: Container = Depends(container),
):
    return await store.orgs.students(org_id, principal.user_id)


@router.delete("/orgs/{org_id}/students/{student_id}")
async def remove_student(
    org_id: str,
    student_id: str,
    principal: Principal = Depends(limited(WRITE)),
    store: Container = Depends(container),
):
    await store.orgs.remove_student(org_id, principal.user_id, student_id)
    return {"removed": student_id}
