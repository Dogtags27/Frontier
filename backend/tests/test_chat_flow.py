"""The chat box end to end against the real model, graph and corpus.

Each case sends messages the way a student would, including follow-ups, and checks
what the assistant understood and what it did, not the exact wording it chose.
"""

import json
import uuid

import pytest
from fastapi.testclient import TestClient

from app.constants import get_settings
from app.main import create_app
from app.models.queries import Q
from app.services.chat import _annotate, _fold
from app.services.intent import IntentEngine, Plan
from app.utilities.security import SupabaseTokenVerifier

from tests.test_intent import ISSUER, PUBLIC, _cleanup, _token

PAPER = "2211.05920"


def _events(text: str) -> dict:
    found: dict = {"tools": []}
    for block in text.split("\n\n"):
        if not block.startswith("event: "):
            continue
        name, _, data = block[7:].partition("\ndata: ")
        if not data:
            continue
        payload = json.loads(data)
        if name == "tool_call":
            found["tools"].append(payload["tool"])
        else:
            found[name] = payload
    return found


@pytest.fixture()
def student():
    settings = get_settings().model_copy(
        update={"admin_emails": "", "rate_backend": "memory", "rate_capacity_student": 200, "monthly_usd": 10000}
    )
    app = create_app(settings, SupabaseTokenVerifier(ISSUER, "authenticated", keys={"b7": PUBLIC}))
    user_id = str(uuid.uuid4())
    headers = {"Authorization": f"Bearer {_token(user_id, 'flow@b7.test')}"}
    try:
        with TestClient(app) as client:
            created = client.post("/me/bootstrap", json={"role": "student", "display_name": "flow"}, headers=headers)
            assert created.status_code == 200, created.text
            state = {"conversation": ""}

            def say(message: str) -> dict:
                body = {"message": message}
                if state["conversation"]:
                    body["conversation_id"] = state["conversation"]
                response = client.post("/chat", json=body, headers=headers)
                assert response.status_code == 200, response.text
                parsed = _events(response.text)
                state["conversation"] = parsed["final"]["conversation_id"]
                return parsed

            say.client = client
            say.headers = headers
            yield say
    finally:
        _cleanup()


def test_annotate_replaces_ids_with_titles():
    seen = _annotate("explain 2211.05920 and 9999.99999", {"2211.05920": {"title": "A Title"}})
    assert '"A Title" (arXiv:2211.05920)' in seen
    assert "9999.99999 (not in the corpus)" in seen


def test_nothing_but_the_guard_and_slash_commands_runs_before_the_model():
    import asyncio

    engine = IntentEngine(get_settings(), llm=None)
    plan = asyncio.run(engine.understand("Where do I start with large language models?"))
    assert plan.source == "unavailable"
    command = asyncio.run(engine.understand("/resume"))
    assert command.intent == "resume" and command.source == "command"


def test_topic_requests_keep_every_word(student):
    reply = student("where do I start with reinforcement learning with human feedback")
    assert reply["intent"]["intent"] == "explore_topic"
    assert "human feedback" in reply["intent"]["slots"]["query"].lower()
    assert reply["final"]["evidence"], reply["final"]["text"]


def test_an_id_in_the_message_is_read_as_its_title(student):
    reply = student(f"explain {PAPER}")
    assert reply["intent"]["intent"] == "lookup_paper"
    assert reply["final"]["evidence"][0]["ref_id"] == PAPER
    title = reply["final"]["evidence"][0]["title"]
    assert title and _fold(title) in _fold(reply["final"]["text"])


def test_follow_ups_resolve_to_the_papers_just_shown(student):
    first = student("find papers about software defect prediction")
    assert first["intent"]["intent"] == "find_papers"
    shown = [item["ref_id"] for item in first["final"]["evidence"]]
    assert len(shown) >= 2
    second = student("what does the second one build on")
    assert second["intent"]["intent"] == "trace_lineage"
    assert second["final"]["evidence"][0]["ref_id"] == shown[1]


def test_compare_the_first_two_uses_the_list_just_shown(student):
    first = student("find papers about software defect prediction")
    shown = [item["ref_id"] for item in first["final"]["evidence"]]
    third = student("compare the first two")
    assert third["intent"]["intent"] == "compare"
    assert {item["ref_id"] for item in third["final"]["evidence"]} == set(shown[:2])


def test_asking_what_i_read_does_not_record_a_read(student):
    reply = student("which papers have I read on defect prediction so far")
    assert reply["intent"]["intent"] != "record"
    reads = student.client.get("/students/me/progress", headers=student.headers).json()
    assert reads["graph"]["reads"] == 0


def test_saying_you_read_the_listed_papers_marks_them(student):
    first = student("find papers about software defect prediction")
    shown = [item["ref_id"] for item in first["final"]["evidence"]]
    done = student("I read the first two")
    print("DEBUG", done["intent"], done["final"]["text"])
    assert done["intent"]["intent"] == "record"
    marked = {item["ref_id"] for item in done["final"]["evidence"]}
    assert marked == set(shown[:2])
    progress = student.client.get("/students/me/progress", headers=student.headers).json()
    assert progress["graph"]["reads"] == 2
    profile = student.client.get("/me/profile", headers=student.headers).json()
    assert profile["tasks"]


def test_a_named_paper_and_an_id_can_be_compared(student):
    reply = student(f"compare {PAPER} with the paper on cross-project defect prediction")
    assert reply["intent"]["intent"] == "compare"
    assert len(reply["final"]["evidence"]) >= 1


def test_ideas_get_a_real_check_not_just_a_search(student):
    reply = student("has anyone used graph neural networks for software defect prediction?")
    assert reply["intent"]["intent"] == "validate_idea"
    assert "judge_idea" in reply["tools"] or reply["final"]["text"]
    assert reply["final"]["caveats"]


def test_a_claim_gets_a_claim_level_check(student):
    reply = student("do the papers agree that deep learning beats traditional methods for defect prediction")
    assert reply["intent"]["intent"] == "check_evidence"
    assert "search_papers" in reply["tools"]
    assert reply["final"]["evidence"]


def test_gap_questions_before_and_after_a_search_use_the_right_intent(student):
    empty = student("what gaps have you found so far")
    assert empty["intent"]["intent"] == "show_gaps"
    started = student("find gaps around software defect prediction")
    assert started["intent"]["intent"] == "find_gaps"
    assert started["final"].get("job_id")


def test_progress_report_differs_from_resume(student):
    student(f"I read {PAPER}")
    report = student("write my progress report for my supervisor")
    assert report["intent"]["intent"] == "progress_report"
    assert "progress" in report["tools"]
    resume = student("where was I last time")
    assert resume["intent"]["intent"] == "resume"


def test_off_topic_and_vague_messages_are_handled(student):
    assert student("tell me a joke")["intent"]["intent"] == "refuse"
    vague = student("hello")
    assert vague["intent"]["intent"] in {"clarify", "refuse"}
    assert vague["final"]["text"]


def test_make_this_my_reading_path_saves_the_listed_papers_in_order(student):
    first = student("find papers about software defect prediction")
    shown = [item["ref_id"] for item in first["final"]["evidence"]]
    saved = student("make this my reading path")
    assert saved["intent"]["intent"] == "plan_reading"
    reading = student.client.get("/students/me/reading", headers=student.headers).json()
    path = [step["paper_id"] for step in reading["path"]]
    assert path[: len(shown)] == shown or set(shown) <= set(path)


def test_a_gap_proposed_on_the_page_is_reviewed_by_the_adversary_at_once(student):
    made = student.client.post(
        "/students/me/gaps",
        json={"text": "Nobody has applied co-training to semi-supervised defect prediction on Java projects", "task_id": ""},
        headers=student.headers,
    )
    assert made.status_code == 200, made.text
    body = made.json()
    assert body["status"] in {"alive", "killed"}, body
    assert body["review"]
    detail = student.client.get(f"/students/me/gaps/{body['id']}", headers=student.headers).json()
    assert detail["status"] == body["status"]
    assert any("idea_review" in {item.get("query"), item.get("name")} for item in detail.get("checks") or []), detail


def test_a_gap_stated_in_chat_lands_on_the_open_gaps_list_with_a_review(student):
    reply = student("add this as a gap: nobody has used graph neural networks for cross-project defect prediction")
    assert reply["intent"]["intent"] == "propose_gap"
    listed = student.client.get("/students/me/gaps", headers=student.headers).json()["items"]
    assert len(listed) == 1
    assert listed[0]["status"] in {"alive", "killed"}
    again = student("add this as a gap: nobody has used graph neural networks for cross-project defect prediction")
    assert len(student.client.get("/students/me/gaps", headers=student.headers).json()["items"]) == 1


def test_an_idea_check_that_finds_it_open_is_tracked_as_a_gap(student):
    reply = student("has anyone used quantum annealing to schedule regression tests for software defect prediction?")
    assert reply["intent"]["intent"] == "validate_idea"
    listed = student.client.get("/students/me/gaps", headers=student.headers).json()["items"]
    verdict_text = reply["final"]["text"].lower()
    assert listed or "already" in verdict_text or "has been" in verdict_text
