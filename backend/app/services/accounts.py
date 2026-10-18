"""Accounts, organisations, and class codes."""

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from psycopg.errors import UniqueViolation

from app.constants import Settings, normalize_email
from app.core import Conflict, Forbidden, NotFound
from app.models.queries import SQL
from app.utilities.security import Identity, Principal

INVITE_DAYS = 14
INVITE_MAX_USES = 200


def code_hash(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


class AccountService:
    """Profiles live here. Passwords and refresh tokens stay in Supabase."""

    def __init__(self, pg, settings: Settings, workspace, orgs: "OrgService"):
        self.pg = pg
        self.settings = settings
        self.workspace = workspace
        self.orgs = orgs

    async def principal_for(self, identity: Identity) -> Principal:
        row = await self._row(identity.user_id)
        if row is None:
            return Principal(
                identity.user_id,
                identity.email,
                identity.email_verified,
                "",
                "",
                None,
                False,
                None,
                None,
            )
        user = await self.reconcile_admin(self.user_from(row))
        if user["graph_status"] != "ready":
            await self.workspace.ensure(user["id"], user["display_name"])
            if user["signup_role"] == "supervisor" and not user["org_id"]:
                await self.ensure_org(user["id"], user["display_name"])
            user = self.user_from(await self._row(user["id"]))
            user = await self.reconcile_admin(user)
        return Principal(
            user["id"],
            user["email"],
            identity.email_verified,
            user["role"],
            user["signup_role"],
            user["org_id"],
            user["disabled"],
            user["graph_name"],
            user["graph_status"],
        )

    async def bootstrap(self, identity: Identity, signup_role: str, display_name: str) -> dict:
        existing = await self._row(identity.user_id)
        if existing is not None and existing[8]:
            raise Forbidden("account is disabled")
        if existing is None:
            try:
                await self.pg.execute(
                    SQL.INSERT_USER,
                    (identity.user_id, identity.email, signup_role, signup_role, display_name[:80]),
                )
            except UniqueViolation as exc:
                raise Conflict("an account with this email already exists") from exc
        else:
            signup_role = existing[2]
            display_name = existing[4]
        user = self.user_from(await self._row(identity.user_id))
        if user["graph_status"] != "ready":
            await self.workspace.ensure(user["id"], display_name or identity.email)
        if user["signup_role"] == "supervisor":
            await self.ensure_org(user["id"], display_name or identity.email)
        user = await self.reconcile_admin(self.user_from(await self._row(identity.user_id)))
        return self._public(user)

    async def ensure_org(self, user_id: str, display_name: str) -> dict | None:
        found = await self.pg.fetch(SQL.ORG_FOR_OWNER, (user_id,))
        if found:
            return await self.orgs.current_invite(str(found[0][0]), user_id)
        org_id = str(uuid.uuid4())
        name = f"{display_name or 'Instructor'}'s Team"
        await self.pg.execute(SQL.INSERT_ORG, (org_id, name[:80], user_id))
        await self.pg.execute(SQL.SET_ORG, (org_id, user_id))
        return await self.orgs.rotate(org_id, user_id)

    async def reconcile_admin(self, user: dict) -> dict:
        """Promote while the email is on the allow-list, and restore the signup role when it is not."""
        listed = normalize_email(user["email"]) in self.settings.admin_email_set
        if listed and user["role"] != "admin":
            await self.pg.execute(SQL.SET_ROLE, ("admin", user["id"]))
        elif not listed and user["role"] == "admin":
            await self.pg.execute(SQL.SET_ROLE, (user["signup_role"], user["id"]))
        else:
            return user
        return self.user_from(await self._row(user["id"]))

    async def _row(self, user_id: str):
        rows = await self.pg.fetch(SQL.USER_BY_ID, (user_id,))
        return rows[0] if rows else None

    def user_from(self, row) -> dict:
        return {
            "id": str(row[0]),
            "email": row[1],
            "signup_role": row[2],
            "role": row[3],
            "display_name": row[4],
            "org_id": str(row[5]) if row[5] else None,
            "graph_name": row[6],
            "graph_status": row[7],
            "disabled": bool(row[8]),
        }

    def _public(self, user: dict) -> dict:
        return {
            "id": user["id"],
            "email": user["email"],
            "role": user["role"],
            "signup_role": user["signup_role"],
            "display_name": user["display_name"],
            "org_id": user["org_id"],
            "graph_status": user["graph_status"],
        }


class OrgService:
    """One live class code per organisation. Join checks the hash."""

    def __init__(self, pg):
        self.pg = pg

    async def rotate(self, org_id: str, owner_id: str) -> dict:
        code = secrets.token_urlsafe(9)
        invite_id = str(uuid.uuid4())
        expires = datetime.now(timezone.utc) + timedelta(days=INVITE_DAYS)

        def write(conn):
            with conn.cursor() as cur:
                cur.execute(SQL.REVOKE_LIVE_INVITES, (org_id,))
                cur.execute(
                    SQL.INSERT_INVITE,
                    (invite_id, code_hash(code), code, org_id, owner_id, expires, INVITE_MAX_USES),
                )

        await self.pg.transaction(write)
        return _invite(code, expires, INVITE_MAX_USES, 0)

    async def current_invite(self, org_id: str, owner_id: str) -> dict:
        org = await self._owned(org_id, owner_id)
        rows = await self.pg.fetch(SQL.LIVE_INVITE, (org[0],))
        if not rows:
            return await self.rotate(org_id, owner_id)
        row = rows[0]
        return _invite(row[1], row[2], row[3], row[4])

    async def join(self, student: Principal, code: str) -> dict:
        if student.signup_role != "student":
            raise NotFound("not found")
        digest = code_hash(code.strip())

        def write(conn):
            with conn.cursor() as cur:
                cur.execute(SQL.PICK_INVITE, (digest,))
                picked = cur.fetchone()
                if picked is None:
                    return None
                org_id, owner_id, _used, _max_uses = picked
                if str(owner_id) == student.user_id:
                    return None
                cur.execute(SQL.ENROLL, (str(owner_id), student.user_id, str(org_id)))
                cur.execute(SQL.BUMP_INVITE, (digest,))
                cur.execute(SQL.SET_ORG, (str(org_id), student.user_id))
                return {"org_id": str(org_id), "supervisor_id": str(owner_id)}

        result = await self.pg.transaction(write)
        if result is None:
            raise NotFound("not found")
        org = await self.pg.fetch(SQL.ORG_BY_ID, (result["org_id"],))
        result["name"] = org[0][1] if org else ""
        return result

    async def mine(self, student_id: str) -> list[dict]:
        rows = await self.pg.fetch(SQL.MY_ORGS, (student_id,))
        return [
            {
                "id": str(row[0]),
                "name": row[1],
                "supervisor": row[2],
                "joined_at": row[3].isoformat() if hasattr(row[3], "isoformat") else str(row[3]),
                "members": int(row[4]),
            }
            for row in rows
        ]

    async def leave(self, student_id: str, org_id: str) -> None:
        try:
            uuid.UUID(org_id)
        except ValueError as exc:
            raise NotFound("not found") from exc
        await self.pg.execute(SQL.LEAVE_ORG, (org_id, student_id))
        await self.pg.execute(SQL.RESET_ORG, (student_id, student_id))

    async def info(self, org_id: str, owner_id: str) -> dict:
        org = await self._owned(org_id, owner_id)
        count = await self.pg.fetch(SQL.ORG_MEMBER_COUNT, (org_id,))
        return {"id": str(org[0]), "name": org[1], "members": int(count[0][0]) if count else 0}

    async def rename(self, org_id: str, owner_id: str, name: str) -> dict:
        await self._owned(org_id, owner_id)
        clean = " ".join(name.split())[:60]
        if not clean:
            raise Conflict("the team needs a name")
        await self.pg.execute(SQL.RENAME_ORG, (clean, org_id))
        return await self.info(org_id, owner_id)

    async def students(self, org_id: str, owner_id: str) -> list[dict]:
        await self._owned(org_id, owner_id)
        rows = await self.pg.fetch(SQL.ORG_STUDENTS, (org_id, owner_id))
        return [{"id": str(row[0]), "display_name": row[1]} for row in rows]

    async def remove_student(self, org_id: str, owner_id: str, student_id: str) -> None:
        await self._owned(org_id, owner_id)
        await self.pg.execute(SQL.REMOVE_ENROLLMENT, (owner_id, student_id))
        await self.pg.execute(SQL.RESET_ORG, (student_id, student_id))

    async def _owned(self, org_id: str, owner_id: str):
        rows = await self.pg.fetch(SQL.ORG_BY_ID, (org_id,))
        if not rows or str(rows[0][2]) != owner_id:
            raise NotFound("not found")
        return rows[0]


def _invite(code: str, expires, max_uses: int, used: int) -> dict:
    expires_at = expires.isoformat() if hasattr(expires, "isoformat") else str(expires)
    return {
        "code": code,
        "join_path": f"/join/{code}",
        "expires_at": expires_at,
        "max_uses": max_uses,
        "used": used,
    }
