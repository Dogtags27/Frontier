"""HTTP shapes for the health routes."""

from pydantic import BaseModel
from typing import Literal


class CheckBody(BaseModel):
    name: str
    ok: bool
    expected: int | None = None
    actual: int | None = None
    detail: str | None = None


class ReadyBody(BaseModel):
    status: str
    checks: list[CheckBody]


class AgentBody(BaseModel):
    paper_id: str = ""
    note: str = ""
    gap_id: str = ""
    left: str = ""
    right: str = ""


class BootstrapBody(BaseModel):
    role: Literal["student", "supervisor"] = "student"
    display_name: str = ""


class JoinBody(BaseModel):
    code: str


class ReadBody(BaseModel):
    paper_id: str
    depth: Literal["skimmed", "read", "understood"] = "read"
    note: str = ""


class NoteBody(BaseModel):
    text: str


class DecisionBody(BaseModel):
    kind: str
    reason: str = ""
    gap_id: str = ""


class TransitionBody(BaseModel):
    to: Literal["challenged", "alive", "killed", "adopted", "scooped"]
    version: int


class EvidenceBody(BaseModel):
    ref_id: str
    kind: Literal["paper", "claim", "concept"] = "paper"


class HandoffBody(BaseModel):
    gap_id: str
    to_agent: Literal["adversary", "chronicler"]
    from_agent: str = "gaphunter"


class IngestBody(BaseModel):
    arxiv_ids: list[str]


class JobBody(BaseModel):
    type: Literal[
        "map_field",
        "find_gaps",
        "challenge_gap",
        "reassess_gap",
        "write_brief",
        "summarize_turn",
        "ingest_note",
        "resolve_handoff",
    ]
    payload: dict = {}


class GapBody(BaseModel):
    text: str
    task_id: str = ""


class MemoryBody(BaseModel):
    kind: Literal["interest", "belief", "preference", "constraint"] = "belief"
    text: str
    entity: str = ""


class ConversationBody(BaseModel):
    title: str = ""


class TurnBody(BaseModel):
    text: str


class SearchQuery(BaseModel):
    """What a corpus search accepts. Filters apply in every mode."""

    q: str = ""
    mode: Literal["semantic", "metadata", "hybrid"] = "hybrid"
    year_from: int | None = None
    year_to: int | None = None
    category: str = ""
    layer: str = ""
    paper_kind: str = ""
    task: str = ""
    method: str = ""
    dataset: str = ""
    metric: str = ""
    cites: str = ""
    cited_by: str = ""
    unread_only: bool = False
    limit: int = 10
    cursor: int = 0
    sort: Literal["relevance", "year_desc", "year_asc", "title", "citations"] = "relevance"

    def clamped(self) -> "SearchQuery":
        limit = min(max(self.limit, 1), 20)
        cursor = max(self.cursor, 0)
        return self.model_copy(update={"q": self.q.strip(), "limit": limit, "cursor": cursor})

    def has_filters(self) -> bool:
        return any(
            (
                self.year_from is not None,
                self.year_to is not None,
                self.category,
                self.layer,
                self.paper_kind,
                self.task,
                self.method,
                self.dataset,
                self.metric,
                self.cites,
                self.cited_by,
                self.unread_only,
            )
        )
