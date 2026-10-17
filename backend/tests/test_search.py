"""Semantic, name, and filter search against the loaded corpus. No OpenAI calls."""

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

ISSUER = "https://b3.test/auth/v1"
AUDIENCE = "authenticated"
PRIVATE = ec.generate_private_key(ec.SECP256R1())
PUBLIC = PRIVATE.public_key()
PAPER = "2211.05920"
CITED = "1105.3264"


class EmbedOnly:
    def __init__(self, vector):
        self.vector = vector
        self.calls = 0

    async def complete(self, model, messages, max_tokens, json_mode):
        raise AssertionError("search must not call the chat model")

    async def embed(self, model, text):
        self.calls += 1
        return list(self.vector), 8


class NoEmbed(EmbedOnly):
    def __init__(self):
        super().__init__([])

    async def embed(self, model, text):
        self.calls += 1
        raise AssertionError("this search should not embed")


def paper_vector() -> list[float]:
    settings = get_settings()
    db = FalkorDB(host=settings.falkordb_host, port=settings.falkordb_port, password=settings.falkordb_password or None)
    row = db.select_graph(settings.corpus_graph).ro_query(
        "MATCH (p:Paper {arxiv_id: $id}) RETURN p.embedding",
        {"id": PAPER},
    ).result_set[0][0]
    return list(row)


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
    return jwt.encode(claims, PRIVATE, algorithm="ES256", headers={"kid": "b3"})


def auth(user_id: str, email: str) -> dict:
    return {"Authorization": f"Bearer {token(user_id, email)}"}


@contextmanager
def session(transport):
    settings = get_settings().model_copy(
        update={
            "admin_emails": "admin@b3.test",
            "rate_backend": "memory",
            "rate_capacity_student": 80,
            "rate_ip_capacity": 200,
            "rate_auth_capacity": 20,
            "daily_tokens_student": 100_000,
            "daily_usd_student": 100,
            "monthly_usd": 10_000,
        }
    )
    app = create_app(settings, SupabaseTokenVerifier(ISSUER, AUDIENCE, keys={"b3": PUBLIC}), transport)
    try:
        with TestClient(app) as client:
            user_id = str(uuid.uuid4())
            created = client.post(
                "/me/bootstrap",
                json={"role": "student", "display_name": "search"},
                headers=auth(user_id, "search@b3.test"),
            )
            assert created.status_code == 200, created.text
            yield client, user_id, transport
    finally:
        cleanup()


def cleanup() -> None:
    settings = get_settings()
    with psycopg.connect(settings.postgres_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id::text FROM users WHERE email LIKE %s", ("%b3.test",))
            ids = [row[0] for row in cur.fetchall()]
            if not ids:
                return
            cur.execute(SQL.DELETE_USAGE_USERS, (ids,))
            cur.execute("DELETE FROM users WHERE id::text = ANY(%s)", (ids,))
    db = FalkorDB(host=settings.falkordb_host, port=settings.falkordb_port, password=settings.falkordb_password or None)
    for user_id in ids:
        graph = db.select_graph(graph_name_for(user_id))
        try:
            graph.delete()
        except ResponseError:
            pass


def test_direct_title_words_outrank_a_semantic_only_hit():
    from app.models.schemas import SearchQuery
    from app.services.search import SearchService

    service = SearchService(None, None, None, None)
    request = SearchQuery(q="graph neural networks", mode="hybrid")
    channels = {"vector": ["semantic-only", "title-hit"], "title": ["title-hit"], "name": ["dataset-hit"]}
    props = {
        "semantic-only": _paper("semantic-only", "Unrelated Methods for Convex Optimization"),
        "title-hit": _paper("title-hit", "Graph Neural Networks for Molecules"),
        "dataset-hit": _paper("dataset-hit", "A Survey of Training Tricks"),
    }
    hits = service._combine(channels, props, {}, {}, {}, request, None)
    assert [hit["arxiv_id"] for hit in hits][:2] == ["title-hit", "dataset-hit"]
    assert hits[0]["score"] > hits[-1]["score"]


def _paper(arxiv_id: str, title: str) -> dict:
    return {
        "arxiv_id": arxiv_id,
        "title": title,
        "year": 2022,
        "category": "cs.LG",
        "layer": "recent",
        "paper_kind": "research",
    }


def ids(body) -> list[str]:
    return [item["arxiv_id"] for item in body["items"]]


def test_metadata_search_finds_a_title_and_does_not_embed():
    with session(NoEmbed()) as (client, user_id, transport):
        response = client.get("/papers/search", params={"q": "defect", "mode": "metadata"}, headers=auth(user_id, "search@b3.test"))
        assert response.status_code == 200, response.text
        body = response.json()
        assert PAPER in ids(body)
        hit = next(item for item in body["items"] if item["arxiv_id"] == PAPER)
        assert "title" in hit["matched_by"]
        assert body["elapsed_ms"] < 5000
        assert transport.calls == 0


def test_filters_and_name_lookup_narrow_the_same_paper():
    with session(NoEmbed()) as (client, user_id, _transport):
        headers = auth(user_id, "search@b3.test")
        later = client.get(
            "/papers/search",
            params={"q": "defect", "mode": "metadata", "year_from": 2023},
            headers=headers,
        )
        assert PAPER not in ids(later.json())
        named = client.get(
            "/papers/search",
            params={
                "mode": "metadata",
                "method": "LSVM",
                "category": "cs.SE",
                "year_from": 2022,
                "year_to": 2022,
                "limit": 20,
            },
            headers=headers,
        )
        assert named.status_code == 200, named.text
        assert PAPER in ids(named.json())
        citing = client.get(
            "/papers/search",
            params={"mode": "metadata", "cites": CITED, "year_from": 2022, "year_to": 2022, "category": "cs.SE", "limit": 20},
            headers=headers,
        )
        assert PAPER in ids(citing.json())


def test_abstract_channel_matches_words_that_are_not_the_title():
    with session(NoEmbed()) as (client, user_id, transport):
        response = client.get(
            "/papers/search",
            params={"q": "non-defective", "mode": "metadata"},
            headers=auth(user_id, "search@b3.test"),
        )
        assert response.status_code == 200, response.text
        hit = next(item for item in response.json()["items"] if item["arxiv_id"] == PAPER)
        assert "abstract" in hit["matched_by"]
        assert transport.calls == 0


def test_semantic_search_uses_one_injected_vector_and_returns_the_paper_first():
    vector = paper_vector()
    transport = EmbedOnly(vector)
    with session(transport) as (client, user_id, _transport):
        response = client.get(
            "/papers/search",
            params={"q": "semi-supervised defect prediction", "mode": "semantic", "limit": 5},
            headers=auth(user_id, "search@b3.test"),
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["items"][0]["arxiv_id"] == PAPER
        assert body["items"][0]["distance"] == 0
        assert body["items"][0]["matched_by"] == ["vector"]
        assert body["items"][0]["snippet"]
        assert body["elapsed_ms"] < 5000
        assert transport.calls == 1


def test_hybrid_reports_every_channel_that_matched():
    transport = EmbedOnly(paper_vector())
    with session(transport) as (client, user_id, _transport):
        response = client.get(
            "/papers/search",
            params={"q": "defect", "mode": "hybrid"},
            headers=auth(user_id, "search@b3.test"),
        )
        assert response.status_code == 200, response.text
        hit = next(item for item in response.json()["items"] if item["arxiv_id"] == PAPER)
        assert "vector" in hit["matched_by"]
        assert "title" in hit["matched_by"]
        assert transport.calls == 1


def test_sorting_and_cursor():
    with session(NoEmbed()) as (client, user_id, _transport):
        headers = auth(user_id, "search@b3.test")
        params = {"mode": "metadata", "layer": "recent", "paper_kind": "research", "limit": 5, "sort": "year_asc"}
        page = client.get("/papers/search", params=params, headers=headers)
        assert page.status_code == 200, page.text
        years = [item["year"] for item in page.json()["items"]]
        assert years == sorted(years)
        assert page.json()["next_cursor"] == 5
        nxt = client.get("/papers/search", params={**params, "cursor": 5}, headers=headers)
        assert ids(page.json()) != ids(nxt.json())
        titled = client.get(
            "/papers/search",
            params={"mode": "metadata", "category": "cs.SE", "year_from": 2022, "year_to": 2022, "limit": 10, "sort": "title"},
            headers=headers,
        )
        titles = [item["title"].lower() for item in titled.json()["items"]]
        assert titles == sorted(titles)
        cited = client.get(
            "/papers/search",
            params={"q": "reinforcement learning", "mode": "metadata", "sort": "citations", "limit": 5},
            headers=headers,
        )
        assert cited.status_code == 200, cited.text
        counts = [item["citations"] for item in cited.json()["items"]]
        assert counts == sorted(counts, reverse=True)
        assert all(isinstance(count, int) and count >= 0 for count in counts)


def test_unread_only_hides_a_paper_marked_read():
    with session(NoEmbed()) as (client, user_id, _transport):
        settings = get_settings()
        db = FalkorDB(host=settings.falkordb_host, port=settings.falkordb_port, password=settings.falkordb_password or None)
        db.select_graph(graph_name_for(user_id)).query(
            "MERGE (r:Ref {kind: 'paper', ref_id: $id}) SET r.state = 'read'",
            {"id": PAPER},
        )
        headers = auth(user_id, "search@b3.test")
        visible = client.get("/papers/search", params={"q": "defect", "mode": "metadata"}, headers=headers)
        hit = next(item for item in visible.json()["items"] if item["arxiv_id"] == PAPER)
        assert hit["status"] == "read"
        hidden = client.get(
            "/papers/search",
            params={"q": "defect", "mode": "metadata", "unread_only": True},
            headers=headers,
        )
        assert PAPER not in ids(hidden.json())


def test_suggest_and_paper_reads():
    with session(NoEmbed()) as (client, user_id, _transport):
        headers = auth(user_id, "search@b3.test")
        methods = client.get("/vocab/suggest", params={"kind": "method", "q": "SMOTE"}, headers=headers)
        assert methods.status_code == 200, methods.text
        assert any("SMOTE" in item["name"] for item in methods.json()["items"])
        paper = client.get(f"/papers/{PAPER}", headers=headers)
        assert paper.status_code == 200
        assert paper.json()["category"] == "cs.SE"
        sentence = client.get(f"/papers/{PAPER}/sentences", params={"n": 198}, headers=headers)
        assert "repeated structure" in sentence.json()["items"][0]["original"]
        facets = client.get(f"/papers/{PAPER}/facets", headers=headers)
        assert facets.status_code == 200, facets.text
        assert any(item["slug"] == "dataset:82" for item in facets.json()["datasets"])
        neighbors = client.get(f"/papers/{PAPER}/neighbors", headers=headers)
        assert CITED in {item["arxiv_id"] for item in neighbors.json()["cites"]}
        pdf = client.get(f"/papers/{PAPER}/pdf", headers=headers)
        assert pdf.status_code == 200, pdf.text
        assert pdf.json()["url"].startswith("http")
        missing = client.get("/papers/search", params={"mode": "semantic"}, headers=headers)
        assert missing.status_code == 400
