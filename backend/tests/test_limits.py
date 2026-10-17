"""Rate limits, route cost, and the LLM ledger."""

import uuid
from contextlib import contextmanager
from decimal import Decimal

import jwt
import psycopg
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient
from falkordb import FalkorDB
from pydantic import BaseModel
from redis.exceptions import ResponseError

from app.constants import get_settings
from app.core import RateLimited, Upstream
from app.utilities.llm import Completion
from app.main import create_app
from app.models.queries import SQL
from app.utilities.security import Principal, SupabaseTokenVerifier
from app.services.workspace import graph_name_for

ISSUER = "https://b2.test/auth/v1"
AUDIENCE = "authenticated"
PRIVATE = ec.generate_private_key(ec.SECP256R1())
PUBLIC = PRIVATE.public_key()


def token(user_id: str, email: str) -> str:
    import time

    now = int(time.time())
    claims = {
        "sub": user_id,
        "email": email,
        "aud": AUDIENCE,
        "iss": ISSUER,
        "exp": now + 600,
        "email_verified": True,
    }
    return jwt.encode(claims, PRIVATE, algorithm="ES256", headers={"kid": "b2"})


def auth(user_id: str, email: str) -> dict:
    return {"Authorization": f"Bearer {token(user_id, email)}"}


def new_id() -> str:
    return str(uuid.uuid4())


def limits(**updates):
    base = {
        "admin_emails": "admin@b2.test",
        "rate_backend": "memory",
        "rate_refill_per_sec": 0,
        "rate_auth_refill_per_sec": 0,
        "rate_capacity_student": 30,
        "rate_ip_capacity": 1000,
        "rate_auth_capacity": 20,
        "rate_window_sec": 60,
        "daily_tokens_student": 100_000,
        "daily_usd_student": 100,
        "daily_usd_org": 100,
        "monthly_usd": 10_000,
        "max_body_bytes": 1_048_576,
    }
    base.update(updates)
    return get_settings().model_copy(update=base)


@contextmanager
def session(**updates):
    settings = limits(**updates)
    verifier = SupabaseTokenVerifier(ISSUER, AUDIENCE, keys={"b2": PUBLIC})
    app = create_app(settings, verifier)
    with TestClient(app) as client:
        yield client
    cleanup()


def cleanup() -> None:
    settings = get_settings()
    with psycopg.connect(settings.postgres_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id::text FROM users WHERE email LIKE %s", ("%b2.test",))
            ids = [row[0] for row in cur.fetchall()]
            if ids:
                cur.execute(SQL.DELETE_USAGE_USERS, (ids,))
                cur.execute(
                    "DELETE FROM enrollments WHERE student_id::text = ANY(%s) OR supervisor_id::text = ANY(%s)",
                    (ids, ids),
                )
                cur.execute("DELETE FROM invites WHERE created_by::text = ANY(%s)", (ids,))
                cur.execute("DELETE FROM orgs WHERE owner_supervisor_id::text = ANY(%s)", (ids,))
                cur.execute("DELETE FROM users WHERE id::text = ANY(%s)", (ids,))
    if not ids:
        return
    db = FalkorDB(host=settings.falkordb_host, port=settings.falkordb_port, password=settings.falkordb_password or None)
    for user_id in ids:
        graph = db.select_graph(graph_name_for(user_id))
        try:
            graph.delete()
        except ResponseError:
            pass


def bootstrap(client, email: str, role: str = "student"):
    user_id = new_id()
    response = client.post(
        "/me/bootstrap",
        json={"role": role, "display_name": email.split("@")[0]},
        headers=auth(user_id, email),
    )
    assert response.status_code == 200, response.text
    return user_id, response.json()


def test_burst_returns_429_with_retry_after():
    with session(rate_capacity_student=2) as client:
        user_id, _profile = bootstrap(client, "burst@b2.test")
        headers = auth(user_id, "burst@b2.test")
        assert client.get("/me", headers=headers).status_code == 200
        assert client.get("/me", headers=headers).status_code == 200
        blocked = client.get("/me", headers=headers)
        assert blocked.status_code == 429
        assert blocked.json()["detail"] == "user"
        assert int(blocked.headers["Retry-After"]) >= 1


def test_chat_cost_is_heavier_than_a_read():
    with session(rate_capacity_student=6) as client:
        user_id, _profile = bootstrap(client, "cost@b2.test")
        headers = auth(user_id, "cost@b2.test")
        assert client.get("/me", headers=headers).status_code == 200
        assert client.get("/me", headers=headers).status_code == 200
        blocked = client.post("/chat", headers=headers)
        assert blocked.status_code == 429
        assert blocked.json()["detail"] == "user"

        other, _profile = bootstrap(client, "room@b2.test")
        other_headers = auth(other, "room@b2.test")
        assert client.get("/me", headers=other_headers).status_code == 200
        allowed = client.post("/chat", headers=other_headers)
        assert allowed.status_code == 400
        assert allowed.json()["message"] == "message is required"


def test_auth_bucket_is_stricter():
    with session(rate_auth_capacity=2) as client:
        user_id = new_id()
        body = {"role": "student", "display_name": "auth"}
        headers = auth(user_id, "auth@b2.test")
        assert client.post("/me/bootstrap", json=body, headers=headers).status_code == 200
        assert client.post("/me/bootstrap", json=body, headers=headers).status_code == 200
        blocked = client.post("/me/bootstrap", json=body, headers=headers)
        assert blocked.status_code == 429
        assert blocked.json()["detail"] == "auth"
        assert int(blocked.headers["Retry-After"]) >= 1


def test_ip_bucket_is_separate_from_the_user_bucket():
    with session(rate_capacity_student=20, rate_ip_capacity=1) as client:
        user_id, _profile = bootstrap(client, "ip@b2.test")
        headers = auth(user_id, "ip@b2.test")
        assert client.get("/me", headers=headers).status_code == 200
        blocked = client.get("/me", headers=headers)
        assert blocked.status_code == 429
        assert blocked.json()["detail"] == "ip"


def test_daily_budget_blocks_chat_and_leaves_reads_up():
    with session(daily_tokens_student=40) as client:
        user_id, _profile = bootstrap(client, "budget@b2.test")
        with psycopg.connect(get_settings().postgres_url, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    SQL.INSERT_USAGE,
                    (new_id(), user_id, None, "chat", "gpt-4.1-mini", 40, 0, Decimal("0"), False),
                )
        headers = auth(user_id, "budget@b2.test")
        assert client.get("/me", headers=headers).status_code == 200
        blocked = client.post("/chat", headers=headers)
        assert blocked.status_code == 429
        assert blocked.json()["detail"] == "daily_budget"
        assert client.get("/students/" + user_id + "/conversations", headers=headers).status_code == 200


def test_monthly_breaker_blocks_only_llm_routes():
    with psycopg.connect(get_settings().postgres_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(SQL.USAGE_MONTH)
            spent = Decimal(cur.fetchone()[0])
    with session(monthly_usd=float(spent) + 0.25) as client:
        user_id, _profile = bootstrap(client, "month@b2.test")
        with psycopg.connect(get_settings().postgres_url, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    SQL.INSERT_USAGE,
                    (new_id(), user_id, None, "chat", "gpt-4.1-mini", 1, 0, Decimal("1"), False),
                )
        headers = auth(user_id, "month@b2.test")
        assert client.get("/me", headers=headers).status_code == 200
        blocked = client.post("/chat", headers=headers)
        assert blocked.status_code == 429
        assert blocked.json()["detail"] == "monthly_budget"


def test_org_budget_blocks_chat_for_a_member():
    with session(daily_usd_org=0.5) as client:
        supervisor_id, created = bootstrap(client, "org-rao@b2.test", role="supervisor")
        org_id = created["org_id"]
        code = client.get(
            f"/orgs/{org_id}/invite",
            headers=auth(supervisor_id, "org-rao@b2.test"),
        ).json()["code"]
        student_id, _student = bootstrap(client, "org-dev@b2.test")
        joined = client.post(
            "/orgs/join",
            json={"code": code},
            headers=auth(student_id, "org-dev@b2.test"),
        )
        assert joined.status_code == 200, joined.text
        with psycopg.connect(get_settings().postgres_url, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    SQL.INSERT_USAGE,
                    (new_id(), student_id, org_id, "chat", "gpt-4.1-mini", 1, 0, Decimal("1"), False),
                )
        headers = auth(student_id, "org-dev@b2.test")
        assert client.get("/me", headers=headers).status_code == 200
        blocked = client.post("/chat", headers=headers)
        assert blocked.status_code == 429
        assert blocked.json()["detail"] == "org_budget"


def test_oversized_body_is_rejected():
    with session(max_body_bytes=32) as client:
        response = client.post("/me/bootstrap", content=b"x" * 64, headers={"content-type": "application/json"})
        assert response.status_code == 413


class Scripted:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = 0

    async def complete(self, model, messages, max_tokens, json_mode):
        self.calls += 1
        item = self.replies.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    async def embed(self, model, text):
        self.calls += 1
        return [0.25, 0.5], 100_000


def principal(user_id: str, org_id: str | None = None) -> Principal:
    return Principal(user_id, "ledger@b2.test", True, "student", "student", org_id, False, None, "ready")


@pytest.fixture
async def ledger():
    from app.core import Container

    transport = Scripted([])
    settings = limits()
    built = Container.build(settings, SupabaseTokenVerifier(ISSUER, AUDIENCE, keys={"b2": PUBLIC}), transport)
    await built.open()
    ids: list[str] = []
    yield built, transport, ids
    if ids:
        await built.pg.execute(SQL.DELETE_USAGE_USERS, (ids,))
    await built.close()


async def test_llm_records_the_ledger_and_refuses_other_models(ledger):
    box, transport, ids = ledger
    user_id = new_id()
    ids.append(user_id)
    who = principal(user_id)
    transport.replies = [Completion("hello", 1000, 100)]
    reply = await box.llm.complete(who, [{"role": "user", "content": "hi"}])
    assert reply.text == "hello"
    rows = await box.pg.fetch(SQL.USAGE_FOR_USER, (user_id,))
    assert rows[0][0] == "chat"
    assert rows[0][1] == "gpt-4.1-mini"
    assert rows[0][5] is False
    assert Decimal(rows[0][4]) == Decimal("0.000560")

    transport.calls = 0
    box.settings.chat_model = "gpt-4o"
    with pytest.raises(Upstream):
        await box.llm.complete(who, [{"role": "user", "content": "hi"}])
    assert transport.calls == 0


async def test_structured_output_retries_once(ledger):
    box, transport, ids = ledger
    user_id = new_id()
    ids.append(user_id)

    class Out(BaseModel):
        text: str

    transport.replies = [Completion("nope", 10, 1), Completion('{"text":"ok"}', 10, 1)]
    parsed = await box.llm.structured(principal(user_id), [{"role": "user", "content": "say ok"}], Out)
    assert parsed.text == "ok"
    assert transport.calls == 2
    rows = await box.pg.fetch(SQL.USAGE_FOR_USER, (user_id,))
    assert len(rows) == 2

    transport.replies = [Completion("nope", 10, 1), Completion("still", 10, 1)]
    with pytest.raises(Upstream):
        await box.llm.structured(principal(user_id), [{"role": "user", "content": "say ok"}], Out)


async def test_embed_cache_skips_the_second_call(ledger):
    box, transport, ids = ledger
    user_id = new_id()
    ids.append(user_id)
    who = principal(user_id)
    first = await box.llm.embed(who, "attention is all you need")
    second = await box.llm.embed(who, "attention is all you need")
    assert first == second
    assert transport.calls == 1
    rows = await box.pg.fetch(SQL.USAGE_FOR_USER, (user_id,))
    assert rows[0][5] is False
    assert rows[0][2] == 100_000
    assert rows[1][5] is True
    assert rows[1][2] == 0


async def test_budget_is_checked_before_the_model_is_called(ledger):
    box, transport, ids = ledger
    user_id = new_id()
    ids.append(user_id)
    box.settings.daily_tokens_student = 5
    await box.pg.execute(
        SQL.INSERT_USAGE,
        (new_id(), user_id, None, "chat", "gpt-4.1-mini", 5, 0, Decimal("0"), False),
    )
    transport.replies = [Completion("should not run", 10, 1)]
    with pytest.raises(RateLimited) as caught:
        await box.llm.complete(principal(user_id), [{"role": "user", "content": "hi"}])
    assert caught.value.detail == "daily_budget"
    assert transport.calls == 0


async def test_transport_failure_retries_once(ledger):
    box, transport, ids = ledger
    user_id = new_id()
    ids.append(user_id)
    transport.replies = [RuntimeError("timeout"), Completion("recovered", 8, 2)]
    reply = await box.llm.complete(principal(user_id), [{"role": "user", "content": "hi"}])
    assert reply.text == "recovered"
    assert transport.calls == 2


async def test_concurrency_cap_is_two():
    from app.core import Container

    settings = limits(max_agent_concurrency=2)
    box = Container.build(settings, SupabaseTokenVerifier(ISSUER, AUDIENCE, keys={"b2": PUBLIC}))
    await box.open()
    user_id = new_id()
    try:
        await box.limiter.acquire(user_id)
        await box.limiter.acquire(user_id)
        with pytest.raises(RateLimited) as caught:
            await box.limiter.acquire(user_id)
        assert caught.value.detail == "concurrency"
        await box.limiter.release(user_id)
        await box.limiter.acquire(user_id)
    finally:
        await box.close()


async def test_live_bucket_backend_enforces_the_same_cap():
    from app.core import Container

    settings = get_settings().model_copy(
        update={"rate_backend": "auto", "rate_capacity_student": 2, "rate_refill_per_sec": 0, "rate_ip_capacity": 2}
    )
    box = Container.build(settings, SupabaseTokenVerifier(ISSUER, AUDIENCE, keys={"b2": PUBLIC}))
    await box.open()
    user_id = new_id()
    host = "198.51.100.20"
    keys = [f"rl:user:{user_id}", f"rl:ip:{host}"]

    class Request:
        client = type("Client", (), {"host": host})()

    try:
        assert box.limiter.backend in {"redis", "postgres"}
        who = principal(user_id)
        await box.limiter.allow(Request(), who, 1)
        await box.limiter.allow(Request(), who, 1)
        with pytest.raises(RateLimited) as caught:
            await box.limiter.allow(Request(), who, 1)
        assert caught.value.detail == "user"
    finally:
        await box.pg.execute(SQL.DELETE_BUCKETS, (keys,))
        if box.limiter.backend == "redis":
            try:
                await box.graph.eval("return redis.call('DEL', KEYS[1], KEYS[2])", keys, [])
            except Exception:
                pass
        await box.close()
