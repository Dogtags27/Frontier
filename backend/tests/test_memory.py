"""Memory, conversations, and the supervisor summary. No OpenAI calls."""

import time
import uuid
from contextlib import contextmanager

import jwt
import psycopg
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient
from falkordb import FalkorDB
from redis.exceptions import ResponseError

from app.constants import get_settings
from app.main import create_app
from app.models.queries import SQL
from app.utilities.security import SupabaseTokenVerifier
from app.services.workspace import graph_name_for

ISSUER = "https://b4.test/auth/v1"
AUDIENCE = "authenticated"
PRIVATE = ec.generate_private_key(ec.SECP256R1())
PUBLIC = PRIVATE.public_key()
PAPER = "2211.05920"
MEMORY = "secret-memory-belief about coloring"
CHAT = "secret-chat-line about the seminar"


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
    return jwt.encode(claims, PRIVATE, algorithm="ES256", headers={"kid": "b4"})


def auth(user_id: str, email: str) -> dict:
    return {"Authorization": f"Bearer {token(user_id, email)}"}


def settings():
    return get_settings().model_copy(
        update={
            "admin_emails": "admin@b4.test",
            "rate_backend": "memory",
            "rate_capacity_student": 80,
            "rate_capacity_supervisor": 80,
            "rate_ip_capacity": 400,
            "rate_auth_capacity": 30,
            "daily_tokens_student": 100_000,
            "monthly_usd": 10_000,
        }
    )


def app():
    return create_app(settings(), SupabaseTokenVerifier(ISSUER, AUDIENCE, keys={"b4": PUBLIC}))


@contextmanager
def client():
    try:
        with TestClient(app()) as test_client:
            yield test_client
    finally:
        cleanup()


def cleanup() -> None:
    live = get_settings()
    with psycopg.connect(live.postgres_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id::text FROM users WHERE email LIKE %s", ("%b4.test",))
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
        graph = db.select_graph(graph_name_for(user_id))
        try:
            graph.delete()
        except ResponseError:
            pass


def bootstrap(test_client, email: str, role: str = "student") -> str:
    user_id = str(uuid.uuid4())
    response = test_client.post(
        "/me/bootstrap",
        json={"role": role, "display_name": email.split("@")[0]},
        headers=auth(user_id, email),
    )
    assert response.status_code == 200, response.text
    return user_id


def test_records_persist_across_a_new_process_and_stay_off_the_summary():
    try:
        with TestClient(app()) as first:
            student = bootstrap(first, "maya@b4.test")
            headers = auth(student, "maya@b4.test")
            recorded = first.post(
                f"/students/{student}/reads",
                json={"paper_id": PAPER, "depth": "read", "note": "main limit is labeling cost"},
                headers=headers,
            )
            assert recorded.status_code == 200, recorded.text
            again = first.post(
                f"/students/{student}/reads",
                json={"paper_id": PAPER, "depth": "read", "note": "main limit is labeling cost"},
                headers={**headers, "Idempotency-Key": "read-1"},
            )
            repeat = first.post(
                f"/students/{student}/reads",
                json={"paper_id": PAPER, "depth": "understood", "note": "different"},
                headers={**headers, "Idempotency-Key": "read-1"},
            )
            assert again.json()["id"] == repeat.json()["id"]
            gap = first.post(
                f"/students/{student}/gaps",
                json={"text": "labeling cost for defect models", "task_id": "problem:1326"},
                headers=headers,
            )
            assert gap.status_code == 200, gap.text
            memory = first.post(
                f"/students/{student}/memory",
                json={"kind": "belief", "text": MEMORY, "entity": "coloring"},
                headers=headers,
            )
            assert memory.status_code == 200, memory.text
            same = first.post(
                f"/students/{student}/memory",
                json={"kind": "belief", "text": MEMORY, "entity": "coloring"},
                headers=headers,
            )
            assert same.json()["duplicate"] is True
            assert same.json()["id"] == memory.json()["id"]
            conversation = first.post(
                f"/students/{student}/conversations",
                json={"title": "seminar"},
                headers=headers,
            )
            conversation_id = conversation.json()["id"]
            turn = first.post(
                f"/students/{student}/conversations/{conversation_id}/turns",
                json={"text": CHAT},
                headers=headers,
            )
            assert turn.status_code == 200, turn.text
            remembered = first.get(f"/students/{student}/memory", params={"q": "coloring"}, headers=headers).json()
            stored_chat = first.get(f"/students/{student}/conversations/{conversation_id}", headers=headers).json()
            timeline = first.get(f"/students/{student}/timeline", headers=headers).json()

        with TestClient(app()) as second:
            headers = auth(student, "maya@b4.test")
            recalled = second.get(f"/students/{student}/memory", params={"q": "coloring"}, headers=headers)
            assert recalled.status_code == 200, recalled.text
            assert recalled.json() == remembered
            reloaded = second.get(f"/students/{student}/conversations/{conversation_id}", headers=headers)
            assert reloaded.json() == stored_chat
            assert reloaded.json()["turns"][0]["text"] == CHAT
            again_timeline = second.get(f"/students/{student}/timeline", headers=headers)
            assert again_timeline.json() == timeline
            kinds = [item["kind"] for item in again_timeline.json()["items"]]
            assert "read" in kinds and "gap_opened" in kinds
            assert any(item["title"] for item in again_timeline.json()["items"] if item["ref"] == PAPER)

            brief = second.get(f"/students/{student}/brief", headers=headers)
            assert brief.status_code == 200, brief.text
            assert brief.json()["source"] == "graph"
            assert "labeling cost" in brief.json()["text"]
            assert CHAT not in brief.json()["text"]
            assert MEMORY not in brief.json()["text"]

            supervisor = bootstrap(second, "rao@b4.test", role="supervisor")
            org_id = second.get("/me", headers=auth(supervisor, "rao@b4.test")).json()["org_id"]
            code = second.get(f"/orgs/{org_id}/invite", headers=auth(supervisor, "rao@b4.test")).json()["code"]
            assert second.post("/orgs/join", json={"code": code}, headers=headers).status_code == 200
            summary = second.get(f"/students/{student}/progress", headers=auth(supervisor, "rao@b4.test"))
            assert summary.status_code == 200, summary.text
            body = summary.json()
            assert set(body) == {"gaps", "open_gaps", "reading", "notes", "decisions", "timeline", "graph"}
            assert body["graph"]["reads"] >= 1
            assert body["gaps"]["candidate"] == 1
            assert any(item["kind"] == "read" for item in body["timeline"])
            assert any(item["kind"] == "gap_opened" for item in body["timeline"])
            dumped = summary.text
            assert CHAT not in dumped
            assert MEMORY not in dumped
            assert "conversation" not in body
            supervisor_headers = auth(supervisor, "rao@b4.test")
            assert second.get(f"/students/{student}/conversations", headers=supervisor_headers).status_code == 404
            assert second.get(f"/students/{student}/memory", headers=supervisor_headers).status_code == 404
            assert second.post("/chat", headers=supervisor_headers).status_code == 404
    finally:
        cleanup()


def test_a_replaced_belief_stays_visible_as_of_the_old_time():
    with client() as test_client:
        student = bootstrap(test_client, "dev@b4.test")
        headers = auth(student, "dev@b4.test")
        first = test_client.post(
            f"/students/{student}/memory",
            json={"kind": "belief", "text": "coloring is open", "entity": "coloring"},
            headers=headers,
        ).json()
        test_client.post(
            f"/students/{student}/memory",
            json={"kind": "belief", "text": "coloring was scooped", "entity": "coloring"},
            headers=headers,
        )
        current = test_client.get(f"/students/{student}/memory", params={"q": "coloring"}, headers=headers).json()
        assert [item["text"] for item in current["memories"]] == ["coloring was scooped"]
        past = test_client.get(
            f"/students/{student}/memory/as-of",
            params={"at": first["valid_from"]},
            headers=headers,
        )
        assert past.status_code == 200, past.text
        assert [item["text"] for item in past.json()["memories"]] == ["coloring is open"]
        forgotten = test_client.delete(f"/students/{student}/memory/{current['memories'][0]['id']}", headers=headers)
        assert forgotten.status_code == 200, forgotten.text
        left = test_client.get(f"/students/{student}/memory", params={"q": "coloring"}, headers=headers).json()
        assert left["memories"] == []
