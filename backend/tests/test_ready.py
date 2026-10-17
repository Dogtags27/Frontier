"""Count comparison does not need the stores. The live check does."""

import json

from fastapi.testclient import TestClient

from app.constants import REPO, database_url
from app.ready import compare, expected_counts


def test_database_url_adds_sslmode():
    assert database_url("postgresql://frontier@localhost:5432/frontier").endswith("sslmode=disable")
    assert "sslmode=require" in database_url("postgresql://frontier@db.example:5432/frontier")
    assert database_url("postgresql://frontier@db.example/frontier?sslmode=require").count("sslmode") == 1


def test_expected_counts_follow_the_manifest():
    manifest = json.loads((REPO / "data" / "extract" / "manifest.json").read_text(encoding="utf-8"))
    expected = expected_counts(manifest)
    assert expected["graph_papers"] == 997
    assert expected["pg_papers"] == 997
    assert expected["sentences"] == 658126
    assert expected["claim_vectors"] == 26346
    assert expected["corpus_private_nodes"] == 0
    assert expected["graph_foundation"] + expected["graph_recent"] == expected["graph_papers"]


def test_compare_flags_a_mismatch():
    checks = compare({"papers": 2}, {"papers": 1})
    assert checks[0].ok is False
    assert checks[0].actual == 1


def test_health_and_ready_against_live_stores():
    from app.main import create_app

    with TestClient(create_app()) as client:
        health = client.get("/healthz")
        assert health.status_code == 200
        assert health.json() == {"status": "ok"}
        ready = client.get("/readyz")
        body = ready.json()
        assert ready.status_code == 200, body
        assert body["status"] == "ready"
        assert all(item["ok"] for item in body["checks"])
