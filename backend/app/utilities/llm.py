"""Chat, structured output, and embeddings. Every call writes the usage ledger."""

import hashlib
import uuid
from decimal import Decimal

from pydantic import BaseModel, ValidationError

from app.constants import Settings
from app.core import Upstream
from app.constants import Budget
from app.models.queries import SQL

CHAT_MODEL = "gpt-4.1-mini"
EMBED_MODEL = "text-embedding-3-small"


class Completion:
    def __init__(self, text: str, input_tokens: int, output_tokens: int):
        self.text = text
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class OpenAITransport:
    """The only place the OpenAI SDK is constructed."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._client = None

    def _openai(self):
        if self._client is None:
            from openai import AsyncOpenAI

            self._client = AsyncOpenAI(api_key=self.settings.openai_api_key)
        return self._client

    async def complete(self, model: str, messages: list[dict], max_tokens: int, json_mode: bool) -> Completion:
        if not self.settings.openai_api_key:
            raise Upstream("openai is not configured")
        kwargs = {"model": model, "messages": messages, "max_tokens": max_tokens}
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        response = await self._openai().chat.completions.create(**kwargs)
        usage = response.usage
        text = response.choices[0].message.content or ""
        return Completion(text, usage.prompt_tokens or 0, usage.completion_tokens or 0)

    async def stream(self, model: str, messages: list[dict], max_tokens: int, usage: dict):
        if not self.settings.openai_api_key:
            raise Upstream("openai is not configured")
        response = await self._openai().chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            stream=True,
            stream_options={"include_usage": True},
        )
        async for chunk in response:
            if chunk.usage is not None:
                usage["input"] = chunk.usage.prompt_tokens or 0
                usage["output"] = chunk.usage.completion_tokens or 0
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    async def embed(self, model: str, text: str) -> tuple[list[float], int]:
        if not self.settings.openai_api_key:
            raise Upstream("openai is not configured")
        response = await self._openai().embeddings.create(model=model, input=text)
        return list(response.data[0].embedding), response.usage.prompt_tokens or 0


class LLM:
    """Checks the budget, calls the model, then records tokens and dollars."""

    def __init__(self, settings: Settings, pg, budget: Budget, transport=None):
        self.settings = settings
        self.pg = pg
        self.budget = budget
        self.transport = transport or OpenAITransport(settings)
        self._embeds: dict[str, tuple[float, list[float]]] = {}

    async def complete(self, principal, messages: list[dict], max_tokens: int = 800) -> Completion:
        model = self._model("chat")
        await self.budget.assert_open(principal)
        completion = await self._call(lambda: self.transport.complete(model, messages, max_tokens, False))
        await self._record(principal, "chat", model, completion.input_tokens, completion.output_tokens, False)
        return completion

    async def stream(self, principal, messages: list[dict], max_tokens: int = 800):
        """Yield text pieces. A transport without streaming gives one piece."""
        model = self._model("chat")
        await self.budget.assert_open(principal)
        usage = {"input": 0, "output": 0}
        produced = False
        try:
            if hasattr(self.transport, "stream"):
                async for piece in self.transport.stream(model, messages, max_tokens, usage):
                    produced = True
                    yield piece
            else:
                completion = await self._call(lambda: self.transport.complete(model, messages, max_tokens, False))
                usage = {"input": completion.input_tokens, "output": completion.output_tokens}
                produced = True
                yield completion.text
        except Upstream:
            raise
        except Exception as exc:
            if produced:
                return
            raise Upstream("the model call failed", type(exc).__name__) from exc
        finally:
            if produced or usage["input"]:
                await self._record(principal, "chat", model, usage["input"], usage["output"], False)

    async def structured(self, principal, messages: list[dict], schema: type[BaseModel], max_tokens: int = 800):
        model = self._model("chat")
        await self.budget.assert_open(principal)
        dialogue = list(messages)
        error = ""
        for _attempt in range(2):
            completion = await self._call(lambda: self.transport.complete(model, dialogue, max_tokens, True))
            await self._record(principal, "chat", model, completion.input_tokens, completion.output_tokens, False)
            try:
                return schema.model_validate_json(completion.text)
            except ValidationError as exc:
                error = str(exc)
                dialogue = dialogue + [{"role": "user", "content": "Reply with JSON matching the schema."}]
        raise Upstream("the model reply did not match the schema", error[:200])

    async def embed(self, principal, text: str) -> list[float]:
        model = self._model("embed")
        digest = hashlib.sha256(f"{model}\n{text}".encode()).hexdigest()
        cached = self._cached_embed(digest)
        if cached is not None:
            await self._record(principal, "embed", model, 0, 0, True)
            return cached
        await self.budget.assert_open(principal)
        vector, tokens = await self._call(lambda: self.transport.embed(model, text))
        self._embeds[digest] = (self._now(), vector)
        if len(self._embeds) > 256:
            self._embeds.pop(next(iter(self._embeds)))
        await self._record(principal, "embed", model, tokens, 0, False)
        return vector

    def _model(self, kind: str) -> str:
        if kind == "chat":
            model, allowed = self.settings.chat_model, CHAT_MODEL
        else:
            model, allowed = self.settings.embed_model, EMBED_MODEL
        if model != allowed:
            raise Upstream("model is not allowed", model)
        return model

    async def _call(self, fn):
        try:
            return await fn()
        except Upstream:
            raise
        except Exception:
            try:
                return await fn()
            except Exception as exc:
                raise Upstream("the model call failed", type(exc).__name__) from exc

    def _cached_embed(self, digest: str) -> list[float] | None:
        hit = self._embeds.get(digest)
        if hit is None:
            return None
        if self._now() - hit[0] > self.settings.embed_cache_ttl_sec:
            self._embeds.pop(digest, None)
            return None
        return hit[1]

    def _now(self) -> float:
        import time

        return time.monotonic()

    def _usd(self, kind: str, input_tokens: int, output_tokens: int, cached: bool) -> Decimal:
        if cached:
            return Decimal("0")
        if kind == "embed":
            usd = Decimal(input_tokens) * Decimal(str(self.settings.embed_usd_per_mtok))
        else:
            usd = Decimal(input_tokens) * Decimal(str(self.settings.chat_input_usd_per_mtok))
            usd += Decimal(output_tokens) * Decimal(str(self.settings.chat_output_usd_per_mtok))
        return (usd / Decimal(1_000_000)).quantize(Decimal("0.000001"))

    async def _record(self, principal, kind: str, model: str, input_tokens: int, output_tokens: int, cached: bool) -> None:
        await self.pg.execute(
            SQL.INSERT_USAGE,
            (
                str(uuid.uuid4()),
                principal.user_id,
                principal.org_id,
                kind,
                model,
                input_tokens,
                output_tokens,
                self._usd(kind, input_tokens, output_tokens, cached),
                cached,
            ),
        )
        self.budget.invalidate(principal.user_id, principal.org_id)
