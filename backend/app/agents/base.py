"""Shared agent shape. A concrete agent declares its work and its writes."""

from dataclasses import dataclass, field


CAVEAT = "A gap means this pair was not found in the loaded corpus. It does not mean the idea is new."
MAX_SUMMARY = 180


def as_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode()
    return str(value)


@dataclass
class Trace:
    """One run's tool steps. This stays on the job, not on the supervisor timeline."""

    steps: list[dict] = field(default_factory=list)

    def step(self, tool: str, args: dict, summary: str, path: list | None = None) -> None:
        item = {"step": len(self.steps) + 1, "tool": tool, "args": args, "result_summary": summary[:MAX_SUMMARY]}
        if path:
            item["graph_path"] = path
        self.steps.append(item)

    def as_list(self) -> list[dict]:
        return list(self.steps)


def answer(text: str, evidence: list[dict], trace: Trace, caveats: list[str] | None = None) -> dict:
    return {
        "text": text,
        "evidence": evidence,
        "trace": trace.as_list(),
        "caveats": caveats or [],
    }


@dataclass
class AgentContext:
    """What an agent is allowed to touch for one job. The corpus handle is read-only."""

    graph: object
    corpus: str
    workspace: object
    memory: object
    gaps: object
    queue: object
    settings: object
    search: object | None = None
    llm: object | None = None
    principal: object | None = None
    papers: object | None = None
    trace: Trace = field(default_factory=Trace)

    async def read_corpus(self, cypher: str, params: dict | None = None):
        return await self.graph.run(self.corpus, cypher, params, ro=True)


class Agent:
    """Base for every agent. The tool loop is bounded. Agents do not call each other."""

    name = ""
    work_types: tuple[str, ...] = ()

    async def handle(self, ctx: AgentContext, item: dict) -> dict:
        raise NotImplementedError

    async def use_tool(self, ctx: AgentContext, tools, name: str, args: dict) -> dict:
        if len(ctx.trace.steps) >= ctx.settings.agent_max_steps:
            ctx.trace.step(name, args, "stopped: tool step limit reached")
            return {"stopped": True}
        result = await tools.run(name, args)
        summary = result.get("summary") if isinstance(result, dict) else ""
        ctx.trace.step(name, args, summary or "ok", result.get("path") if isinstance(result, dict) else None)
        return result
