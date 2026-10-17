"""Shared helpers for tests that run the real app against the local stores and the real model."""

import json
import time
import uuid
from contextlib import contextmanager

import jwt
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from app.constants import get_settings
from app.main import create_app
from app.models.queries import SQL
from app.services.workspace import graph_name_for
from app.utilities.security import SupabaseTokenVerifier

ISSUER = "https://live.test/auth/v1"
PRIVATE = ec.generate_private_key(ec.SECP256R1())
PUBLIC = PRIVATE.public_key()


def token(user_id: str, email: str) -> str:
    now = int(time.time())
    claims = {"sub": user_id, "email": email, "aud": "authenticated", "iss": ISSUER, "exp": now + 900, "email_verified": True}
    return jwt.encode(claims, PRIVATE, algorithm="ES256", headers={"kid": "live"})


class Student:
    """One signed-in student with helpers that read the SSE stream."""

    def __init__(self, client: TestClient, name: str):
        self.client = client
        self.id = str(uuid.uuid4())
        self.email = f"{name}-{self.id[:6]}@live.test"
        self.headers = {"Authorization": f"Bearer {token(self.id, self.email)}"}
        made = client.post("/me/bootstrap", json={"role": "student", "display_name": name}, headers=self.headers)
        assert made.status_code == 200, made.text
        self.conversation = ""

    def chat(self, message: str, conversation: str | None = None) -> dict:
        body = {"message": message}
        use = self.conversation if conversation is None else conversation
        if use:
            body["conversation_id"] = use
        res = self.client.post("/chat", json=body, headers=self.headers)
        assert res.status_code == 200, res.text
        events: dict[str, list] = {}
        for block in res.text.split("\n\n"):
            name = block.split("event: ", 1)[1].split("\n", 1)[0] if "event: " in block else ""
            raw = block.split("data: ", 1)[1] if "data: " in block else ""
            if name and raw:
                events.setdefault(name, []).append(json.loads(raw))
        final = events["final"][0]
        convo = (events.get("conversation") or [{}])[0].get("id", "")
        if convo:
            self.conversation = convo
        return {
            "intent": (events.get("intent") or [{}])[0],
            "final": final,
            "text": final["text"],
            "evidence": final.get("evidence") or [],
            "conversation": convo,
            "events": events,
        }

    def get(self, path: str):
        res = self.client.get(path, headers=self.headers)
        assert res.status_code == 200, (path, res.text)
        return res.json()


@contextmanager
def live_app():
    settings = get_settings().model_copy(update={"admin_emails": "", "rate_backend": "memory", "rate_capacity_student": 500, "monthly_usd": 10000, "daily_usd_student": 100, "daily_tokens_student": 5_000_000})
    app = create_app(settings, SupabaseTokenVerifier(ISSUER, "authenticated", keys={"live": PUBLIC}))
    with TestClient(app) as client:
        box = app.state.container
        users: list[str] = []

        def make(name: str) -> Student:
            student = Student(client, name)
            users.append(student.id)
            return student

        try:
            yield client, make, box
        finally:
            async def clean():
                for user in users:
                    try:
                        await box.graph.delete_graph(graph_name_for(user))
                    except Exception:
                        pass
                try:
                    await box.pg.execute(SQL.DELETE_USAGE_USERS, (users,))
                    await box.pg.execute("DELETE FROM enrollments WHERE student_id::text = ANY(%s)", (users,))
                    await box.pg.execute("DELETE FROM open_gap_index WHERE user_id::text = ANY(%s)", (users,))
                    await box.pg.execute("DELETE FROM users WHERE id::text = ANY(%s)", (users,))
                except Exception:
                    pass

            try:
                client.portal.call(clean)
            except Exception:
                pass
