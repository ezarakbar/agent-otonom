"""Dynamic workflow generator — LLM writes a new Python workflow module."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from agent_otonom.engines.llm import OllamaEngine
from agent_otonom.workflow.sandbox import WorkflowSandbox

logger = logging.getLogger(__name__)

TEMPLATE_HINT = '''
You write ONE Python module for AGENT OTONOM.
Requirements:
- Define: async def run(ctx) -> str | None
- ctx has: job_id, prompt, meta, engines, settings, set_status(msg), set_progress(pct, msg), emit
- ctx.engines.llm, .voice, .vision, .ffmpeg are available
- For image/video ALWAYS use ctx.engines.vision.make_visuals (ComfyUI)
- For speech ALWAYS use ctx.engines.voice.synthesize (GPT-SoVITS)
- Do not invent color cards or skip those engines
- Return absolute path string to final output file, or None
- NO os/subprocess/socket/sys/open/eval/exec imports or calls
- Keep it simple; prefer ctx.engines helpers
- Use only asyncio, json, re, math, typing if needed

Example skeleton:
async def run(ctx):
    await ctx.set_status("Status: Memproses…")
    await ctx.set_progress(10, "Status: Memulai…")
    # ... use engines ...
    return str(out_path)
'''


class WorkflowGenerator:
    def __init__(
        self,
        llm: OllamaEngine,
        generated_dir: Path,
        sandbox: WorkflowSandbox | None = None,
    ) -> None:
        self.llm = llm
        self.generated_dir = generated_dir
        self.sandbox = sandbox or WorkflowSandbox()
        self.generated_dir.mkdir(parents=True, exist_ok=True)

    def _slug(self, idea: str) -> str:
        s = re.sub(r"[^a-zA-Z0-9]+", "_", idea.lower()).strip("_")
        s = s[:40] or "custom_task"
        ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        return f"gen_{s}_{ts}"

    async def generate(self, idea: str) -> tuple[str, Path, list[str]]:
        """Returns (workflow_id, path, warnings). Raises on sandbox failure."""
        wid = self._slug(idea)
        system = "You are a senior Python engineer. Output ONLY Python code, no markdown."
        prompt = (
            f"{TEMPLATE_HINT}\n\n"
            f"User task idea:\n{idea}\n\n"
            "Implement run(ctx) that reasonably fulfills the task using available engines. "
            "If the task is media-related, produce a file under ctx.settings.outputs_dir / ctx.job_id."
        )
        raw = await self.llm.generate(prompt, system=system, temperature=0.2)
        source = _strip_fences(raw)
        result = self.sandbox.validate_source(source)
        if not result.ok:
            # fallback minimal safe workflow
            logger.warning("Generated code failed sandbox: %s — using safe stub", result.errors)
            source = _safe_stub(idea)
            result = self.sandbox.validate_source(source)
            if not result.ok:
                raise ValueError(f"Sandbox rejected workflow: {result.errors}")

        path = self.generated_dir / f"{wid}.py"
        header = (
            f'"""Auto-generated workflow for: {idea[:120]}\n'
            f'Generated at {datetime.now(timezone.utc).isoformat()}\n"""\n\n'
        )
        path.write_text(header + source, encoding="utf-8")
        audit = self.generated_dir / f"{wid}.audit.txt"
        audit.write_text(
            f"idea: {idea}\nerrors: {result.errors}\nwarnings: {result.warnings}\n",
            encoding="utf-8",
        )
        return wid, path, result.warnings


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:python)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _safe_stub(idea: str) -> str:
    return f'''
async def run(ctx):
    """Safe fallback workflow."""
    await ctx.set_status("Status: Workflow dinamis (stub aman)…")
    await ctx.set_progress(20, "Status: Menyiapkan output…")
    out_dir = ctx.settings.outputs_dir / ctx.job_id
    out_dir.mkdir(parents=True, exist_ok=True)
    note = out_dir / "result.txt"
    note.write_text(
        "Tugas: {idea[:500]}\\n\\n"
        "Generator memakai stub aman karena kode LLM tidak lolos sandbox.\\n"
        "Perbaiki manual atau ulangi dengan prompt lebih spesifik.\\n",
        encoding="utf-8",
    )
    await ctx.set_progress(100, "Status: Stub selesai")
    return str(note)
'''.lstrip()
