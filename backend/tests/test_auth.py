"""Auth, admin checks, class codes, and workspace isolation."""

import time
import uuid

import jwt
import psycopg
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient
from falkordb import FalkorDB
from redis.exceptions import ResponseError

from app.constants import get_settings
from app.main import create_app
from app.models.queries import SQL
from app.utilities.security import SupabaseTokenVerifier
from app.services.workspace import graph_name_for

ISSUER = "https://b1.test/auth/v1"
AUDIENCE = "authenticated"
PRIVATE = ec.generate_private_key(ec.SECP256R1())
PUBLIC = PRIVATE.public_key()


def token(user_id: str, email: str, **extra) -> str:
    now = int(time.time())
    claims = {
        "sub": user_id,
        "email": email,
        "aud": AUDIENCE,
        "iss": ISSUER,
        "exp": now + 600,
        "email_verified": True,
    }
    claims.update(extra)
    return jwt.encode(claims, PRIVATE, algorithm="ES256", headers={"kid": "b1"})


def auth(value: str) -> dict:
    return {"Authorization": f"Bearer {value}"}


def new_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def client():
    settings = get_settings().model_copy(update={"admin_emails": "admin@b1.test"})
    verifier = SupabaseTokenVerifier(ISSUER, AUDIENCE, keys={"b1": PUBLIC})
    app = create_app(settings, verifier)
    with TestClient(app) as test_client:
        yield test_client
    cleanup_b1()


def cleanup_b1() -> None:
    settings = get_settings()
    with psycopg.connect(settings.postgres_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id::text, graph_name FROM users WHERE email LIKE %s", ("%b1.test",))
            rows = cur.fetchall()
            if not rows:
                return
            ids = [row[0] for row in rows]
            cur.execute(
                "DELETE FROM enrollments WHERE student_id::text = ANY(%s) OR supervisor_id::text = ANY(%s)",
                (ids, ids),
            )
            cur.execute("DELETE FROM invites WHERE created_by::text = ANY(%s)", (ids,))
            cur.execute("DELETE FROM orgs WHERE owner_supervisor_id::text = ANY(%s)", (ids,))
            cur.execute("DELETE FROM users WHERE id::text = ANY(%s)", (ids,))
    db = FalkorDB(host=settings.falkordb_host, port=settings.falkordb_port, password=settings.falkordb_password or None)
    for user_id, _name in rows:
        graph = db.select_graph(graph_name_for(user_id))
        try:
            graph.delete()
        except ResponseError:
            pass


def bootstrap(client, email: str, role: str = "student", user_id: str | None = None, **claims):
    user_id = user_id or new_id()
    response = client.post("/me/bootstrap", json={"role": role, "display_name": email.split("@")[0]}, headers=auth(token(user_id, email, **claims)))
    return user_id, response


def test_expired_and_unverified_tokens_are_rejected(client):
    user_id = new_id()
    expired = token(user_id, "late@b1.test", exp=int(time.time()) - 10)
    assert client.post("/me/bootstrap", json={"role": "student"}, headers=auth(expired)).status_code == 401
    unverified = token(user_id, "plain@b1.test", email_verified=False)
    rejected = client.post("/me/bootstrap", json={"role": "student"}, headers=auth(unverified))
    assert rejected.status_code == 403
    with psycopg.connect(get_settings().postgres_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM users WHERE email = %s", ("plain@b1.test",))
            assert cur.fetchone()[0] == 0


def test_role_comes_from_our_table_and_admin_needs_every_check(client):
    user_id, created = bootstrap(
        client,
        "maya@b1.test",
        user_metadata={"role": "admin"},
    )
    assert created.status_code == 200, created.text
    assert created.json()["role"] == "student"
    assert client.get("/admin/whoami", headers=auth(token(user_id, "maya@b1.test"))).status_code == 403

    admin_id, admin = bootstrap(client, "admin@b1.test", role="student")
    assert admin.json()["role"] == "admin"
    assert client.get("/admin/whoami", headers=auth(token(admin_id, "admin@b1.test"))).status_code == 200

    client.app.state.container.settings.admin_emails = ""
    assert client.get("/admin/whoami", headers=auth(token(admin_id, "admin@b1.test"))).status_code == 403
    profile = client.get("/me", headers=auth(token(admin_id, "admin@b1.test")))
    assert profile.json()["role"] == "student"

    client.app.state.container.settings.admin_emails = "admin@b1.test"
    assert client.get("/admin/whoami", headers=auth(token(admin_id, "admin@b1.test"))).status_code == 200
    with psycopg.connect(get_settings().postgres_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(SQL.SET_DISABLED, (True, admin_id))
    assert client.get("/admin/whoami", headers=auth(token(admin_id, "admin@b1.test"))).status_code == 403


def test_class_code_enrollment(client):
    supervisor_id, created = bootstrap(client, "rao@b1.test", role="supervisor")
    assert created.status_code == 200, created.text
    org_id = created.json()["org_id"]
    invite = client.get(f"/orgs/{org_id}/invite", headers=auth(token(supervisor_id, "rao@b1.test")))
    assert invite.status_code == 200, invite.text
    code = invite.json()["code"]
    assert invite.json()["join_path"] == f"/join/{code}"

    student_id, student = bootstrap(client, "dev@b1.test")
    assert student.status_code == 200
    headers = auth(token(student_id, "dev@b1.test"))
    assert client.post("/orgs/join", json={"code": "no-such-code"}, headers=headers).status_code == 404

    with psycopg.connect(get_settings().postgres_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(SQL.EXPIRE_INVITE, (code,))
    assert client.post("/orgs/join", json={"code": code}, headers=headers).status_code == 404
    rotated = client.post(f"/orgs/{org_id}/invites", headers=auth(token(supervisor_id, "rao@b1.test")))
    fresh = rotated.json()["code"]
    assert client.post("/orgs/join", json={"code": code}, headers=headers).status_code == 404
    joined = client.post("/orgs/join", json={"code": fresh}, headers=headers)
    assert joined.status_code == 200, joined.text

    with psycopg.connect(get_settings().postgres_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(SQL.EXHAUST_INVITE, (fresh,))
    other_id, other = bootstrap(client, "ada@b1.test")
    assert other.status_code == 200
    assert client.post("/orgs/join", json={"code": fresh}, headers=auth(token(other_id, "ada@b1.test"))).status_code == 404


def test_supervisor_sees_progress_only_and_graphs_stay_isolated(client):
    supervisor_id, created = bootstrap(client, "rao2@b1.test", role="supervisor")
    org_id = created.json()["org_id"]
    code = client.get(f"/orgs/{org_id}/invite", headers=auth(token(supervisor_id, "rao2@b1.test"))).json()["code"]
    student_id, _student = bootstrap(client, "maya2@b1.test")
    other_id, _other = bootstrap(client, "dev2@b1.test")
    supervisor_headers = auth(token(supervisor_id, "rao2@b1.test"))
    student_headers = auth(token(student_id, "maya2@b1.test"))
    assert client.post("/orgs/join", json={"code": code}, headers=student_headers).status_code == 200

    progress = client.get(f"/students/{student_id}/progress", headers=supervisor_headers)
    assert progress.status_code == 200, progress.text
    body = progress.json()
    for hidden in ("conversation", "conversations", "turns", "chat", "trace"):
        assert hidden not in body
    assert set(body) == {"gaps", "open_gaps", "reading", "notes", "decisions", "timeline", "graph"}

    assert client.post("/chat", headers=supervisor_headers).status_code == 404
    assert client.get(f"/students/{student_id}/conversations", headers=supervisor_headers).status_code == 404
    assert client.get(f"/students/{student_id}/conversations", headers=student_headers).status_code == 200
    assert client.get(f"/students/{other_id}/progress", headers=student_headers).status_code == 404

    outsider_id, outsider = bootstrap(client, "outsider@b1.test", role="supervisor")
    assert outsider.status_code == 200
    assert client.get(f"/students/{student_id}/progress", headers=auth(token(outsider_id, "outsider@b1.test"))).status_code == 404

    assert client.delete(f"/orgs/{org_id}/students/{student_id}", headers=supervisor_headers).status_code == 200
    assert client.get(f"/students/{student_id}/progress", headers=supervisor_headers).status_code == 404

    settings = get_settings()
    db = FalkorDB(host=settings.falkordb_host, port=settings.falkordb_port, password=settings.falkordb_password or None)
    student_graph = db.select_graph(graph_name_for(student_id))
    other_graph = db.select_graph(graph_name_for(other_id))
    seen = other_graph.ro_query(
        "MATCH (s:Student {id: $id}) RETURN count(s)",
        {"id": student_id},
    ).result_set[0][0]
    assert seen == 0
    corpus = db.select_graph(settings.corpus_graph)
    leaked = corpus.ro_query(
        "MATCH (s:Student {id: $id}) RETURN count(s)",
        {"id": student_id},
    ).result_set[0][0]
    assert leaked == 0
    with pytest.raises(ResponseError):
        student_graph.ro_query("CREATE (:Nope {id: 'b1-write'})")
    left = student_graph.ro_query("MATCH (n:Nope {id: 'b1-write'}) RETURN count(n)").result_set[0][0]
    assert left == 0


def test_live_jwks_lists_signing_keys():
    import json
    import urllib.request

    settings = get_settings()
    with urllib.request.urlopen(settings.jwks_url, timeout=20) as response:
        keys = json.load(response)["keys"]
    assert keys
    assert {item["alg"] for item in keys} == {"ES256"}
