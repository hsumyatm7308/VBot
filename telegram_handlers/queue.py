"""In-memory FIFO queues with one sequential worker per Telegram user."""

import asyncio
from collections import deque
from dataclasses import dataclass
from typing import Awaitable, Callable


@dataclass(frozen=True)
class DownloadJob:
    user_id: int
    execute: Callable[[], Awaitable[None]]
    begin: Callable[[], None]
    finish: Callable[[], None]


@dataclass(frozen=True)
class EnqueueResult:
    state: str
    position: int | None = None


@dataclass(frozen=True)
class QueueCancellation:
    had_work: bool
    worker: asyncio.Task | None


class DownloadQueueManager:
    """Keep at most one active and ``max_queued`` waiting jobs per user.

    Queue mutations contain no awaits, so enqueue/worker handoff is atomic on
    the single asyncio event loop used by python-telegram-bot.
    """

    def __init__(self, max_queued: int = 2):
        self.max_queued = max_queued
        self.queues: dict[int, deque[DownloadJob]] = {}
        self.active_jobs: dict[int, DownloadJob] = {}
        self.workers: dict[int, asyncio.Task] = {}
        self._shutting_down = False

    def has_work(self, user_id: int) -> bool:
        worker = self.workers.get(user_id)
        return bool(
            user_id in self.active_jobs
            or self.queues.get(user_id)
            or (worker is not None and not worker.done())
        )

    def enqueue(self, job: DownloadJob) -> EnqueueResult:
        user_id = job.user_id
        waiting = self.queues.get(user_id)

        if user_id in self.active_jobs:
            if waiting is None:
                waiting = self.queues.setdefault(user_id, deque())
            if len(waiting) >= self.max_queued:
                return EnqueueResult("full")
            waiting.append(job)
            return EnqueueResult("queued", len(waiting))

        self.active_jobs[user_id] = job
        self.queues.setdefault(user_id, deque())
        self._start_worker(user_id)
        return EnqueueResult("started")

    def clear_waiting(self, user_id: int) -> QueueCancellation:
        waiting = self.queues.pop(user_id, None)
        worker = self.workers.get(user_id)
        task_active = worker is not None and not worker.done()
        had_work = bool(waiting or task_active)
        return QueueCancellation(had_work, worker)

    async def wait_until_idle(self, user_id: int, timeout: float = 5.0):
        """Wait for all jobs for a user; intended for orderly shutdown/tests."""
        async def wait_for_idle_loop():
            while True:
                worker = self.workers.get(user_id)
                if worker is None:
                    return
                await asyncio.gather(worker, return_exceptions=True)
                await asyncio.sleep(0)

        await asyncio.wait_for(wait_for_idle_loop(), timeout=timeout)

    async def shutdown(self, stop_process: Callable[[int], Awaitable] | None = None):
        self._shutting_down = True
        user_ids = set(self.workers) | set(self.active_jobs) | set(self.queues)
        tasks = []

        for user_id in user_ids:
            self.queues.pop(user_id, None)
            worker = self.workers.get(user_id)
            if worker is None or worker.done():
                continue
            try:
                if stop_process is not None:
                    await stop_process(user_id)
            except Exception as error:
                import logging

                logging.getLogger(__name__).warning(
                    "Could not stop media process during shutdown for user %s (%s)",
                    user_id,
                    type(error).__name__,
                )
            finally:
                worker.cancel()
            tasks.append(worker)

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        self.active_jobs.clear()
        self.queues.clear()
        self.workers.clear()
        self._shutting_down = False

    def _start_worker(self, user_id: int):
        task = asyncio.create_task(
            self._run_user(user_id),
            name=f"download-queue-{user_id}",
        )
        self.workers[user_id] = task
        task.add_done_callback(
            lambda completed, queued_user_id=user_id: self._worker_done(
                queued_user_id,
                completed,
            )
        )

    async def _run_user(self, user_id: int):
        while user_id in self.active_jobs:
            job = self.active_jobs[user_id]
            began = False
            try:
                job.begin()
                began = True
                await job.execute()
            except asyncio.CancelledError:
                raise
            except Exception as error:
                # The job runner normally maps errors to its normal UI. This
                # guard ensures an unexpected exception cannot strand the FIFO.
                import logging

                logging.getLogger(__name__).error(
                    "Download queue job failed for user %s (%s)",
                    user_id,
                    type(error).__name__,
                )
            finally:
                if began:
                    job.finish()

            waiting = self.queues.get(user_id)
            if waiting:
                self.active_jobs[user_id] = waiting.popleft()
            else:
                self.active_jobs.pop(user_id, None)
                self.queues.pop(user_id, None)

    def _worker_done(self, user_id: int, task: asyncio.Task):
        if self.workers.get(user_id) is not task:
            return

        if not task.cancelled():
            error = task.exception()
            if error is not None:
                import logging

                logging.getLogger(__name__).error(
                    "Download queue worker stopped for user %s (%s)",
                    user_id,
                    type(error).__name__,
                )

        self.workers.pop(user_id, None)
        self.active_jobs.pop(user_id, None)

        waiting = self.queues.get(user_id)
        if self._shutting_down or not waiting:
            self.queues.pop(user_id, None)
            return

        self.active_jobs[user_id] = waiting.popleft()
        self._start_worker(user_id)


DOWNLOAD_QUEUE = DownloadQueueManager(max_queued=2)
