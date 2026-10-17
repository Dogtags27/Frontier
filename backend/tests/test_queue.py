"""Work queue, leases, handoffs, and gap versions. No OpenAI calls."""

import asyncio
import time
import uuid

import jwt
import psycopg
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient
from redis.exceptions import ResponseError

from app.constants import get_settings
from app.main import create_app
from app.models.queries import Q, SQL
from app.services.gaps import GapService
from app.services.memory import MemoryService
from app.services.queue import WorkQueue
from app.services.workspace import GraphHandle, WorkspaceResolver
from app.utilities.security import SupabaseTokenVerifier
from app.utilities.stores import GraphStore
from app.utilities.worker import Worker

ISSUER = "https://b5.test/auth/v1"
AUDIENCE = "authenticated"
PRIVATE = ec.generate_private_key(ec.SECP256R1())
PUBLIC = PRIVATE.public_key()


def token(user_id: str, email: str) -> str:
    now = int(time.time())
    claims = {
        "sub": user_id,
        "email": email,
        "aud": AUDIENCE,
        "iss": ISSUER,
        "exp": now + 600,
        "email_verified": True,
    }
    return jwt.encode(claims, PRIVATE, algorithm="ES256", headers={"kid": "b5"})


def auth(user_id: str, email: str) -> dict:
    return {"Authorization": f"Bearer {token(user_id, email)}"}


def settings():
    return get_settings().model_copy(
        update={
            "admin_emails": "admin@b5.test",
            "rate_backend": "memory",
            "rate_capacity_student": 500,
            "rate_ip_capacity": 2000,
            "rate_auth_capacity": 50,
            "work_hint_key": f"wq:hints:b5:{uuid.uuid4().hex}",
            "work_lease_sec": 30,
            "work_attempts": 3,
        }
    )


def app(configured):
    return create_app(configured, SupabaseTokenVerifier(ISSUER, AUDIENCE, keys={"b5": PUBLIC}))


class Box:
    def __init__(self, configured):
        self.settings = configured
        self.graph = GraphStore(configured)
        self.queue = WorkQueue(self.graph, None, configured)
        self.gaps = GapService(self.graph)
        self.memory = MemoryService(self.graph)
        self.workspace = WorkspaceResolver(self.graph, None)

    async def close(self):
        await self.graph.close()


def graph_name() -> str:
    return f"frontier_ws_{uuid.uuid4().hex}"


async def discard(box: Box, name: str) -> None:
    try:
        await box.graph.delete_graph(name)
    except ResponseError:
        pass
    await box.close()


async def test_twenty_claimers_and_an_expired_lease_have_one_winner():
    configured = settings()
    box = Box(configured)
    name = graph_name()
    try:
        await box.graph.ensure_workspace(name)
        job = await box.queue.enqueue(name, "write_brief", {})
        winners = await asyncio.gather(
            *[box.queue.claim(name, f"claim-{index}", ["write_brief"]) for index in range(20)]
        )
        claimed = [item for item in winners if item]
        assert len(claimed) == 1
        assert claimed[0]["id"] == job["id"]
        late = await box.queue.complete(name, "someone-else", job["id"], {"ok": True})
        assert late is False

        expired = await box.queue.enqueue(name, "write_brief", {"n": 2})
        first = await box.queue.claim(name, "first", ["write_brief"], lease_sec=-1)
        second = await box.queue.claim(name, "second", ["write_brief"])
        assert first["id"] == expired["id"]
        assert second["id"] == expired["id"]
        assert await box.queue.complete(name, "first", expired["id"], {"ok": True}) is False
        assert await box.queue.complete(name, "second", expired["id"], {"ok": True}) is True
        stored = await box.queue.get(name, expired["id"])
        assert stored["status"] == "done"
        assert stored["attempts"] == 2
    finally:
        await discard(box, name)


async def test_workers_run_a_job_once_and_the_sweeper_restores_a_hint():
    configured = settings()
    box = Box(configured)
    name = graph_name()
    calls = []

    async def once(item, graph):
        calls.append((graph, item["id"]))
        await asyncio.sleep(0.05)
        return {"ok": True}

    try:
        await box.graph.ensure_workspace(name)
        job = await box.queue.enqueue(name, "write_brief", {})
        hint = await box.graph.pop_hint(configured.work_hint_key, 1)
        assert hint == name
        workers = [Worker(box, {"write_brief": once}, worker_id=f"w-{index}") for index in range(8)]
        finished = await asyncio.gather(*[worker.run_graph(name) for worker in workers])
        assert sum(finished) == 1
        assert calls == [(name, job["id"])]
        other = graph_name()
        await box.graph.ensure_workspace(other)
        assert await workers[0].container.queue.claim(other, "other", ["write_brief"]) is None

        waiting = await box.queue.enqueue(name, "write_brief", {"later": True})
        await box.graph.pop_hint(configured.work_hint_key, 1)
        assert await workers[0].sweep_once([name]) == 1
        assert await box.graph.pop_hint(configured.work_hint_key, 1) == name
        assert await box.queue.get(name, waiting["id"])
        await discard_name(box, other)
    finally:
        await discard(box, name)


async def discard_name(box: Box, name: str) -> None:
    try:
        await box.graph.delete_graph(name)
    except ResponseError:
        pass


async def test_parallel_reads_collapse_and_a_blocked_handoff_stays_visible():
    configured = settings()
    box = Box(configured)
    name = graph_name()
    handle = GraphHandle(box.graph, name, "write")
    try:
        await box.graph.ensure_workspace(name)
        await asyncio.gather(
            *[box.memory.read(handle, "2211.05920", "read", f"note {index}") for index in range(8)]
        )
        count = await box.graph.run(name, Q.COUNT_READS)
        assert int(count[0][0]) == 1

        opened = await box.memory.open_gap(handle, "labeling cost", "problem:1326")
        decision = await box.memory.decide(handle, "pursue", "worth a week", opened["id"])
        handoff = await box.gaps.open_handoff(handle, opened["id"], "adversary", "gaphunter")
        blocked = await box.gaps.resolve(handle, handoff["id"])
        assert blocked["status"] == "blocked"
        assert "two evidence" in blocked["reason"]
        visible = await box.gaps.list_handoffs(handle)
        assert visible["items"][0]["status"] == "blocked"
        assert visible["items"][0]["reason"]

        await box.gaps.add_evidence(handle, opened["id"], "2211.05920", "paper")
        reopened = await box.gaps.add_evidence(handle, opened["id"], "1105.3264", "paper")
        assert handoff["id"] in reopened["reopened"]
        job = await box.queue.enqueue(name, "resolve_handoff", {"handoff_id": handoff["id"]})
        worker = Worker(box)
        assert await worker.run_graph(name) == 1
        resolved = await box.gaps.resolve(handle, handoff["id"])
        assert resolved["status"] == "accepted"
        done = await box.queue.get(name, job["id"])
        assert done["status"] == "done"
        assert done["result"]["status"] == "accepted"

        moved = await box.gaps.transition(handle, opened["id"], "challenged", 1)
        assert moved["version"] == 2
        alive = await box.gaps.transition(handle, opened["id"], "alive", 2)
        scooped = await box.gaps.transition(handle, opened["id"], "scooped", alive["version"])
        assert scooped["status"] == "scooped"
        state = await box.graph.run(name, Q.DECISION_STATE, {"id": decision["id"]})
        assert state[0][1] is True or _text(state[0][1]) == "true"
        brief_job = await box.queue.enqueue(name, "write_brief", {})
        assert await Worker(box).run_graph(name) == 1
        brief = await box.queue.get(name, brief_job["id"])
        assert brief["result"]["source"] == "graph"
        assert "Last reading" in brief["result"]["summary"]
    finally:
        await discard(box, name)


def _text(value) -> str:
    if isinstance(value, bytes):
        return value.decode()
    return str(value)


def test_two_writers_one_gap_and_jobs_stay_on_that_graph():
    configured = settings()
    try:
        with TestClient(app(configured)) as client:
            student = _bootstrap(client, "maya@b5.test")
            other = _bootstrap(client, "dev@b5.test")
            headers = auth(student, "maya@b5.test")
            opened = client.post(
                f"/students/{student}/gaps",
                json={"text": "empty cell", "task_id": "problem:1326"},
                headers=headers,
            )
            assert opened.status_code == 200, opened.text
            gap_id = opened.json()["id"]
            body = {"to": "challenged", "version": 1}
            first, second = asyncio.run(
                _both(
                    client,
                    f"/students/{student}/gaps/{gap_id}/transition",
                    body,
                    headers,
                )
            )
            codes = sorted([first.status_code, second.status_code])
            assert codes == [200, 409]
            lost = second if second.status_code == 409 else first
            assert lost.json()["detail"] == "challenged:2"
            current = client.get(f"/students/{student}/gaps/{gap_id}", headers=headers)
            assert current.json()["version"] == 2
            assert current.json()["status"] == "challenged"

            queued = client.post(
                f"/students/{student}/jobs",
                json={"type": "write_brief", "payload": {}},
                headers=headers,
            )
            assert queued.status_code == 202, queued.text
            hidden = client.get(
                f"/students/{other}/jobs/{queued.json()['id']}",
                headers=auth(other, "dev@b5.test"),
            )
            assert hidden.status_code == 404
            illegal = client.post(
                f"/students/{student}/gaps/{gap_id}/transition",
                json={"to": "adopted", "version": 2},
                headers=headers,
            )
            assert illegal.status_code == 400
    finally:
        _cleanup()


async def _both(client, path, body, headers):
    return await asyncio.gather(
        asyncio.to_thread(client.post, path, json=body, headers=headers),
        asyncio.to_thread(client.post, path, json=body, headers=headers),
    )


def _bootstrap(client, email: str) -> str:
    user_id = str(uuid.uuid4())
    response = client.post(
        "/me/bootstrap",
        json={"role": "student", "display_name": email.split("@")[0]},
        headers=auth(user_id, email),
    )
    assert response.status_code == 200, response.text
    return user_id


def _cleanup() -> None:
    from app.services.workspace import graph_name_for
    from falkordb import FalkorDB

    live = get_settings()
    with psycopg.connect(live.postgres_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id::text FROM users WHERE email LIKE %s", ("%b5.test",))
            ids = [row[0] for row in cur.fetchall()]
            if not ids:
                return
            cur.execute(SQL.DELETE_USAGE_USERS, (ids,))
            cur.execute(
                "DELETE FROM enrollments WHERE student_id::text = ANY(%s) OR supervisor_id::text = ANY(%s)",
                (ids, ids),
            )
            cur.execute("DELETE FROM invites WHERE created_by::text = ANY(%s)", (ids,))
            cur.execute("DELETE FROM orgs WHERE owner_supervisor_id::text = ANY(%s)", (ids,))
            cur.execute("DELETE FROM users WHERE id::text = ANY(%s)", (ids,))
    db = FalkorDB(host=live.falkordb_host, port=live.falkordb_port, password=live.falkordb_password or None)
    for user_id in ids:
        try:
            db.select_graph(graph_name_for(user_id)).delete()
        except ResponseError:
            pass
