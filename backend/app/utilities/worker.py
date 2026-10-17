"""Claim a graph hint, run the handler, and write the result back.

A handler is an agent or a small gate. Agents do not call each other. A type
with no handler stays open until one is registered.
"""

import asyncio
import os
import uuid

import structlog

log = structlog.get_logger()


def build_handlers(container) -> dict:
    from app.agents.roster import worker_handlers

    return worker_handlers(container)


class Worker:
    """One process, a small pool, and a sweeper that repairs missed hints."""

    def __init__(self, container, handlers: dict | None = None, worker_id: str = ""):
        self.container = container
        self.handlers = handlers if handlers is not None else build_handlers(container)
        self.types = list(self.handlers)
        self.worker_id = worker_id or f"worker-{os.getpid()}-{uuid.uuid4().hex[:8]}"
        self.slots = asyncio.Semaphore(container.settings.worker_concurrency)
        self.stop = asyncio.Event()

    async def serve(self) -> None:
        sweeper = asyncio.create_task(self._sweep_loop())
        pending: set[asyncio.Task] = set()
        log.info("worker started", worker=self.worker_id, types=self.types)
        try:
            while not self.stop.is_set():
                hint = await self.container.graph.pop_hint(self.container.settings.work_hint_key, 1)
                if not hint:
                    continue
                await self.slots.acquire()
                task = asyncio.create_task(self._guard(hint))
                pending.add(task)
                task.add_done_callback(pending.discard)
        finally:
            sweeper.cancel()
            if pending:
                await asyncio.wait(pending, timeout=self.container.settings.work_lease_sec)

    async def run_graph(self, graph_name: str) -> int:
        """Claim and finish every runnable item currently waiting on one graph."""
        finished = 0
        while True:
            item = await self.container.queue.claim(graph_name, self.worker_id, self.types)
            if item is None:
                return finished
            if await self._execute(graph_name, item):
                finished += 1

    async def sweep_once(self, graphs: list[str] | None = None) -> int:
        names = graphs if graphs is not None else await self.container.queue.ready_graphs()
        pushed = 0
        for name in names:
            try:
                waiting = await self.container.queue.claimable(name, self.types)
            except Exception as exc:
                log.info("sweep skipped", graph=name, error=type(exc).__name__)
                continue
            if waiting:
                await self.container.graph.push_hint(self.container.settings.work_hint_key, name)
                pushed += 1
        return pushed

    async def _guard(self, graph_name: str) -> None:
        try:
            await self.run_graph(graph_name)
        except Exception as exc:
            log.warning("worker graph failed", graph=graph_name, error=type(exc).__name__)
        finally:
            self.slots.release()

    async def _execute(self, graph_name: str, item: dict) -> bool:
        handler = self.handlers.get(item["type"])
        if handler is None:
            return False
        try:
            result = await handler(item, graph_name)
        except Exception as exc:
            await self.container.queue.fail(graph_name, self.worker_id, item["id"], type(exc).__name__)
            log.info("job failed", job=item["id"], error=type(exc).__name__)
            return False
        wrote = await self.container.queue.complete(
            graph_name,
            self.worker_id,
            item["id"],
            result if isinstance(result, dict) else {"ok": True},
        )
        if not wrote:
            log.info("job lost its lease", job=item["id"])
        return wrote

    async def _sweep_loop(self) -> None:
        while not self.stop.is_set():
            try:
                await self.sweep_once()
            except Exception as exc:
                log.warning("sweep failed", error=type(exc).__name__)
            try:
                await asyncio.wait_for(self.stop.wait(), self.container.settings.work_sweep_sec)
                return
            except asyncio.TimeoutError:
                continue


async def serve() -> None:
    from app.core import Container
    from app.main import configure_logging

    configure_logging()
    container = Container.build()
    await container.open()
    worker = Worker(container)
    try:
        await worker.serve()
    finally:
        worker.stop.set()
        await container.close()


def main() -> None:
    asyncio.run(serve())


if __name__ == "__main__":
    main()
