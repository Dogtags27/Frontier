"""Try to kill a gap with several independent corpus checks, and record each one.

A gap survives only if every check comes back empty. A near miss is recorded and
does not kill it. Each check is stored as its own attempt so the student can read
exactly what was tried and what it found.
"""

import uuid
from datetime import datetime, timezone

from pydantic import BaseModel, Field

from app.agents.base import CAVEAT, Agent, answer, as_text
from app.core import NotFound
from app.models.schemas import SearchQuery
from app.models.queries import Q

FINAL = {"alive", "killed", "adopted", "scooped"}


class Adversary(Agent):
    name = "adversary"
    work_types = ("challenge_gap",)

    async def handle(self, ctx, item: dict) -> dict:
        payload = item.get("payload") or {}
        gap_id = str(payload.get("gap_id") or "")
        if not gap_id:
            raise NotFound("not found")
        gate = await self._gate(ctx, str(payload.get("handoff_id") or ""))
        if gate and gate["status"] == "blocked":
            ctx.trace.step("handoff", {"id": gate["id"]}, gate["reason"])
            return answer(gate["reason"], [], ctx.trace, [CAVEAT]) | {"status": "blocked", "gap_id": gap_id}
        gap = await self._load(ctx, gap_id)
        if gap["status"] in FINAL:
            return answer(f"Gap is already {gap['status']}.", [], ctx.trace, [CAVEAT]) | {"status": gap["status"], "gap_id": gap_id}
        if gap["status"] == "candidate":
            moved = await ctx.gaps.transition(ctx.workspace, gap_id, "challenged", gap["version"])
            gap["version"] = moved["version"]
            gap["status"] = moved["status"]
        verdict, checks, papers = await self._judge(ctx, gap)
        for check in checks:
            await ctx.workspace.query(
                Q.RECORD_ATTEMPT,
                {
                    "gap_id": gap_id,
                    "id": str(uuid.uuid4()),
                    "at": datetime.now(timezone.utc).isoformat(),
                    "query": check["name"],
                    "result": check["result"],
                    "reason": check["reason"][:400],
                },
            )
        final = await ctx.gaps.transition(ctx.workspace, gap_id, verdict, gap["version"])
        reason = _reason(verdict, checks)
        ctx.trace.step("judge", {"signal": gap["signal"], "task": gap["task"], "family": gap["family"]}, reason, papers)
        return answer(
            reason,
            [{"ref_type": "paper", "ref_id": paper, "title": ""} for paper in papers],
            ctx.trace,
            [CAVEAT],
        ) | {"status": final["status"], "version": final["version"], "gap_id": gap_id, "checks": checks}

    async def _gate(self, ctx, handoff_id: str) -> dict | None:
        if not handoff_id:
            return None
        return await ctx.gaps.resolve(ctx.workspace, handoff_id)

    async def _load(self, ctx, gap_id: str) -> dict:
        rows = await ctx.workspace.query(Q.GAP_SIGNAL, {"id": gap_id})
        if not rows:
            raise NotFound("not found")
        row = rows[0]
        return {
            "id": as_text(row[0]),
            "status": as_text(row[1]),
            "version": int(row[2] or 1),
            "task": as_text(row[3]),
            "family": as_text(row[4]),
            "signal": as_text(row[5]),
            "text": as_text(row[6]),
            "year": int(row[7] or 0),
            "score": row[8],
        }

    async def _judge(self, ctx, gap: dict) -> tuple[str, list[dict], list[str]]:
        if not gap["task"] or not gap["family"]:
            return "alive", [_check("scope", "found_nothing", "The gap names no task and method family, so there was nothing to check.")], []
        checks: list[dict] = []
        if gap["signal"] == "open_limitation":
            later = await ctx.read_corpus(
                Q.LATER_PAPERS,
                {"task": gap["task"], "family": gap["family"], "year": gap["year"]},
            )
            papers = [as_text(row[0]) for row in later]
            if papers:
                checks.append(_check("later_work", "killed", f"A later paper uses this family on the task: {', '.join(papers)}.", papers))
                return "killed", checks, papers
            checks.append(_check("later_work", "found_nothing", "No later research paper revisits this limitation."))
        else:
            cell = await ctx.read_corpus(Q.CELL_PAPERS, {"task": gap["task"], "family": gap["family"]})
            papers = [as_text(row[0]) for row in cell]
            if papers:
                checks.append(_check("occupancy", "killed", f"The cell is already occupied by {', '.join(papers)}.", papers))
                return "killed", checks, papers
            checks.append(_check("occupancy", "found_nothing", "No tagged paper uses this method on this task."))

        needle = gap["family"].replace("_", " ").replace("-", " ").strip().lower()
        titled = await ctx.read_corpus(Q.TITLE_PRIOR, {"task": gap["task"], "needle": needle})
        named = [as_text(row[0]) for row in titled]
        if named:
            titles = "; ".join(as_text(row[1]) for row in titled[:2])
            checks.append(
                _check(
                    "prior_art",
                    "killed",
                    f"A paper on this task names the method in its title, so extraction probably missed it: {titles}.",
                    named,
                )
            )
            return "killed", checks, named
        checks.append(_check("prior_art", "found_nothing", "No paper on this task names the method in its title."))

        stats = await ctx.read_corpus(Q.CELL_STATS, {"task": gap["task"], "family": gap["family"]})
        on_task = int(stats[0][0] or 0) if stats else 0
        elsewhere = int(stats[0][1] or 0) if stats else 0
        nearby = await ctx.read_corpus(Q.TASK_PAPERS, {"task": gap["task"]})
        titles = [as_text(row[1]) for row in nearby[:2] if row[1]]
        reason = f"{on_task} papers address the task and {elsewhere} use the method elsewhere, but none join them."
        if titles:
            reason += " Closest work on the task: " + "; ".join(titles) + "."
        checks.append(_check("adjacency", "near_miss", reason))
        return "alive", checks, []


class Relation(BaseModel):
    id: str
    relation: str = "related"
    why: str = ""


class IdeaVerdict(BaseModel):
    verdict: str = "open"
    summary: str = ""
    papers: list[Relation] = Field(default_factory=list)


IDEA_RULES = (
    "You are a sceptical reviewer checking whether a research idea is already published. "
    "You are given the idea and candidate papers from a corpus, each with an abstract. "
    "Judge only from those abstracts. For each paper say how it relates to the idea: "
    "same (it does this), overlaps (it does a large part of this), related (same area, different contribution), "
    "or unrelated. Then give a verdict: done if some paper is the same, partly_done if papers overlap, "
    "open if nothing overlaps. The summary is two plain sentences that name the closest paper by title and say "
    "what is still unclaimed. A corpus is limited, so never claim novelty as a fact. "
    "Reply with JSON: verdict, summary, papers (list of id, relation, why in one sentence)."
)


async def check_idea(ctx, idea: str, candidates: list[dict]) -> dict:
    """Ask the model to judge each candidate against the idea. The corpus supplies every fact."""
    listing = "\n\n".join(
        f"[{item['arxiv_id']}] {item['title']} ({item.get('year') or 'n.d.'})\n{(item.get('abstract') or '')[:600]}"
        for item in candidates
    )
    verdict = await ctx.llm.structured(
        ctx.principal,
        [
            {"role": "system", "content": IDEA_RULES},
            {"role": "user", "content": f"<idea>\n{idea[:600]}\n</idea>\n<candidates>\n{listing}\n</candidates>"},
        ],
        IdeaVerdict,
        max_tokens=700,
    )
    known = {item["arxiv_id"] for item in candidates}
    relations = [item for item in verdict.papers if item.id in known]
    kind = verdict.verdict if verdict.verdict in {"done", "partly_done", "open"} else "open"
    ctx.trace.step("judge_idea", {"candidates": len(candidates)}, f"{kind}: {verdict.summary}"[:180])
    return {"verdict": kind, "summary": verdict.summary, "relations": relations}


async def candidates_for(ctx, text: str, limit: int = 6) -> list[dict]:
    """Closest corpus papers to a piece of text, each with its abstract."""
    found = await ctx.search.search(ctx.principal, SearchQuery(q=text[:300], mode="hybrid", limit=limit))
    out = []
    for item in (found.get("items") or [])[:5]:
        try:
            paper = await ctx.papers.get(item["arxiv_id"])
        except Exception:
            continue
        out.append({"arxiv_id": paper["arxiv_id"], "title": paper["title"], "year": paper["year"], "abstract": paper.get("abstract") or ""})
    return out


async def apply_verdict(ctx, gap_id: str, verdict: dict, candidates: list[dict]) -> dict:
    """Write an idea review onto a gap as one recorded check and move the gap to its verdict."""
    adversary = Adversary()
    gap = await adversary._load(ctx, gap_id)
    if gap["status"] in FINAL:
        return {"status": gap["status"], "summary": verdict["summary"], "gap_id": gap_id}
    if gap["status"] == "candidate":
        moved = await ctx.gaps.transition(ctx.workspace, gap_id, "challenged", gap["version"])
        gap["version"] = moved["version"]
    titles = {item["arxiv_id"]: item["title"] for item in candidates}
    close = [item for item in verdict["relations"] if item.relation in {"same", "overlaps"}]
    papers = [item.id for item in close]
    reason = verdict["summary"] or "No overlapping paper was found in the corpus."
    if close:
        reason += " Closest: " + "; ".join(f"{titles.get(item.id, item.id)} ({item.relation})" for item in close[:2]) + "."
    result = {"done": "killed", "partly_done": "near_miss"}.get(verdict["verdict"], "found_nothing")
    await ctx.workspace.query(
        Q.RECORD_ATTEMPT,
        {
            "gap_id": gap_id,
            "id": str(uuid.uuid4()),
            "at": datetime.now(timezone.utc).isoformat(),
            "query": "idea_review",
            "result": result,
            "reason": reason[:400],
        },
    )
    final = await ctx.gaps.transition(ctx.workspace, gap_id, "killed" if result == "killed" else "alive", gap["version"])
    ctx.trace.step("judge", {"signal": "idea_review"}, reason, papers)
    return {"status": final["status"], "summary": reason, "gap_id": gap_id, "papers": papers}


async def review_text_gap(ctx, gap_id: str) -> dict:
    """The Adversary's review of a gap the student wrote in plain words. No task or method tags are needed."""
    gap = await Adversary()._load(ctx, gap_id)
    if gap["status"] in FINAL:
        return {"status": gap["status"], "summary": f"Gap is already {gap['status']}.", "gap_id": gap_id}
    candidates = await candidates_for(ctx, gap["text"])
    if not candidates:
        verdict = {"verdict": "open", "summary": "No paper in the corpus comes close to this.", "relations": []}
    else:
        try:
            verdict = await check_idea(ctx, gap["text"], candidates)
        except Exception:
            return {"status": gap["status"], "summary": "The review did not finish. Run the checks again.", "gap_id": gap_id, "unfinished": True}
    return await apply_verdict(ctx, gap_id, verdict, candidates)



def _check(name: str, result: str, reason: str, papers: list[str] | None = None) -> dict:
    return {"name": name, "result": result, "reason": reason, "papers": papers or []}


def _reason(verdict: str, checks: list[dict]) -> str:
    if verdict == "killed":
        return checks[-1]["reason"]
    near = [check for check in checks if check["result"] == "near_miss"]
    held = f"Survived {len(checks)} checks."
    return f"{held} {near[0]['reason']}" if near else held
