"""The smallest experiment for one open gap, using only setups already in the corpus."""

from datetime import datetime, timezone

from app.agents.base import Agent, answer, as_text
from app.models.queries import Q

OPENABLE = {"candidate", "challenged", "alive"}


class Scoper(Agent):
    name = "scoper"
    work_types = ("plan_experiment",)

    async def handle(self, ctx, item: dict) -> dict:
        payload = item.get("payload") or {}
        gap = await self._gap(ctx, str(payload.get("gap_id") or ""))
        if gap is None:
            return answer("Name a gap, or ask me to find one first.", [], ctx.trace)
        if gap["status"] not in OPENABLE:
            return answer(f"That gap is {gap['status']}, so there is no experiment to plan.", [], ctx.trace)
        if gap["evidence"] < 1:
            return answer("Add evidence to that gap before planning an experiment.", [], ctx.trace)
        ctx.trace.step("scope_gap", {"gap_id": gap["id"]}, gap["text"][:180] or gap["id"])
        dataset = await self._one(ctx, Q.TASK_DATASET, {"task": gap["task"]})
        metric = await self._one(ctx, Q.TASK_METRIC, {"task": gap["task"]})
        if dataset is None or metric is None:
            return answer(
                "This corpus has no dataset and metric already used on that task, so I will not invent one.",
                [{"ref_type": "gap", "ref_id": gap["id"], "title": gap["text"]}],
                ctx.trace,
            )
        baseline = await self._one(ctx, Q.TASK_BASELINE, {"task": gap["task"], "family": gap["family"]})
        summary = _summary(gap, dataset, metric, baseline)
        await self._write(ctx, gap["id"], summary, dataset, metric, baseline)
        ctx.trace.step("playbook", {"gap_id": gap["id"]}, summary[:180])
        evidence = [
            {"ref_type": "dataset", "ref_id": dataset["id"], "title": dataset["name"]},
            {"ref_type": "metric", "ref_id": metric["id"], "title": metric["name"]},
            {"ref_type": "paper", "ref_id": dataset["paper"], "title": ""},
        ]
        if baseline:
            evidence.append({"ref_type": "method", "ref_id": baseline["id"], "title": baseline["name"]})
        return answer(summary, evidence, ctx.trace)

    async def _gap(self, ctx, gap_id: str) -> dict | None:
        if gap_id:
            rows = await ctx.workspace.query(Q.SCOPE_GAP, {"id": gap_id})
        else:
            rows = await ctx.workspace.query(Q.OPEN_GAPS)
            rows = [row for row in rows if int(row[5] or 0) >= 1]
            rows.sort(key=lambda row: ({"alive": 0, "challenged": 1}.get(as_text(row[1]), 2), -(row[2] or 0), as_text(row[0])))
            if not rows:
                return None
            gap_id = as_text(rows[0][0])
            rows = await ctx.workspace.query(Q.SCOPE_GAP, {"id": gap_id})
        if not rows:
            return None
        row = rows[0]
        return {
            "id": as_text(row[0]),
            "status": as_text(row[1]),
            "task": as_text(row[2]),
            "family": as_text(row[3]),
            "text": as_text(row[4]),
            "evidence": int(row[5] or 0),
        }

    async def _one(self, ctx, query: str, params: dict) -> dict | None:
        rows = await ctx.read_corpus(query, params)
        if not rows or not rows[0][0]:
            return None
        return {"id": as_text(rows[0][0]), "name": as_text(rows[0][1]), "paper": as_text(rows[0][2])}

    async def _write(self, ctx, gap_id: str, summary: str, dataset: dict, metric: dict, baseline: dict | None) -> None:
        plan_id = f"plan-{gap_id}"
        await ctx.workspace.query(
            Q.CLEAR_PLAYBOOK,
            {"id": plan_id, "at": datetime.now(timezone.utc).isoformat(), "gap": gap_id, "summary": summary[:500]},
        )
        ordered = [("dataset", dataset["id"]), ("metric", metric["id"])]
        if baseline:
            ordered.append(("method", baseline["id"]))
        if dataset["paper"]:
            ordered.append(("paper", dataset["paper"]))
        for order, (kind, ref_id) in enumerate(ordered):
            await ctx.workspace.query(
                Q.ADD_PLAYBOOK_STEP,
                {"id": plan_id, "kind": kind, "ref_id": ref_id, "order": order, "role": kind},
            )


def _summary(gap: dict, dataset: dict, metric: dict, baseline: dict | None) -> str:
    family = gap["family"] or "the method in this gap"
    text = f"Smallest experiment: try {family} on {dataset['name']}, and score it with {metric['name']}"
    if baseline:
        text += f", compared with {baseline['name']}"
    papers = dataset["paper"]
    if baseline and baseline["paper"] and baseline["paper"] != papers:
        papers = f"{papers} and {baseline['paper']}"
    return text + f". Those choices come from {papers}."
