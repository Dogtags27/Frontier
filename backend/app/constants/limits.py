"""Request buckets and LLM budgets. One limiter, three stores behind it."""

import asyncio
import math
from datetime import datetime, timezone
from decimal import Decimal

import structlog

from app.constants.config import Settings
from app.models.queries import SQL

log = structlog.get_logger()

READ = 1
WRITE = 2
CHAT = 5
DISCOVERY = 20

# Spend the cost from every bucket, or from none. ARGV: now_ms, refill_per_ms, cost, ttl_ms, fail_ms, caps...
TAKE_SCRIPT = """
local now = tonumber(ARGV[1])
local refill = tonumber(ARGV[2])
local cost = tonumber(ARGV[3])
local ttl = tonumber(ARGV[4])
local fail_ms = tonumber(ARGV[5])
local tokens = {}
local caps = {}
for i = 1, #KEYS do
  caps[i] = tonumber(ARGV[5 + i])
  local data = redis.call('HMGET', KEYS[i], 'tokens', 'ts')
  local held = tonumber(data[1])
  local ts = tonumber(data[2])
  if held == nil then
    held = caps[i]
    ts = now
  end
  local elapsed = now - ts
  if elapsed < 0 then elapsed = 0 end
  held = math.min(caps[i], held + elapsed * refill)
  tokens[i] = held
end
local blocked = 0
local retry_ms = 0
for i = 1, #KEYS do
  if tokens[i] < cost then
    blocked = i
    if refill > 0 then
      retry_ms = math.ceil((cost - tokens[i]) / refill)
    else
      retry_ms = fail_ms
    end
    break
  end
end
for i = 1, #KEYS do
  local left = tokens[i]
  if blocked == 0 then left = left - cost end
  redis.call('HSET', KEYS[i], 'tokens', left, 'ts', now)
  redis.call('PEXPIRE', KEYS[i], ttl)
end
if blocked == 0 then return {1, 0, 0} end
return {0, retry_ms, blocked}
"""

ACQUIRE_SCRIPT = """
local held = redis.call('INCR', KEYS[1])
if held == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end
if held > tonumber(ARGV[2]) then
  redis.call('DECR', KEYS[1])
  return 0
end
return held
"""


def retry_seconds(tokens: float, cost: float, refill_per_sec: float, window: int) -> int:
    if refill_per_sec <= 0:
        return max(1, window)
    return max(1, math.ceil((cost - tokens) / refill_per_sec))


def refilled(tokens: float, then: float, now: float, capacity: float, refill_per_sec: float) -> float:
    elapsed = max(0.0, now - then)
    return min(capacity, tokens + elapsed * refill_per_sec)


class MemoryBuckets:
    """Process-local buckets. Tests use this so they do not share Redis."""

    def __init__(self):
        self.rows: dict[str, tuple[float, float]] = {}
        self.held: dict[str, int] = {}
        self._lock = asyncio.Lock()

    async def take(self, pairs: list[tuple[str, float]], refill: float, cost: float, window: int):
        now = asyncio.get_running_loop().time()
        async with self._lock:
            states = []
            for key, capacity in pairs:
                tokens, then = self.rows.get(key, (capacity, now))
                states.append(refilled(tokens, then, now, capacity, refill))
            for index, tokens in enumerate(states):
                if tokens < cost:
                    for (key, _capacity), left in zip(pairs, states):
                        self.rows[key] = (left, now)
                    return False, retry_seconds(tokens, cost, refill, window), index
            for (key, _capacity), left in zip(pairs, states):
                self.rows[key] = (left - cost, now)
            return True, 0, -1

    async def acquire(self, key: str, limit: int, ttl: int) -> bool:
        async with self._lock:
            held = self.held.get(key, 0) + 1
            if held > limit:
                return False
            self.held[key] = held
            return True

    async def release(self, key: str) -> None:
        async with self._lock:
            self.held[key] = max(0, self.held.get(key, 0) - 1)


class RedisBuckets:
    def __init__(self, graph):
        self.graph = graph

    async def ping(self) -> None:
        await self.graph.eval("return 1", [], [])

    async def take(self, pairs: list[tuple[str, float]], refill: float, cost: float, window: int):
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        refill_per_ms = refill / 1000
        keys = [key for key, _capacity in pairs]
        args = [now_ms, refill_per_ms, cost, window * 1000, window * 1000]
        args.extend(capacity for _key, capacity in pairs)
        allowed, retry_ms, blocked = await self.graph.eval(TAKE_SCRIPT, keys, args)
        if int(allowed) == 1:
            return True, 0, -1
        retry = max(1, math.ceil(int(retry_ms) / 1000))
        return False, retry, int(blocked) - 1

    async def acquire(self, key: str, limit: int, ttl: int) -> bool:
        held = await self.graph.eval(ACQUIRE_SCRIPT, [key], [ttl, limit])
        return int(held) > 0

    async def release(self, key: str) -> None:
        await self.graph.eval("redis.call('DECR', KEYS[1]); return 1", [key], [])


class PostgresBuckets:
    """Same bucket rules, stored in Postgres when Redis refuses extra keys."""

    def __init__(self, pg):
        self.pg = pg

    async def take(self, pairs: list[tuple[str, float]], refill: float, cost: float, window: int):
        return await self.pg.transaction(lambda conn: self._take(conn, pairs, refill, cost, window))

    def _take(self, conn, pairs, refill, cost, window):
        now = datetime.now(timezone.utc)
        states: dict[str, float] = {}
        with conn.cursor() as cur:
            for key, capacity in sorted(pairs, key=lambda item: item[0]):
                cur.execute(SQL.INSERT_BUCKET, (key, capacity, now))
                cur.execute(SQL.LOCK_BUCKET, (key,))
                row = cur.fetchone()
                then = row[1]
                if then.tzinfo is None:
                    then = then.replace(tzinfo=timezone.utc)
                elapsed = max(0.0, (now - then).total_seconds())
                states[key] = min(float(capacity), float(row[0]) + elapsed * refill)
            blocked = -1
            retry = 0
            for index, (key, _capacity) in enumerate(pairs):
                if states[key] < cost:
                    blocked = index
                    retry = retry_seconds(states[key], cost, refill, window)
                    break
            for key, _capacity in pairs:
                left = states[key] if blocked >= 0 else states[key] - cost
                cur.execute(SQL.UPDATE_BUCKET, (left, now, key))
            return blocked < 0, retry, blocked

    async def acquire(self, key: str, limit: int, ttl: int) -> bool:
        rows = await self.pg.fetch(SQL.ACQUIRE_CONCURRENCY, (key, limit))
        return bool(rows)

    async def release(self, key: str) -> None:
        await self.pg.execute(SQL.RELEASE_CONCURRENCY, (key,))


class Budget:
    """Daily user and org caps, plus one monthly circuit breaker. Summaries cache for 30 seconds."""

    def __init__(self, pg, settings: Settings):
        self.pg = pg
        self.settings = settings
        self._cache: dict[str, tuple[float, tuple]] = {}

    def invalidate(self, user_id: str, org_id: str | None) -> None:
        self._cache.pop(f"user:{user_id}", None)
        if org_id:
            self._cache.pop(f"org:{org_id}", None)
        self._cache.pop("month", None)

    async def assert_open(self, principal) -> None:
        from app.core import RateLimited

        month = await self._month()
        if month >= Decimal(str(self.settings.monthly_usd)):
            raise RateLimited("monthly budget reached", "monthly_budget", retry_after=3600)
        tokens, usd = await self._user(principal.user_id)
        if tokens >= self.settings.daily_token_cap(principal.role) or usd >= Decimal(str(self.settings.daily_usd_cap(principal.role))):
            raise RateLimited("daily budget reached", "daily_budget", retry_after=3600)
        if principal.org_id:
            _org_tokens, org_usd = await self._org(principal.org_id)
            if org_usd >= Decimal(str(self.settings.daily_usd_org)):
                raise RateLimited("org budget reached", "org_budget", retry_after=3600)

    async def _user(self, user_id: str):
        return await self._cached(f"user:{user_id}", SQL.USAGE_DAY_USER, (user_id,))

    async def _org(self, org_id: str):
        return await self._cached(f"org:{org_id}", SQL.USAGE_DAY_ORG, (org_id,))

    async def _month(self) -> Decimal:
        _tokens, usd = await self._cached("month", SQL.USAGE_MONTH, ())
        return usd

    async def _cached(self, key: str, sql: str, params: tuple):
        now = asyncio.get_running_loop().time()
        hit = self._cache.get(key)
        if hit and now - hit[0] < 30:
            return hit[1]
        rows = await self.pg.fetch(sql, params or None)
        row = rows[0]
        if len(row) == 1:
            value = (0, Decimal(row[0]))
        else:
            value = (int(row[0]), Decimal(row[1]))
        self._cache[key] = (now, value)
        return value


class RateLimiter:
    """Token buckets per user, IP, and auth pair. LLM routes also check the ledger."""

    def __init__(self, settings: Settings, pg, graph, budget: Budget):
        self.settings = settings
        self.pg = pg
        self.budget = budget
        self.backend = "memory"
        self._choice = settings.rate_backend
        self._memory = MemoryBuckets()
        self._redis = RedisBuckets(graph)
        self._postgres = PostgresBuckets(pg)

    async def open(self) -> None:
        if self._choice == "memory":
            self.backend = "memory"
            return
        if self._choice in ("auto", "redis"):
            try:
                await self._redis.ping()
                self.backend = "redis"
                return
            except Exception as exc:
                log.info("rate limiter redis unavailable", error=type(exc).__name__)
                if self._choice == "redis":
                    self.backend = "memory" if self.pg.error else "postgres"
                    return
        self.backend = "memory" if self.pg.error else "postgres"

    def _store(self):
        if self.backend == "redis":
            return self._redis
        if self.backend == "postgres":
            return self._postgres
        return self._memory

    async def allow(self, request, principal, cost: float, llm: bool = False) -> None:
        ip = request.client.host if request.client else "unknown"
        capacity = self.settings.tier_capacity(principal.role or "student")
        pairs = [(f"rl:user:{principal.user_id}", capacity), (f"rl:ip:{ip}", self.settings.rate_ip_capacity)]
        await self._spend(pairs, self.settings.rate_refill_per_sec, cost, ("user", "ip"))
        if llm:
            await self.budget.assert_open(principal)

    async def allow_auth(self, request, email: str) -> None:
        ip = request.client.host if request.client else "unknown"
        pairs = [(f"rl:auth:{ip}:{email}", self.settings.rate_auth_capacity)]
        await self._spend(pairs, self.settings.rate_auth_refill_per_sec, 1, ("auth",))

    async def _spend(self, pairs, refill: float, cost: float, names: tuple[str, ...]) -> None:
        from app.core import RateLimited

        allowed, retry, index = await self._store().take(pairs, refill, cost, self.settings.rate_window_sec)
        if not allowed:
            raise RateLimited("too many requests", names[index], retry_after=retry)

    async def acquire(self, user_id: str) -> None:
        from app.core import RateLimited

        key = f"rl:conc:{user_id}"
        ok = await self._store().acquire(key, self.settings.max_agent_concurrency, self.settings.rate_window_sec)
        if not ok:
            raise RateLimited("too many agent runs", "concurrency", retry_after=1)

    async def release(self, user_id: str) -> None:
        await self._store().release(f"rl:conc:{user_id}")
