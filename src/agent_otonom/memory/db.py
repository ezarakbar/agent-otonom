"""SQLite persistence for jobs and chat messages."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._migrate()

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if not self._conn:
            raise RuntimeError("Database not connected")
        return self._conn

    async def _migrate(self) -> None:
        await self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                workflow TEXT NOT NULL,
                prompt TEXT NOT NULL,
                status TEXT NOT NULL,
                progress REAL DEFAULT 0,
                result_path TEXT,
                error TEXT,
                meta_json TEXT DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                job_id TEXT,
                meta_json TEXT DEFAULT '{}',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT,
                kind TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
        await self.conn.commit()

    async def create_job(
        self,
        workflow: str,
        prompt: str,
        meta: dict[str, Any] | None = None,
        job_id: str | None = None,
    ) -> str:
        jid = job_id or str(uuid.uuid4())
        now = _now()
        await self.conn.execute(
            """
            INSERT INTO jobs (id, workflow, prompt, status, progress, meta_json, created_at, updated_at)
            VALUES (?, ?, ?, 'queued', 0, ?, ?, ?)
            """,
            (jid, workflow, prompt, json.dumps(meta or {}), now, now),
        )
        await self.conn.commit()
        return jid

    async def update_job(
        self,
        job_id: str,
        *,
        status: str | None = None,
        progress: float | None = None,
        result_path: str | None = None,
        error: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> None:
        row = await self.get_job(job_id)
        if not row:
            return
        new_status = status if status is not None else row["status"]
        new_progress = progress if progress is not None else row["progress"]
        new_path = result_path if result_path is not None else row["result_path"]
        new_error = error if error is not None else row["error"]
        new_meta = json.dumps(meta) if meta is not None else row["meta_json"]
        await self.conn.execute(
            """
            UPDATE jobs
            SET status=?, progress=?, result_path=?, error=?, meta_json=?, updated_at=?
            WHERE id=?
            """,
            (new_status, new_progress, new_path, new_error, new_meta, _now(), job_id),
        )
        await self.conn.commit()

    async def get_job(self, job_id: str) -> dict[str, Any] | None:
        cur = await self.conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,))
        row = await cur.fetchone()
        return dict(row) if row else None

    async def list_jobs(self, limit: int = 50) -> list[dict[str, Any]]:
        cur = await self.conn.execute(
            "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def add_message(
        self,
        role: str,
        content: str,
        job_id: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> str:
        mid = str(uuid.uuid4())
        await self.conn.execute(
            """
            INSERT INTO messages (id, role, content, job_id, meta_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (mid, role, content, job_id, json.dumps(meta or {}), _now()),
        )
        await self.conn.commit()
        return mid

    async def list_messages(self, limit: int = 100) -> list[dict[str, Any]]:
        cur = await self.conn.execute(
            "SELECT * FROM messages ORDER BY created_at ASC LIMIT ?", (limit,)
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def add_event(self, kind: str, payload: dict[str, Any], job_id: str | None = None) -> None:
        await self.conn.execute(
            "INSERT INTO events (job_id, kind, payload_json, created_at) VALUES (?, ?, ?, ?)",
            (job_id, kind, json.dumps(payload), _now()),
        )
        await self.conn.commit()
