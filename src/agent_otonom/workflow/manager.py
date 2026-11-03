"""Dynamic workflow manager — route, generate, enqueue."""

from __future__ import annotations

import logging
from typing import Any

from agent_otonom.config import Settings
from agent_otonom.engines.registry import EngineHub
from agent_otonom.intent.analyzer import IntentAnalyzer, IntentResult
from agent_otonom.queue.worker import JobQueue
from agent_otonom.ui_events import confirm, status
from agent_otonom.workflow.generator import WorkflowGenerator
from agent_otonom.workflow.registry import WorkflowRegistry
from agent_otonom.workflow.sandbox import WorkflowSandbox

logger = logging.getLogger(__name__)


class WorkflowManager:
    def __init__(
        self,
        settings: Settings,
        engines: EngineHub,
        registry: WorkflowRegistry,
        queue: JobQueue,
        allow_dynamic: bool = True,
        require_confirm: bool = True,
    ) -> None:
        self.settings = settings
        self.engines = engines
        self.registry = registry
        self.queue = queue
        self.allow_dynamic = allow_dynamic
        self.require_confirm = require_confirm
        self.analyzer = IntentAnalyzer(engines.llm)
        self.generator = WorkflowGenerator(
            engines.llm,
            settings.workflows_dir / "_generated",
            WorkflowSandbox(),
        )
        self._bind_handlers()

    def _bind_handlers(self) -> None:
        for info in self.registry.list():
            handler = self.registry.handler(info.id)
            if handler:
                self.queue.register(info.id, self._wrap(handler))

    def _wrap(self, run_fn):
        async def _handler(ctx):
            # enrich context
            ctx.engines = self.engines
            ctx.settings = self.settings
            ctx.capability = self.engines.capability
            return await run_fn(ctx)

        return _handler

    async def handle_prompt(
        self,
        prompt: str,
        *,
        meta: dict[str, Any] | None = None,
        confirm_dynamic: bool = False,
    ) -> dict[str, Any]:
        intent = await self.analyzer.analyze(prompt)
        meta = {**(meta or {}), **intent.params}

        if intent.needs_generation or intent.workflow == "dynamic":
            return await self._handle_dynamic(prompt, intent, meta, confirm_dynamic)

        if not self.registry.get(intent.workflow):
            return await self._handle_dynamic(prompt, intent, meta, confirm_dynamic)

        job_id = await self.queue.enqueue(intent.workflow, prompt, meta=meta)
        return {
            "ok": True,
            "job_id": job_id,
            "workflow": intent.workflow,
            "title": intent.title,
            "confidence": intent.confidence,
            "message": f"Status: Menjalankan `{intent.title}`…",
        }

    async def _handle_dynamic(
        self,
        prompt: str,
        intent: IntentResult,
        meta: dict[str, Any],
        confirm_dynamic: bool,
    ) -> dict[str, Any]:
        if not self.allow_dynamic:
            return {
                "ok": False,
                "error": "Dynamic workflows disabled. Set ALLOW_DYNAMIC_WORKFLOWS=true.",
            }

        if self.require_confirm and not confirm_dynamic:
            await self.queue.bus.publish(
                confirm(
                    "Workflow baru belum ada. Konfirmasi untuk generate & jalankan modul dinamis?",
                    data={"idea": prompt, "action": "generate_workflow"},
                )
            )
            return {
                "ok": True,
                "needs_confirm": True,
                "workflow": "dynamic",
                "message": (
                    "Workflow untuk tugas ini belum tersedia. "
                    "Konfirmasi untuk membuat modul baru secara dinamis."
                ),
                "idea": prompt,
            }

        await self.queue.bus.publish(status("Status: Menulis workflow Python baru…"))
        wid, path, warnings = await self.generator.generate(prompt)
        self.registry.register_generated(
            wid,
            path,
            title=wid.replace("_", " ").title(),
            description=f"Generated for: {prompt[:160]}",
        )
        handler = self.registry.handler(wid)
        if not handler:
            return {"ok": False, "error": "Failed to load generated workflow"}
        self.queue.register(wid, self._wrap(handler))

        job_id = await self.queue.enqueue(wid, prompt, meta=meta)
        return {
            "ok": True,
            "job_id": job_id,
            "workflow": wid,
            "generated": True,
            "path": str(path),
            "warnings": warnings,
            "message": f"Status: Workflow baru `{wid}` disimpan & dijalankan…",
        }
