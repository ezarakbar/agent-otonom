"""Hardware-aware render profiles — portable across PCs."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class RenderProfile:
    name: str  # fast | balanced | quality | patient
    quality_key: str  # passed to VisionEngine
    max_scenes: int
    out_width: int
    out_height: int
    comfy_timeout_sec: float
    prefer_cpu_safe: bool
    notes: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_render_profile(
    capability: Any,
    *,
    target_sec: float | None = None,
    mode: str | None = None,
) -> RenderProfile:
    """Pick a render profile from host probe + request length."""
    ram = float(getattr(capability, "ram_gb", 8) or 8)
    gpu = str(getattr(capability, "gpu_vendor", "unknown") or "unknown")
    base = str(getattr(capability, "quality_profile", "medium") or "medium")

    # Explicit user/mode override
    if mode in {"fast", "balanced", "quality", "patient"}:
        return _named(mode, gpu)

    short = target_sec is not None and target_sec <= 8
    # AMD Polaris / unknown often run Comfy on CPU in this stack
    cpu_heavy = gpu in {"amd", "unknown", "none", "intel"}

    if short and cpu_heavy:
        return RenderProfile(
            name="patient",
            quality_key="balanced_cpu" if ram >= 12 else "fast",
            max_scenes=1,
            out_width=720,
            out_height=1280,
            comfy_timeout_sec=1800,
            prefer_cpu_safe=True,
            notes="Clip pendek di host CPU/AMD: 1 scene, sabar sampai selesai.",
        )
    if short:
        return _named("fast", gpu)
    if base == "high" and gpu in {"nvidia", "apple"}:
        return _named("quality", gpu)
    if ram < 12:
        return _named("fast", gpu)
    if cpu_heavy:
        return RenderProfile(
            name="patient",
            quality_key="balanced_cpu",
            max_scenes=3 if ram >= 16 else 2,
            out_width=720 if ram < 24 else 1080,
            out_height=1280 if ram < 24 else 1920,
            comfy_timeout_sec=2400,
            prefer_cpu_safe=True,
            notes="Host tanpa CUDA modern: resolusi aman, timeout panjang.",
        )
    return _named("balanced", gpu)


def _named(name: str, gpu: str) -> RenderProfile:
    table = {
        "fast": RenderProfile(
            name="fast",
            quality_key="fast",
            max_scenes=2,
            out_width=720,
            out_height=1280,
            comfy_timeout_sec=900,
            prefer_cpu_safe=True,
            notes="Preview cepat.",
        ),
        "balanced": RenderProfile(
            name="balanced",
            quality_key="medium",
            max_scenes=4,
            out_width=1080,
            out_height=1920,
            comfy_timeout_sec=1500,
            prefer_cpu_safe=gpu in {"amd", "intel", "none", "unknown"},
            notes="Default portable.",
        ),
        "quality": RenderProfile(
            name="quality",
            quality_key="high",
            max_scenes=5,
            out_width=1080,
            out_height=1920,
            comfy_timeout_sec=1800,
            prefer_cpu_safe=False,
            notes="GPU kuat.",
        ),
        "patient": RenderProfile(
            name="patient",
            quality_key="balanced_cpu",
            max_scenes=3,
            out_width=720,
            out_height=1280,
            comfy_timeout_sec=2400,
            prefer_cpu_safe=True,
            notes="Lebih lambat tapi tetap selesai.",
        ),
    }
    return table.get(name, table["balanced"])
