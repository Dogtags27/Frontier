"""One choke point each for FalkorDB, Postgres, and R2."""

import asyncio

import boto3
from falkordb.asyncio import FalkorDB
from psycopg_pool import ConnectionPool

from app.constants import Settings
from app.models.queries import Q


def _text(value):
    return value.decode() if isinstance(value, bytes) else value


class GraphStore:
    """Async FalkorDB. `ro=True` uses GRAPH.RO_QUERY, which rejects writes."""

    def __init__(self, settings: Settings):
        password = settings.falkordb_password or None
        self._db = FalkorDB(
            host=settings.falkordb_host,
            port=settings.falkordb_port,
            password=password,
        )
        self._timeout = settings.query_timeout_ms
        self._corpus = settings.corpus_graph
        self.error: str | None = None

    async def run(self, graph: str, query: str, params: dict | None = None, ro: bool = False):
        selected = self._db.select_graph(graph)
        if ro:
            result = await selected.ro_query(query, params or {}, timeout=self._timeout)
        else:
            result = await selected.query(query, params or {}, timeout=self._timeout)
        return result.result_set

    async def list_graphs(self) -> list[str]:
        names = await self._db.list_graphs()
        return [_text(name) for name in names]

    async def delete_graph(self, name: str) -> None:
        """Delete one workspace graph. Refuses the shared corpus."""
        if not name.startswith("frontier_ws_"):
            raise RuntimeError(f"refusing to delete {name}")
        selected = self._db.select_graph(name)
        try:
            await selected.delete()
        except Exception as exc:
            if "Invalid graph operation" in str(exc) or "empty key" in str(exc).lower():
                return
            raise

    async def titles_for(self, arxiv_ids: list[str]) -> dict[str, str]:
        """Resolve paper ids from a workspace against the corpus. One batched read."""
        wanted = [arxiv_id for arxiv_id in dict.fromkeys(arxiv_ids) if arxiv_id]
        if not wanted:
            return {}
        rows = await self.run(self._corpus, Q.PAPERS_BY_IDS, {"ids": wanted}, ro=True)
        return {_text(row[0]): _text(row[1]) for row in rows}

    async def ensure_workspace(self, name: str) -> None:
        """Constraints on one private graph. Re-running is a no-op. The corpus is never selected."""
        if not name.startswith("frontier_ws_"):
            raise RuntimeError(f"refusing to touch {name}")
        selected = self._db.select_graph(name)
        for label, prop in (
            ("Memory", "id"),
            ("Conversation", "id"),
            ("Turn", "id"),
            ("Event", "id"),
            ("ReadEvent", "id"),
            ("Decision", "id"),
            ("Gap", "id"),
            ("Idempotency", "key"),
            ("WorkItem", "id"),
            ("Handoff", "id"),
            ("Session", "id"),
            ("Attempt", "id"),
            ("Finding", "id"),
            ("ReadingPath", "id"),
            ("Playbook", "id"),
        ):
            try:
                await selected.create_node_unique_constraint(label, prop)
            except Exception as exc:
                if "already" in str(exc).lower() or "exist" in str(exc).lower():
                    continue
                raise

    async def push_hint(self, key: str, graph: str) -> None:
        """Wake a worker. The graph node is the truth; this list is only a hint."""
        await self._db.connection.lpush(key, graph)

    async def pop_hint(self, key: str, timeout: int) -> str | None:
        row = await self._db.connection.brpop(key, timeout=timeout)
        if not row:
            return None
        value = row[1]
        return _text(value)

    async def eval(self, script: str, keys: list[str], args: list):
        """Run a Redis script on the FalkorDB connection. Used by the rate limiter, not by graph queries."""
        return await self._db.connection.eval(script, len(keys), *keys, *[str(arg) for arg in args])

    async def close(self) -> None:
        await self._db.aclose()


class Pg:
    """Postgres pool. Calls run in a worker thread so Windows' event loop is not involved."""

    def __init__(self, settings: Settings):
        self._url = settings.postgres_url
        self._pool: ConnectionPool | None = None
        self.error: str | None = None

    async def open(self) -> None:
        if not self._url:
            self.error = "DATABASE_URL is empty"
            return
        try:
            self._pool = await asyncio.to_thread(self._open)
        except Exception as exc:
            self.error = f"{type(exc).__name__}: {exc}"
            self._pool = None

    def _open(self) -> ConnectionPool:
        pool = ConnectionPool(self._url, min_size=1, max_size=4, open=False, kwargs={"autocommit": True})
        pool.open(wait=True, timeout=30)
        return pool

    async def fetch(self, sql: str, params: tuple | None = None):
        if self._pool is None:
            raise RuntimeError(self.error or "postgres is not open")
        return await asyncio.to_thread(self._fetch, sql, params)

    def _fetch(self, sql: str, params: tuple | None):
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                return cur.fetchall()

    async def execute(self, sql: str, params: tuple | None = None) -> None:
        if self._pool is None:
            raise RuntimeError(self.error or "postgres is not open")
        await asyncio.to_thread(self._execute, sql, params)

    def _execute(self, sql: str, params: tuple | None) -> None:
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)

    async def transaction(self, fn):
        """Run fn(connection) in one transaction on a worker thread."""
        if self._pool is None:
            raise RuntimeError(self.error or "postgres is not open")
        return await asyncio.to_thread(self._transaction, fn)

    def _transaction(self, fn):
        with self._pool.connection() as conn:
            conn.autocommit = False
            try:
                result = fn(conn)
                conn.commit()
                return result
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.autocommit = True

    async def execute_script(self, statements: list[str]) -> None:
        def run(conn):
            with conn.cursor() as cur:
                for statement in statements:
                    cur.execute(statement)

        await self.transaction(run)

    async def close(self) -> None:
        if self._pool is not None:
            await asyncio.to_thread(self._pool.close)


class Blob:
    """R2 through the S3 API. Object bodies leave only via get or presign."""

    def __init__(self, settings: Settings):
        self._bucket = settings.r2_bucket
        self.error: str | None = None
        if not settings.r2_endpoint or not settings.r2_access_key_id:
            self.error = "R2 settings are empty"
            self._client = None
            return
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.r2_endpoint,
            aws_access_key_id=settings.r2_access_key_id,
            aws_secret_access_key=settings.r2_secret_access_key,
            region_name="auto",
        )

    async def count_prefix(self, prefix: str) -> int:
        if self._client is None:
            raise RuntimeError(self.error or "r2 is not configured")
        return await asyncio.to_thread(self._count_prefix, prefix)

    def _count_prefix(self, prefix: str) -> int:
        paginator = self._client.get_paginator("list_objects_v2")
        total = 0
        for page in paginator.paginate(Bucket=self._bucket, Prefix=prefix):
            total += page.get("KeyCount", 0)
        return total

    def presign(self, key: str, expires: int = 60) -> str:
        if self._client is None:
            raise RuntimeError(self.error or "r2 is not configured")
        return self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self._bucket, "Key": key},
            ExpiresIn=expires,
        )

    def get(self, key: str) -> bytes:
        if self._client is None:
            raise RuntimeError(self.error or "r2 is not configured")
        body = self._client.get_object(Bucket=self._bucket, Key=key)["Body"]
        return body.read()
