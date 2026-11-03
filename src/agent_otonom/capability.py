"""Hardware & engine capability probe — adapts pipelines to the host PC."""

from __future__ import annotations

import asyncio
import logging
import os
import platform
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from typing import Any

import httpx

from agent_otonom.config import Settings, get_settings

logger = logging.getLogger(__name__)


@dataclass
class CapabilityReport:
    os_name: str
    arch: str
    cpu_count: int
    ram_gb: float
    gpu_vendor: str  # amd | nvidia | intel | apple | unknown | none
    gpu_name: str
    quality_profile: str  # low | medium | high
    video_encoder: str
    tools: dict[str, bool] = field(default_factory=dict)
    engines: dict[str, dict[str, Any]] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _ram_gb() -> float:
    try:
        if hasattr(os, "sysconf"):
            pages = os.sysconf("SC_PAGE_SIZE")
            count = os.sysconf("SC_PHYS_PAGES")
            return round((pages * count) / (1024**3), 1)
    except (ValueError, OSError):
        pass
    try:
        out = subprocess.check_output(["free", "-b"], text=True, timeout=5)
        for line in out.splitlines():
            if line.lower().startswith("mem:"):
                total = int(line.split()[1])
                return round(total / (1024**3), 1)
    except (FileNotFoundError, subprocess.SubprocessError, ValueError, IndexError):
        pass
    return 8.0


def _detect_gpu() -> tuple[str, str]:
    system = platform.system().lower()
    if system == "darwin":
        return "apple", "Apple Silicon / macOS GPU"

    # Linux: lspci
    try:
        out = subprocess.check_output(["lspci"], text=True, timeout=5, stderr=subprocess.DEVNULL)
        for line in out.splitlines():
            low = line.lower()
            if "vga" in low or "3d" in low or "display" in low:
                if "nvidia" in low:
                    return "nvidia", line.split(":", 1)[-1].strip()
                if "amd" in low or "ati" in low or "radeon" in low:
                    return "amd", line.split(":", 1)[-1].strip()
                if "intel" in low:
                    return "intel", line.split(":", 1)[-1].strip()
                return "unknown", line.split(":", 1)[-1].strip()
    except (FileNotFoundError, subprocess.SubprocessError):
        pass

    # Windows: wmic (best-effort)
    try:
        out = subprocess.check_output(
            ["wmic", "path", "win32_VideoController", "get", "name"],
            text=True,
            timeout=5,
            stderr=subprocess.DEVNULL,
        )
        for line in out.splitlines():
            name = line.strip()
            if not name or name.lower() == "name":
                continue
            low = name.lower()
            if "nvidia" in low:
                return "nvidia", name
            if "amd" in low or "radeon" in low:
                return "amd", name
            if "intel" in low:
                return "intel", name
            return "unknown", name
    except (FileNotFoundError, subprocess.SubprocessError):
        pass

    return "none", "No GPU detected"


def _ffmpeg_encoders() -> set[str]:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return set()
    try:
        out = subprocess.check_output(
            [ffmpeg, "-hide_banner", "-encoders"],
            text=True,
            timeout=10,
            stderr=subprocess.STDOUT,
        )
        found: set[str] = set()
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[0].startswith("V"):
                found.add(parts[1])
        return found
    except (subprocess.SubprocessError, OSError):
        return set()


def pick_video_encoder(gpu_vendor: str, encoders: set[str]) -> str:
    preferred: list[str] = []
    if gpu_vendor == "amd":
        preferred = ["h264_amf", "h264_vaapi", "h264_vulkan", "libx264"]
    elif gpu_vendor == "nvidia":
        preferred = ["h264_nvenc", "libx264"]
    elif gpu_vendor == "intel":
        preferred = ["h264_qsv", "h264_vaapi", "libx264"]
    elif gpu_vendor == "apple":
        preferred = ["h264_videotoolbox", "libx264"]
    else:
        preferred = ["libx264"]

    for enc in preferred:
        if enc in encoders or enc == "libx264":
            # libx264 may always be chosen as software fallback even if probe missed it
            if enc == "libx264" or enc in encoders:
                return enc
    return "libx264"


def quality_profile(ram_gb: float, gpu_vendor: str) -> str:
    if ram_gb >= 24 and gpu_vendor in {"nvidia", "amd", "apple"}:
        return "high"
    if ram_gb >= 12:
        return "medium"
    return "low"


async def _http_ok(url: str, timeout: float = 2.0) -> bool:
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.get(url)
            return r.status_code < 500
    except Exception:
        return False


async def probe(settings: Settings | None = None) -> CapabilityReport:
    settings = settings or get_settings()
    gpu_vendor, gpu_name = _detect_gpu()
    ram = _ram_gb()
    encoders = _ffmpeg_encoders()
    encoder = pick_video_encoder(gpu_vendor, encoders)
    profile = quality_profile(ram, gpu_vendor)

    tools = {
        "ffmpeg": shutil.which("ffmpeg") is not None,
        "ffprobe": shutil.which("ffprobe") is not None,
        "ollama": shutil.which("ollama") is not None,
        "espeak": shutil.which("espeak-ng") is not None or shutil.which("espeak") is not None,
        "docker": shutil.which("docker") is not None,
        "piper": bool(settings.piper_bin and PathExists(settings.piper_bin))
        or shutil.which("piper") is not None
        or _find_local_piper(settings) is not None,
    }

    notes: list[str] = []
    if gpu_vendor == "amd":
        notes.append("AMD GPU detected — using AMF/VAAPI path (not NVENC).")
    if gpu_vendor == "nvidia":
        notes.append("NVIDIA GPU detected — NVENC preferred when available.")
    if ram < 12:
        notes.append("RAM under 12 GB — quality profile low; keep workflows light.")
    if encoder == "libx264":
        notes.append("Software H.264 encoder selected (libx264).")

    engines: dict[str, dict[str, Any]] = {}

    ollama_ok = await _http_ok(f"{settings.ollama_base_url.rstrip('/')}/api/tags")
    engines["ollama"] = {
        "available": ollama_ok,
        "base_url": settings.ollama_base_url,
        "model": settings.ollama_model,
        "required": True,
    }
    if not ollama_ok:
        notes.append("Ollama not reachable — start `ollama serve` and pull a model.")

    sovits_ok = await _http_ok(settings.sovits_base_url)
    engines["gpt_sovits"] = {
        "available": sovits_ok,
        "base_url": settings.sovits_base_url,
        "required": False,
    }

    comfy_ok = await _http_ok(settings.comfyui_base_url)
    engines["comfyui"] = {
        "available": comfy_ok,
        "base_url": settings.comfyui_base_url,
        "required": False,
    }

    piper_path = settings.piper_bin or shutil.which("piper") or _find_local_piper(settings)
    engines["piper"] = {
        "available": bool(piper_path),
        "bin": piper_path or "",
        "model": settings.piper_model or _find_local_piper_model(settings) or "",
        "required": False,
    }

    engines["espeak"] = {
        "available": tools["espeak"],
        "required": False,
    }

    engines["ffmpeg"] = {
        "available": tools["ffmpeg"],
        "encoder": encoder,
        "encoders_found": sorted(e for e in encoders if "264" in e or "hevc" in e or "amf" in e),
        "required": True,
    }

    return CapabilityReport(
        os_name=f"{platform.system()} {platform.release()}",
        arch=platform.machine(),
        cpu_count=os.cpu_count() or 1,
        ram_gb=ram,
        gpu_vendor=gpu_vendor,
        gpu_name=gpu_name,
        quality_profile=profile,
        video_encoder=encoder,
        tools=tools,
        engines=engines,
        notes=notes,
    )


def PathExists(p: str) -> bool:
    from pathlib import Path

    return Path(p).exists()


def _find_local_piper(settings: Settings) -> str | None:
    from pathlib import Path

    candidates = [
        settings.agent_root / "piper" / "piper",
        settings.agent_root / "bin" / "piper",
        Path.home() / ".local" / "bin" / "piper",
    ]
    for c in candidates:
        if c.is_file() and os.access(c, os.X_OK):
            return str(c)
    return None


def _find_local_piper_model(settings: Settings) -> str | None:
    from pathlib import Path

    models_dir = settings.agent_root / "models" / "piper"
    if not models_dir.is_dir():
        return None
    for p in sorted(models_dir.glob("*.onnx")):
        return str(p)
    return None


def probe_sync(settings: Settings | None = None) -> CapabilityReport:
    return asyncio.run(probe(settings))
