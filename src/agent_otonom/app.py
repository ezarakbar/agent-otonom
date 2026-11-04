"""FastAPI gateway — REST + WebSocket + static WebGUI."""

from __future__ import annotations

import logging
import shutil
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from agent_otonom.capability import probe
from agent_otonom.config import Settings, get_settings
from agent_otonom.engines.registry import EngineHub, build_engines
from agent_otonom.logging_setup import setup_logging
from agent_otonom.memory.db import Database
from agent_otonom.queue.events import bus
from agent_otonom.queue.worker import JobQueue
from agent_otonom.ui_events import system
from agent_otonom.workflow.manager import WorkflowManager
from agent_otonom.workflow.registry import WorkflowRegistry

logger = logging.getLogger(__name__)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    confirm_dynamic: bool = False
    meta: dict[str, Any] = Field(default_factory=dict)


class AppState:
    settings: Settings
    db: Database
    queue: JobQueue
    engines: EngineHub
    manager: WorkflowManager
    capability: Any


state = AppState()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    setup_logging(settings.logs_dir, settings.log_level)
    settings.ensure_dirs()

    db = Database(settings.db_path)
    await db.connect()

    cap = await probe(settings)
    engines = build_engines(settings, cap)

    queue = JobQueue(
        db,
        bus,
        concurrency=settings.worker_concurrency,
        timeout_sec=settings.job_timeout_sec,
    )
    queue.engines = engines
    queue.capability = cap
    queue.settings = settings

    registry = WorkflowRegistry(settings.workflows_dir)
    registry.load()

    manager = WorkflowManager(
        settings,
        engines,
        registry,
        queue,
        allow_dynamic=settings.allow_dynamic_workflows,
        require_confirm=settings.require_confirm_new_workflow,
    )
    await queue.start()

    state.settings = settings
    state.db = db
    state.queue = queue
    state.engines = engines
    state.manager = manager
    state.capability = cap

    missing = [
        name
        for name, info in cap.engines.items()
        if info.get("required") and not info.get("available")
    ]
    boot = "AGENT OTONOM siap. Engine utama: ComfyUI (image/video) + GPT-SoVITS (audio)."
    if missing:
        boot = (
            "AGENT OTONOM jalan, tapi engine utama belum aktif: "
            + ", ".join(missing)
            + ". Video/audio tidak akan dibuat sampai ComfyUI dan GPT-SoVITS dijalankan."
        )
    await bus.publish(system(boot, capability=cap.to_dict()))
    logger.info("AGENT OTONOM listening — encoder=%s profile=%s", cap.video_encoder, cap.quality_profile)

    yield

    await queue.stop()
    await db.close()


def create_app() -> FastAPI:
    app = FastAPI(title="AGENT OTONOM", version="0.1.0", lifespan=lifespan)

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        return {"ok": True, "service": "agent-otonom", "version": "0.1.0"}

    @app.get("/api/capability")
    async def capability() -> dict[str, Any]:
        cap = await probe(state.settings)
        state.capability = cap
        return cap.to_dict()

    @app.get("/api/workflows")
    async def workflows() -> dict[str, Any]:
        items = [
            {
                "id": w.id,
                "title": w.title,
                "description": w.description,
                "builtin": w.builtin,
            }
            for w in state.manager.registry.list()
        ]
        return {"workflows": items}

    @app.get("/api/jobs")
    async def jobs() -> dict[str, Any]:
        return {"jobs": await state.db.list_jobs()}

    @app.get("/api/jobs/{job_id}")
    async def job(job_id: str) -> dict[str, Any]:
        row = await state.db.get_job(job_id)
        if not row:
            raise HTTPException(404, "Job not found")
        return row

    @app.get("/api/messages")
    async def messages() -> dict[str, Any]:
        return {"messages": await state.db.list_messages()}

    @app.post("/api/chat")
    async def chat(req: ChatRequest) -> dict[str, Any]:
        await state.db.add_message("user", req.message, meta=req.meta)
        result = await state.manager.handle_prompt(
            req.message,
            meta=req.meta,
            confirm_dynamic=req.confirm_dynamic,
        )
        await state.db.add_message(
            "assistant",
            result.get("message") or result.get("error") or str(result),
            job_id=result.get("job_id"),
            meta=result,
        )
        return result

    @app.post("/api/upload")
    async def upload(file: UploadFile = File(...)) -> dict[str, Any]:
        suffix = Path(file.filename or "upload.bin").suffix.lower()
        if suffix not in {".mp4", ".mov", ".mkv", ".webm", ".avi"}:
            raise HTTPException(400, "Unsupported video type")
        name = f"{uuid.uuid4().hex}{suffix}"
        dest = state.settings.uploads_dir / name
        with dest.open("wb") as f:
            shutil.copyfileobj(file.file, f)
        return {"ok": True, "path": str(dest), "filename": file.filename}

    @app.get("/api/media")
    async def media(path: str) -> FileResponse:
        p = Path(path).resolve()
        root = state.settings.agent_root.resolve()
        if not str(p).startswith(str(root)) or not p.is_file():
            raise HTTPException(404, "File not found")
        return FileResponse(p)

    @app.websocket("/ws")
    async def websocket(ws: WebSocket) -> None:
        await ws.accept()
        q = bus.subscribe()
        try:
            await ws.send_json(
                system("WS connected", capability=state.capability.to_dict()).to_dict()
            )
            while True:
                event = await q.get()
                await ws.send_json(event.to_dict())
        except WebSocketDisconnect:
            pass
        except Exception:
            logger.exception("WebSocket error")
        finally:
            bus.unsubscribe(q)

    web_dir = get_settings().web_dir
    if web_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=web_dir / "assets"), name="assets")

        @app.get("/")
        async def index() -> FileResponse:
            return FileResponse(web_dir / "index.html")

    return app


app = create_app()
