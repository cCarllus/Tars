"""Bounded async queue manager for backpressure-sensitive work."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from bot.logger import logger

T = TypeVar("T")
DEFAULT_QUEUE_MAX_SIZE = 500
DEFAULT_WORKER_COUNT = 2


class QueueBackpressureError(RuntimeError):
    """Raised when a queue cannot accept more work."""


@dataclass
class QueueJob(Generic[T]):
    """Queued async operation."""

    action: str
    operation: Callable[[], Awaitable[T]]
    future: asyncio.Future[T]


class QueueManager:
    """Process async operations through a bounded worker queue."""

    def __init__(
        self,
        *,
        name: str,
        max_size: int = DEFAULT_QUEUE_MAX_SIZE,
        worker_count: int = DEFAULT_WORKER_COUNT,
    ) -> None:
        """Initialize the queue manager."""

        self.name = name
        self.max_size = max_size
        self.worker_count = worker_count
        self._queue: asyncio.Queue[QueueJob[Any] | None] = asyncio.Queue(
            maxsize=max_size,
        )
        self._workers: list[asyncio.Task[None]] = []

    async def start(self) -> None:
        """Start queue workers if they are not already running."""

        if self._workers:
            return

        self._workers = [
            asyncio.create_task(self._worker(index), name=f"{self.name}-{index}")
            for index in range(self.worker_count)
        ]
        logger.info(
            "Started queue workers name=%s worker_count=%s",
            self.name,
            self.worker_count,
        )

    async def stop(self) -> None:
        """Stop all queue workers after queued work is processed."""

        if not self._workers:
            return

        await self._queue.join()
        for _ in self._workers:
            await self._queue.put(None)

        await asyncio.gather(*self._workers)
        self._workers.clear()
        logger.info("Stopped queue workers name=%s", self.name)

    async def submit(
        self,
        *,
        action: str,
        operation: Callable[[], Awaitable[T]],
    ) -> T:
        """Submit async work and wait for the worker result."""

        if not self._workers:
            await self.start()

        if self._queue.full():
            logger.warning("Queue backpressure name=%s action=%s", self.name, action)
            msg = f"Queue {self.name} is full"
            raise QueueBackpressureError(msg)

        loop = asyncio.get_running_loop()
        future: asyncio.Future[T] = loop.create_future()
        await self._queue.put(
            QueueJob(action=action, operation=operation, future=future),
        )
        return await future

    async def _worker(self, index: int) -> None:
        while True:
            job = await self._queue.get()
            try:
                if job is None:
                    return

                try:
                    result = await job.operation()
                except Exception as exc:
                    if not job.future.done():
                        job.future.set_exception(exc)
                    logger.exception(
                        "Queued action failed name=%s worker=%s action=%s",
                        self.name,
                        index,
                        job.action,
                    )
                else:
                    if not job.future.done():
                        job.future.set_result(result)
            finally:
                self._queue.task_done()


discord_api_queue = QueueManager(name="discord_api")
