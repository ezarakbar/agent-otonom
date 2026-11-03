"""Asyncio background job queue — keeps the WebGUI responsive during long renders."""

from __future__ import annotations

import asyncio
import logging
import traceback
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from agent_otonom.memory.db import Database
from agent_otonom.queue.events import EventBus
from agent_otonom.ui_events import UIEvent, done, error, progress, status

logger = logging.getLogger(__name__)

JobHandler = Callable[["JobContext"], Awaitable[str | None]]


@dataclass
class JobContext:
    job_id: str
    workflow: str
    prompt: str
    meta: dict[str, Any]
    db: Database
    bus: EventBus
    engines: Any
    capability: Any
    settings: Any

    async def emit(self, event: UIEvent) -> None:
        event.job_id = event.job_id or self.job_id
        await self.bus.publish(event)
        await self.db.add_event(event.kind, event.to_dict(), self.job_id)

    async def set_progress(self, pct: float, message: str) -> None:
        await self.db.update_job(self.job_id, progress=pct, status="running")
        await self.emit(progress(message, pct, self.job_id))

    async def set_status(self, message: str) -> None:
        await self.emit(status(message, self.job_id))


@dataclass
class QueuedJob:
    job_id: str
    workflow: str
    prompt: str
    meta: dict[str, Any] = field(default_factory=dict)
    handler: JobHandler | None = None


class JobQueue:
    def __init__(
        self,
        db: Database,
        bus: EventBus,
        concurrency: int = 1,
        timeout_sec: int = 3600,
    ) -> None:
        self.db = db
        self.bus = bus
        self.concurrency = max(1, concurrency)
        self.timeout_sec = timeout_sec
        self._queue: asyncio.Queue[QueuedJob] = asyncio.Queue()
        self._handlers: dict[str, JobHandler] = {}
        self._workers: list[asyncio.Task[None]] = []
        self._running = False
        self.engines: Any = None
        self.capability: Any = None
        self.settings: Any = None

    def register(self, workflow: str, handler: JobHandler) -> None:
        self._handlers[workflow] = handler

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        for i in range(self.concurrency):
            self._workers.append(asyncio.create_task(self._worker_loop(i), name=f"worker-{i}"))

    async def stop(self) -> None:
        self._running = False
        for _ in self._workers:
            await self._queue.put(
                QueuedJob(job_id="", workflow="__stop__", prompt="", handler=None)
            )
        for t in self._workers:
            try:
                await asyncio.wait_for(t, timeout=5)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                t.cancel()
        self._workers.clear()

    async def enqueue(
        self,
        workflow: str,
        prompt: str,
        meta: dict[str, Any] | None = None,
        job_id: str | None = None,
    ) -> str:
        handler = self._handlers.get(workflow)
        if not handler:
            raise KeyError(f"No handler registered for workflow '{workflow}'")
        jid = await self.db.create_job(workflow, prompt, meta=meta, job_id=job_id)
        await self._queue.put(
            QueuedJob(job_id=jid, workflow=workflow, prompt=prompt, meta=meta or {}, handler=handler)
        )
        await self.bus.publish(status(f"Antrian: workflow `{workflow}` dimulai.", jid))
        return jid

    async def _worker_loop(self, worker_id: int) -> None:
        logger.info("Worker %s started", worker_id)
        while self._running:
            job = await self._queue.get()
            try:
                if job.workflow == "__stop__":
                    return
                await self._run_job(job)
            finally:
                self._queue.task_done()

    async def _run_job(self, job: QueuedJob) -> None:
        assert job.handler is not None
        ctx = JobContext(
            job_id=job.job_id,
            workflow=job.workflow,
            prompt=job.prompt,
            meta=job.meta,
            db=self.db,
            bus=self.bus,
            engines=self.engines,
            capability=self.capability,
            settings=self.settings,
        )
        await self.db.update_job(job.job_id, status="running", progress=1)
        await ctx.emit(status(f"Status: Menjalankan `{job.workflow}`…", job.job_id))
        try:
            result_path = await asyncio.wait_for(job.handler(ctx), timeout=self.timeout_sec)
            await self.db.update_job(
                job.job_id,
                status="done",
                progress=100,
                result_path=result_path,
            )
            msg = "Selesai."
            if result_path:
                msg = f"Selesai: {result_path}"
            await ctx.emit(done(msg, path=result_path, job_id=job.job_id))
        except asyncio.TimeoutError:
            err = f"Job timed out after {self.timeout_sec}s"
            logger.error(err)
            await self.db.update_job(job.job_id, status="error", error=err)
            await ctx.emit(error(err, job.job_id))
        except Exception as exc:
            err = f"{type(exc).__name__}: {exc}"
            logger.error("Job %s failed: %s\n%s", job.job_id, err, traceback.format_exc())
            await self.db.update_job(job.job_id, status="error", error=err)
            await ctx.emit(error(err, job.job_id))
