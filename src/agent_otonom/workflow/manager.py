"""Dynamic workflow manager — brief → confirm → enqueue."""

from __future__ import annotations

import logging
from typing import Any

from agent_otonom.config import Settings
from agent_otonom.engines.registry import EngineHub
from agent_otonom.intent.analyzer import IntentAnalyzer, IntentResult
from agent_otonom.production.brief import build_production_brief, format_brief_message
from agent_otonom.queue.worker import JobQueue
from agent_otonom.ui_events import confirm, status
from agent_otonom.workflow.generator import WorkflowGenerator
from agent_otonom.workflow.registry import WorkflowRegistry
from agent_otonom.workflow.sandbox import WorkflowSandbox

logger = logging.getLogger(__name__)

BRIEF_WORKFLOWS = {"cinematic_short", "image_to_video", "video_clipper"}


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
        confirm_production: bool = False,
        selected_option: str | None = None,
    ) -> dict[str, Any]:
        meta = dict(meta or {})
        intent = await self.analyzer.analyze(prompt, meta)
        # Safety net: text-only commands always stay on generative cinematic path
        has_video = bool(meta.get("input_video") or meta.get("upload_path") or intent.params.get("input_video"))
        has_image = bool(meta.get("input_image") or intent.params.get("input_image"))
        if intent.workflow == "video_clipper" and not has_video:
            intent.workflow = "cinematic_short"
            intent.title = "Cinematic Short"
            intent.params["topic"] = prompt
        if intent.workflow == "image_to_video" and not has_image:
            intent.workflow = "cinematic_short"
            intent.title = "Cinematic Short"
            intent.params["topic"] = prompt
        meta = {**meta, **intent.params}

        if intent.needs_generation or intent.workflow == "dynamic":
            return await self._handle_dynamic(prompt, intent, meta, confirm_dynamic)

        if not self.registry.get(intent.workflow):
            return await self._handle_dynamic(prompt, intent, meta, confirm_dynamic)

        # Professional brief always built; auto-execute when configured
        if (
            intent.workflow in BRIEF_WORKFLOWS
            and getattr(self.settings, "require_production_brief", True)
            and not confirm_production
            and not meta.get("skip_brief")
            and not meta.get("production_brief")
        ):
            brief_resp = await self._offer_brief(prompt, intent, meta)
            if getattr(self.settings, "auto_execute_production", True):
                # Fully automatic: use recommended option and enqueue immediately
                brief = brief_resp.get("brief") or {}
                opt = brief_resp.get("recommended_option") or "standard"
                meta = {
                    **meta,
                    "production_brief": brief,
                    "selected_option": opt,
                }
                job_id = await self.queue.enqueue(intent.workflow, prompt, meta=meta)
                return {
                    "ok": True,
                    "job_id": job_id,
                    "workflow": intent.workflow,
                    "title": intent.title,
                    "confidence": intent.confidence,
                    "auto_executed": True,
                    "brief": brief,
                    "selected_option": opt,
                    "message": (
                        brief_resp.get("message", "")
                        + f"\n\n**Auto-execute:** opsi `{opt}` langsung dijalankan."
                    ),
                }
            return brief_resp

        if selected_option:
            meta["selected_option"] = selected_option
        if confirm_production and meta.get("production_brief") and selected_option:
            meta["selected_option"] = selected_option

        job_id = await self.queue.enqueue(intent.workflow, prompt, meta=meta)
        return {
            "ok": True,
            "job_id": job_id,
            "workflow": intent.workflow,
            "title": intent.title,
            "confidence": intent.confidence,
            "message": f"Status: Menjalankan `{intent.title}`…",
        }

    async def _offer_brief(
        self,
        prompt: str,
        intent: IntentResult,
        meta: dict[str, Any],
    ) -> dict[str, Any]:
        await self.queue.bus.publish(status("Status: Riset referensi & menyusun brief produksi…"))
        brief = await build_production_brief(
            prompt,
            llm=self.engines.llm,
            capability=self.engines.capability,
            enable_web=getattr(self.settings, "enable_web_research", True),
            input_image=meta.get("input_image"),
            input_video=meta.get("input_video") or meta.get("upload_path"),
            meta=meta,
        )
        message = format_brief_message(brief)
        await self.queue.bus.publish(
            confirm(
                "Konfirmasi brief produksi & pilih opsi render sebelum eksekusi.",
                data={
                    "action": "confirm_production",
                    "workflow": intent.workflow,
                    "idea": prompt,
                    "brief": brief,
                    "options": brief.get("options") or [],
                    "recommended_option": brief.get("recommended_option"),
                },
            )
        )
        return {
            "ok": True,
            "needs_confirm": True,
            "confirm_kind": "production_brief",
            "workflow": intent.workflow,
            "title": intent.title,
            "message": message,
            "brief": brief,
            "options": brief.get("options") or [],
            "recommended_option": brief.get("recommended_option"),
            "idea": prompt,
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
                "confirm_kind": "dynamic_workflow",
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
