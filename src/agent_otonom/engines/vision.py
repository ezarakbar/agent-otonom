"""Vision engine: ComfyUI when available, else cinematic slideshow stills."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import httpx

from agent_otonom.engines.ffmpeg_engine import FFmpegEngine

logger = logging.getLogger(__name__)

# Soft cinematic palette for fallback stills
PALETTE = [
    ("0x0f1c2e", "Dawn"),
    ("0x1b2838", "Harbor"),
    ("0x2c1810", "Ember"),
    ("0x102820", "Forest"),
    ("0x1a1028", "Night"),
    ("0x241c14", "Dust"),
]


class VisionEngine:
    def __init__(self, comfyui_url: str, ffmpeg: FFmpegEngine) -> None:
        self.comfyui_url = comfyui_url.rstrip("/")
        self.ffmpeg = ffmpeg
        self._backend: str | None = None

    async def resolve_backend(self) -> str:
        if self._backend:
            return self._backend
        if await self._comfy_ok():
            self._backend = "comfyui"
        else:
            self._backend = "slideshow"
        return self._backend

    async def _comfy_ok(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                r = await client.get(f"{self.comfyui_url}/system_stats")
                return r.status_code == 200
        except Exception:
            try:
                async with httpx.AsyncClient(timeout=2.0) as client:
                    r = await client.get(self.comfyui_url)
                    return r.status_code < 500
            except Exception:
                return False

    async def make_visuals(
        self,
        scenes: list[str],
        out_dir: Path,
        *,
        quality: str = "medium",
    ) -> tuple[list[Path], str]:
        """Create one visual asset per scene. Returns (paths, backend)."""
        out_dir.mkdir(parents=True, exist_ok=True)
        backend = await self.resolve_backend()
        if backend == "comfyui":
            try:
                paths = await self._comfy_stills(scenes, out_dir)
                if paths:
                    return paths, "comfyui"
            except Exception as exc:
                logger.warning("ComfyUI visuals failed (%s); using slideshow", exc)
                backend = "slideshow"

        paths = await self._slideshow_stills(scenes, out_dir, quality=quality)
        return paths, "slideshow"

    async def _comfy_stills(self, scenes: list[str], out_dir: Path) -> list[Path]:
        """Best-effort: many Comfy installs need a workflow JSON.
        If API is up but no workflow configured, fall through empty."""
        # Placeholder: without a bundled workflow graph we cannot reliably generate.
        # Return empty so caller falls back.
        _ = (scenes, out_dir, self.comfyui_url)
        return []

    async def _slideshow_stills(
        self,
        scenes: list[str],
        out_dir: Path,
        *,
        quality: str = "medium",
    ) -> list[Path]:
        w, h = (1080, 1920)
        if quality == "low":
            w, h = (720, 1280)
        elif quality == "high":
            w, h = (1080, 1920)

        paths: list[Path] = []
        for i, scene in enumerate(scenes):
            color, _name = PALETTE[i % len(PALETTE)]
            label = (scene[:36] + "…") if len(scene) > 36 else scene
            png = out_dir / f"scene_{i:02d}.png"
            await self.ffmpeg.color_card(png, color=color, width=w, height=h, label=label)
            paths.append(png)
        return paths
