"""Ingesting the held-out paper scoops one student's gap and leaves the other alone."""

import time
import uuid
from datetime import datetime, timezone

import jwt
import psycopg
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from falkordb import FalkorDB
from httpx import ASGITransport, AsyncClient
from redis.exceptions import ResponseError

from app.constants import get_settings
from app.main import create_app
from app.models.queries import Q, SQL
from app.services.workspace import GraphHandle, graph_name_for
from app.utilities.security import SupabaseTokenVerifier
from app.utilities.worker import Worker

SCOOP = "2007.15251"
TASK = "problem:2273"
FAMILY = "defective list coloring"
METHOD = "method:1890"
ISSUER = "https://b10.test/auth/v1"
PRIVATE = ec.generate_private_key(ec.SECP256R1())
PUBLIC = PRIVATE.public_key()


def _token(user_id: str, email: str) -> str:
    now = int(time.time())
    claims = {"sub": user_id, "email": email, "aud": "authenticated", "iss": ISSUER, "exp": now + 600, "email_verified": True}
    return jwt.encode(claims, PRIVATE, algorithm="ES256", headers={"kid": "b10"})


def _headers(user_id: str, email: str) -> dict:
    return {"Authorization": f"Bearer {_token(user_id, email)}"}


@pytest.mark.asyncio
async def test_ingest_scoops_one_workspace_and_keeps_the_earlier_belief():
    settings = get_settings().model_copy(
        update={
            "admin_emails": "admin@b10.test",
            "rate_backend": "memory",
            "rate_capacity_admin": 400,
            "rate_capacity_student": 400,
            "monthly_usd": 10000,
            "work_hint_key": f"wq:hints:b10:{uuid.uuid4().hex}",
        }
    )
    app = create_app(settings, SupabaseTokenVerifier(ISSUER, "authenticated", keys={"b10": PUBLIC}))
    maya_id, dev_id, admin_id = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    gap_id = f"gap-{uuid.uuid4().hex[:12]}"
    other_id = f"gap-{uuid.uuid4().hex[:12]}"
    try:
        async with app.router.lifespan_context(app):
            box = app.state.container
            try:
                await _run(app, box, settings, maya_id, dev_id, admin_id, gap_id, other_id)
            finally:
                await box.ingest.write([SCOOP])
                restored = await box.graph.run(
                    settings.corpus_graph, Q.CELL_COUNT, {"task": TASK, "family": FAMILY}, ro=True
                )
                assert int(restored[0][0]) >= 1
    finally:
        await _clean()


async def _run(app, box, settings, maya_id, dev_id, admin_id, gap_id, other_id):
    before = await box.graph.run(settings.corpus_graph, Q.PRIVATE_NODES, ro=True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        for user_id, email, name in (
            (maya_id, "maya@b10.test", "Maya"),
            (dev_id, "dev@b10.test", "Dev"),
            (admin_id, "admin@b10.test", "Admin"),
        ):
            opened = await client.post(
                "/me/bootstrap",
                json={"role": "student", "display_name": name},
                headers=_headers(user_id, email),
            )
            assert opened.status_code == 200, opened.text
        denied = await client.post(
            "/admin/papers",
            json={"arxiv_ids": [SCOOP]},
            headers=_headers(maya_id, "maya@b10.test"),
        )
        assert denied.status_code == 403

        maya = GraphHandle(box.graph, graph_name_for(maya_id), "write")
        dev = GraphHandle(box.graph, graph_name_for(dev_id), "write")
        await _open_gap(box, maya, gap_id, TASK, FAMILY, METHOD, "the coloring cell is still empty")
        await _open_gap(box, dev, other_id, "problem:other", "unrelated family", "method:other", "dev keeps this")
        belief = await box.memory.remember(maya, "belief", "the coloring cell is still empty", gap_id)
        counted = await box.graph.run(settings.corpus_graph, Q.CELL_COUNT, {"task": TASK, "family": FAMILY}, ro=True)
        assert int(counted[0][0]) >= 1
        await box.graph.run(settings.corpus_graph, Q.DROP_CELL_EDGE, {"id": SCOOP, "family": FAMILY})
        empty = await box.graph.run(settings.corpus_graph, Q.CELL_COUNT, {"task": TASK, "family": FAMILY}, ro=True)
        assert int(empty[0][0]) == 0

        posted = await client.post(
            "/admin/papers",
            json={"arxiv_ids": [SCOOP]},
            headers=_headers(admin_id, "admin@b10.test"),
        )
        assert posted.status_code == 202, posted.text
        worker = Worker(box)
        assert await worker.run_graph(settings.corpus_graph) >= 1
        assert await worker.run_graph(graph_name_for(maya_id)) >= 1
        assert await worker.run_graph(graph_name_for(dev_id)) == 0

        maya_gap = await box.gaps.get(maya, gap_id)
        dev_gap = await box.gaps.get(dev, other_id)
        assert maya_gap["status"] == "scooped"
        assert dev_gap["status"] == "alive"
        decision = await maya.query(Q.GAP_DECISION, {"id": gap_id})
        assert decision and bool(decision[0][1]) is True
        earlier = await box.memory.as_of(maya, belief["valid_from"])
        assert any(item["text"] == "the coloring cell is still empty" for item in earlier["memories"])
        current = await box.memory.recall(maya, "coloring cell", 5)
        assert all(item["text"] != "the coloring cell is still empty" for item in current["memories"])
        after = await box.graph.run(settings.corpus_graph, Q.PRIVATE_NODES, ro=True)
        assert int(after[0][0]) == int(before[0][0]) == 0


async def _open_gap(box, handle, gap_id: str, task: str, family: str, method: str, reason: str) -> None:
    at = datetime.now(timezone.utc).isoformat()
    await handle.query(
        Q.SAVE_GAP,
        {
            "id": gap_id,
            "at": at,
            "task": task,
            "family": family,
            "method": method,
            "score": 2,
            "text": reason,
            "signal": "empty_cell",
            "year": 2020,
            "event_id": f"opened-{gap_id}",
        },
    )
    await box.gaps.note_cell(handle.name, task, method, family, True)
    await box.gaps.add_evidence(handle, gap_id, "2105.04700", "paper")
    await box.gaps.add_evidence(handle, gap_id, "2304.09666", "paper")
    challenged = await box.gaps.transition(handle, gap_id, "challenged", 1)
    await box.gaps.transition(handle, gap_id, "alive", challenged["version"])
    await box.memory.decide(handle, "pursue", reason, gap_id)


async def _clean() -> None:
    live = get_settings()
    ids = []
    with psycopg.connect(live.postgres_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id::text FROM users WHERE email LIKE %s", ("%b10.test",))
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
    db = FalkorDB(host=live.falkordb_host, port=live.falkordb_port, password=live.falkordb_password or None)
    for user_id in ids:
        try:
            db.select_graph(graph_name_for(user_id)).delete()
        except ResponseError:
            pass
