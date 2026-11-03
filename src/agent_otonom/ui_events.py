"""Clean status lines for the chat UI (hide raw terminal noise)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal


EventKind = Literal[
    "status",
    "progress",
    "preview",
    "error",
    "done",
    "confirm",
    "system",
    "log",
]


@dataclass
class UIEvent:
    kind: EventKind
    message: str
    job_id: str | None = None
    progress: float | None = None  # 0..100
    path: str | None = None
    data: dict[str, Any] = field(default_factory=dict)
    ts: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def status(message: str, job_id: str | None = None, **data: Any) -> UIEvent:
    return UIEvent(kind="status", message=message, job_id=job_id, data=data)


def progress(message: str, pct: float, job_id: str | None = None, **data: Any) -> UIEvent:
    return UIEvent(kind="progress", message=message, progress=pct, job_id=job_id, data=data)


def preview(message: str, path: str, job_id: str | None = None, **data: Any) -> UIEvent:
    return UIEvent(kind="preview", message=message, path=path, job_id=job_id, data=data)


def done(message: str, path: str | None = None, job_id: str | None = None, **data: Any) -> UIEvent:
    return UIEvent(kind="done", message=message, path=path, job_id=job_id, data=data)


def error(message: str, job_id: str | None = None, **data: Any) -> UIEvent:
    return UIEvent(kind="error", message=message, job_id=job_id, data=data)


def confirm(message: str, job_id: str | None = None, **data: Any) -> UIEvent:
    return UIEvent(kind="confirm", message=message, job_id=job_id, data=data)


def system(message: str, **data: Any) -> UIEvent:
    return UIEvent(kind="system", message=message, data=data)
