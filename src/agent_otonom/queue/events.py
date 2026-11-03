"""In-process event bus for WebSocket fan-out."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any, Callable, Awaitable

from agent_otonom.ui_events import UIEvent


Listener = Callable[[UIEvent], Awaitable[None] | None]


class EventBus:
    def __init__(self) -> None:
        self._listeners: list[Listener] = []
        self._queues: dict[str, list[asyncio.Queue[UIEvent]]] = defaultdict(list)
        self._global_queues: list[asyncio.Queue[UIEvent]] = []
        self._lock = asyncio.Lock()

    def subscribe(self) -> asyncio.Queue[UIEvent]:
        q: asyncio.Queue[UIEvent] = asyncio.Queue(maxsize=256)
        self._global_queues.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[UIEvent]) -> None:
        if q in self._global_queues:
            self._global_queues.remove(q)

    def subscribe_job(self, job_id: str) -> asyncio.Queue[UIEvent]:
        q: asyncio.Queue[UIEvent] = asyncio.Queue(maxsize=256)
        self._queues[job_id].append(q)
        return q

    def unsubscribe_job(self, job_id: str, q: asyncio.Queue[UIEvent]) -> None:
        if q in self._queues.get(job_id, []):
            self._queues[job_id].remove(q)

    async def publish(self, event: UIEvent) -> None:
        targets = list(self._global_queues)
        if event.job_id:
            targets.extend(self._queues.get(event.job_id, []))
        for q in targets:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                try:
                    _ = q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                try:
                    q.put_nowait(event)
                except asyncio.QueueFull:
                    pass
        for listener in list(self._listeners):
            try:
                result = listener(event)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                pass

    def add_listener(self, listener: Listener) -> None:
        self._listeners.append(listener)


# singleton used by app
bus = EventBus()
