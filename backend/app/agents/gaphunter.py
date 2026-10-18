"""Rank gaps from the corpus. Detection is graph structure, not a model.

A cell is one task plus one method family. A survey paper does not fill a cell.
Two signals are kept:

- empty_cell: the task and the family both appear in real papers, the family shows
  up beside the task through citations, a shared dataset, a shared metric, or a
  baseline comparison, and no research paper uses that family on that task.
- open_limitation: a failure, limit, assumption, or future-work claim names a
  method on the task, and no later research paper uses that family there.

Every gap that is written is challenged in the same job by the Adversary, so the
student gets verdicts, not a pile of candidates.

Score = neighbor weight * (task breadth + other-task breadth) + evidence weight * claim strength
        - distance weight * how far the cell sits from papers the student has read.
"""

import hashlib
from datetime import datetime, timezone

from app.agents.base import CAVEAT, Agent, answer, as_text
from app.models.queries import Q

CLAIM_WEIGHT = {"failure": 3, "limit": 3, "assumption": 2, "future_work": 1}
CHANNELS = (
    ("citation", Q.CITATION_FAMILIES),
    ("dataset", Q.DATASET_FAMILIES),
    ("metric", Q.METRIC_FAMILIES),
    ("baseline", Q.BASELINE_FAMILIES),
)


def gap_key(task: str, family: str, signal: str) -> str:
    digest = hashlib.sha256(f"{task}|{family}|{signal}".encode()).hexdigest()[:16]
    return f"gap-{digest}"


class GapHunter(Agent):
    name = "gaphunter"
    work_types = ("find_gaps",)

    async def handle(self, ctx, item: dict) -> dict:
        payload = item.get("payload") or {}
        paper_id = str(payload.get("paper_id") or "")
        seeds, origin = await self._seeds(ctx, paper_id)
        ctx.trace.step(
            "seed",
            {"paper_id": paper_id, "note": str(payload.get("note") or "")[:120]},
            f"{len(seeds)} tasks from {origin}" if seeds else "no tasks found",
        )
        if not seeds:
            body = answer(
                "I could not find a task to search around. Open a paper that has been processed, or tell me a topic, and I will search from there.",
                [],
                ctx.trace,
                [CAVEAT],
            )
            await self._remember(ctx, payload, body)
            return body
        ranked = await self._rank(ctx, seeds)
        ctx.trace.step("rank", {"tasks": [row["slug"] for row in seeds]}, f"{len(ranked)} gaps cleared the bar")
        written = []
        for candidate in ranked:
            saved = await self._write(ctx, candidate)
            if saved:
                written.append(saved)
        await self._review(ctx, written)
        written.sort(key=_order)
        body = answer(_report(origin, written, bool(ranked)), [_evidence(row) for row in written], ctx.trace, [CAVEAT])
        body["gaps"] = [{"id": row["id"], "status": row["status"], "reason": row.get("reason", "")} for row in written]
        await self._remember(ctx, payload, body)
        return body

    async def _remember(self, ctx, payload: dict, body: dict) -> None:
        conversation_id = str(payload.get("conversation_id") or "")
        if not conversation_id or ctx.memory is None:
            return
        try:
            await ctx.memory.add_chat_turn(ctx.workspace, conversation_id, "assistant", body["text"], body["evidence"], "gap_result")
        except Exception:
            return

    async def _seeds(self, ctx, paper_id: str) -> tuple[list[dict], str]:
        if paper_id:
            found = await self._tasks_of(ctx, paper_id)
            if found:
                return found, found[0]["title"] or paper_id
        reads = (await self._reads(ctx))[:6]
        seeds: dict[str, dict] = {}
        for read in reads:
            for row in await self._tasks_of(ctx, read):
                seeds.setdefault(row["slug"], row)
        return list(seeds.values())[:8], "your reading"

    async def _tasks_of(self, ctx, paper_id: str) -> list[dict]:
        rows = await ctx.read_corpus(Q.PAPER_TASKS, {"id": paper_id})
        return [
            {"slug": as_text(row[0]), "name": as_text(row[1]), "year": int(row[2] or 0), "title": as_text(row[3])}
            for row in rows
        ]

    async def _review(self, ctx, written: list[dict]) -> None:
        """Challenge every new gap right away, so nothing waits on the student to ask."""
        from app.agents.adversary import Adversary

        judge = Adversary()
        for row in written:
            if row.get("existing"):
                continue
            try:
                handoff = await ctx.gaps.open_handoff(ctx.workspace, row["id"], "adversary", self.name)
                result = await judge.handle(ctx, {"payload": {"gap_id": row["id"], "handoff_id": handoff["id"]}})
            except Exception:
                row["reason"] = "The check did not finish. Ask me to challenge this gap again."
                continue
            row["status"] = result.get("status") or row["status"]
            row["reason"] = result.get("text") or ""
        ctx.trace.step(
            "challenge",
            {"gaps": len(written)},
            f"{sum(1 for row in written if row['status'] == 'alive')} alive, {sum(1 for row in written if row['status'] == 'killed')} killed",
        )
    async def _rank(self, ctx, seeds: list[dict]) -> list[dict]:
        tasks = [row["slug"] for row in seeds]
        names = {row["slug"]: row["name"] for row in seeds}
        occupied = await self._occupied(ctx, tasks)
        breadth = await self._breadth(ctx, tasks)
        support = await self._support(ctx, tasks)
        pairs = [
            {"task": task, "family": family}
            for (task, family) in support
            if family not in occupied.get(task, set()) and breadth.get(task, 0) >= ctx.settings.gap_min_support
        ]
        others = await self._other_tasks(ctx, pairs)
        limitations = await self._limitations(ctx, tasks, names)
        reads = await self._reads(ctx)
        candidates = []
        for (task, family), channels in support.items():
            if family in occupied.get(task, set()):
                continue
            if breadth.get(task, 0) < ctx.settings.gap_min_support:
                continue
            other = others.get((task, family), 0)
            if other < ctx.settings.gap_min_support:
                continue
            distance = await self._distance(ctx, task, reads)
            neighbor = breadth[task] + other
            score = _score(ctx, neighbor, max(channels.values()), distance)
            candidates.append(
                _candidate(
                    task,
                    names.get(task, task),
                    family,
                    "empty_cell",
                    score,
                    distance,
                    0,
                    (
                        f"No paper in this corpus applies {family} to {names.get(task, task)}. "
                        f"{family} is used on {other} other tasks, "
                        f"linked here through {', '.join(sorted(channels))}."
                    ),
                )
            )
        for limit in limitations:
            if breadth.get(limit["task"], 0) < ctx.settings.gap_min_support:
                continue
            if await self._revisited(ctx, limit):
                continue
            distance = await self._distance(ctx, limit["task"], reads)
            other = others.get((limit["task"], limit["family"]), 0)
            score = _score(ctx, breadth[limit["task"]] + other, limit["weight"], distance)
            candidates.append(limit | {"score": round(score, 3), "distance": distance})
        candidates.sort(key=lambda row: (-row["score"], row["id"]))
        return candidates[: ctx.settings.gap_result_limit]

    async def _occupied(self, ctx, tasks: list[str]) -> dict[str, set]:
        rows = await ctx.read_corpus(Q.OCCUPIED_FAMILIES, {"tasks": tasks})
        return {as_text(row[0]): {as_text(family) for family in row[1] or []} for row in rows}

    async def _breadth(self, ctx, tasks: list[str]) -> dict[str, int]:
        rows = await ctx.read_corpus(Q.TASK_BREADTH, {"tasks": tasks})
        return {as_text(row[0]): int(row[1] or 0) for row in rows}

    async def _support(self, ctx, tasks: list[str]) -> dict[tuple[str, str], dict]:
        found: dict[tuple[str, str], dict] = {}
        for channel, query in CHANNELS:
            rows = await ctx.read_corpus(query, {"tasks": tasks})
            for row in rows:
                key = (as_text(row[0]), as_text(row[1]))
                found.setdefault(key, {})[channel] = int(row[2] or 0)
        return found

    async def _other_tasks(self, ctx, pairs: list[dict]) -> dict[tuple[str, str], int]:
        if not pairs:
            return {}
        rows = await ctx.read_corpus(Q.FAMILY_OTHER_TASKS, {"pairs": pairs})
        return {(as_text(row[0]), as_text(row[1])): int(row[2] or 0) for row in rows}

    async def _limitations(self, ctx, tasks: list[str], names: dict[str, str]) -> list[dict]:
        rows = await ctx.read_corpus(
            Q.OPEN_LIMITATIONS,
            {"tasks": tasks, "kinds": list(CLAIM_WEIGHT)},
        )
        best: dict[tuple[str, str], dict] = {}
        for row in rows:
            task, family, kind = as_text(row[0]), as_text(row[2]), as_text(row[3])
            weight = CLAIM_WEIGHT.get(kind, 0)
            key = (task, family)
            current = best.get(key)
            if current and current["weight"] >= weight:
                continue
            label = as_text(row[5])[:160]
            best[key] = _candidate(
                task,
                names.get(task, as_text(row[1])),
                family,
                "open_limitation",
                0,
                0,
                int(row[8] or 0),
                f"A {kind.replace('_', ' ')} on {family} is still open for {names.get(task, task)}: {label}",
                claim_id=as_text(row[4]),
                paper_id=as_text(row[7]),
                weight=weight,
            )
        return list(best.values())

    async def _revisited(self, ctx, limit: dict) -> bool:
        rows = await ctx.read_corpus(
            Q.LATER_PAPERS,
            {"task": limit["task"], "family": limit["family"], "year": limit["year"]},
        )
        return bool(rows)

    async def _reads(self, ctx) -> list[str]:
        rows = await ctx.workspace.query(Q.READ_IDS)
        return [as_text(row[0]) for row in rows if row[0]]

    async def _distance(self, ctx, task: str, reads: list[str]) -> int:
        if not reads:
            return 0
        direct = await ctx.read_corpus(Q.READS_ON_TASK, {"reads": reads, "task": task})
        if direct and int(direct[0][0] or 0) > 0:
            return 0
        beside = await ctx.read_corpus(Q.READS_BESIDE_TASK, {"reads": reads, "task": task})
        if beside and int(beside[0][0] or 0) > 0:
            return 1
        return 2

    async def _write(self, ctx, candidate: dict) -> dict | None:
        method = ""
        found = await ctx.read_corpus(Q.METHOD_FOR_FAMILIES, {"families": [candidate["family"]]})
        if found:
            method = as_text(found[0][1])
        at = datetime.now(timezone.utc).isoformat()
        rows = await ctx.workspace.query(
            Q.SAVE_GAP,
            {
                "id": candidate["id"],
                "at": at,
                "task": candidate["task"],
                "family": candidate["family"],
                "method": method,
                "score": candidate["score"],
                "text": candidate["text"][:400],
                "signal": candidate["signal"],
                "year": candidate["year"],
                "event_id": f"opened-{candidate['id']}",
            },
        )
        if not rows:
            known = await ctx.workspace.query(Q.GAP_SIGNAL, {"id": candidate["id"]})
            if not known:
                return None
            attempts = await ctx.workspace.query(Q.GAP_ATTEMPTS, {"id": candidate["id"]})
            reason = as_text(attempts[-1][1]) if attempts else ""
            return candidate | {"status": as_text(known[0][1]), "existing": True, "reason": reason}
        await ctx.gaps.note_cell(ctx.workspace.name, candidate["task"], method, candidate["family"], True)
        evidence = await self._attach(ctx, candidate)
        row = candidate | {"status": as_text(rows[0][1]), "version": int(rows[0][2] or 1), "evidence": evidence}
        if len(evidence) < 2:
            row["existing"] = True
            row["reason"] = "Only one supporting paper was found, so I have not challenged this yet."
        return row

    async def _attach(self, ctx, candidate: dict) -> list[dict]:
        refs = []
        if candidate.get("paper_id"):
            refs.append(("paper", candidate["paper_id"]))
        if candidate.get("claim_id"):
            refs.append(("claim", candidate["claim_id"]))
        papers = await ctx.read_corpus(Q.TASK_PAPERS, {"task": candidate["task"]})
        for row in papers:
            refs.append(("paper", as_text(row[0])))
        elsewhere = await ctx.read_corpus(
            Q.FAMILY_ELSEWHERE,
            {"family": candidate["family"], "task": candidate["task"]},
        )
        for row in elsewhere:
            refs.append(("paper", as_text(row[0])))
        kept = []
        seen = set()
        for kind, ref_id in refs:
            if not ref_id or (kind, ref_id) in seen:
                continue
            seen.add((kind, ref_id))
            await ctx.gaps.add_evidence(ctx.workspace, candidate["id"], ref_id, kind)
            kept.append({"ref_type": kind, "ref_id": ref_id})
            if len(kept) == 3:
                break
        return kept


def _score(ctx, neighbor: float, evidence: float, distance: int) -> float:
    settings = ctx.settings
    value = (
        settings.gap_neighbor_weight * neighbor
        + settings.gap_evidence_weight * evidence
        - settings.gap_distance_weight * distance
    )
    return round(value, 3)


def _candidate(task, name, family, signal, score, distance, year, text, claim_id="", paper_id="", weight=0) -> dict:
    return {
        "id": gap_key(task, family, signal),
        "task": task,
        "task_name": name,
        "family": family,
        "signal": signal,
        "score": score,
        "distance": distance,
        "year": year,
        "text": text,
        "claim_id": claim_id,
        "paper_id": paper_id,
        "weight": weight,
    }


STATUS_ORDER = {"alive": 0, "challenged": 1, "candidate": 2, "adopted": 3, "killed": 4, "scooped": 5}


def _order(row: dict):
    return (STATUS_ORDER.get(row["status"], 6), -(row["score"] or 0), row["id"])


def _label(row: dict) -> str:
    if row["signal"] == "empty_cell":
        return f"{row['family']} for {row['task_name']}"[:100]
    return row["text"][:110]


def _evidence(row: dict) -> dict:
    return {
        "ref_type": "gap",
        "ref_id": row["id"],
        "title": _label(row),
        "status": row["status"],
        "signal": row["signal"],
        "score": row["score"],
    }


def _report(origin: str, rows: list[dict], searched: bool) -> str:
    where = f" around {origin}" if origin else ""
    if not rows:
        if searched:
            return f"I searched{where} and nothing cleared the bar. The corpus may be thin there, so try a broader topic or read a few more papers first."
        return f"I searched{where} and found no task and method pairing that the surrounding papers support."
    alive = [row for row in rows if row["status"] == "alive"]
    killed = [row for row in rows if row["status"] == "killed"]
    pending = [row for row in rows if row["status"] in {"candidate", "challenged"}]
    noun = "gap" if len(rows) == 1 else "gaps"
    head = f"I found {len(rows)} possible {noun}{where} and challenged each one against the corpus."
    parts = [head]
    if alive:
        parts.append(f"{len(alive)} still hold up:")
        for index, row in enumerate(alive[:4], 1):
            parts.append(f"{index}. {_label(row)}. {row.get('reason', '')}".strip())
    else:
        parts.append("None of them held up.")
    if killed:
        names = "; ".join(_label(row) for row in killed[:3])
        parts.append(f"{len(killed)} ruled out because the work already exists: {names}.")
    if pending:
        parts.append(f"{len(pending)} could not be challenged yet and stay as candidates.")
    parts.append("Ask me to plan an experiment for the first one, or open Open questions to see every check.")
    return "\n".join(parts)
