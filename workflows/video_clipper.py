"""Built-in workflow: video clipper — extract interesting segments."""

from __future__ import annotations

from pathlib import Path


async def run(ctx) -> str | None:
    meta = ctx.meta or {}
    input_video = meta.get("input_video") or meta.get("upload_path")
    if not input_video:
        # look for recent upload referenced in prompt path-like tokens
        raise ValueError(
            "Video Clipper membutuhkan input video. Unggah file lewat WebGUI "
            "atau sertakan path absolut (.mp4/.mov/.mkv)."
        )

    src = Path(input_video)
    if not src.exists():
        raise FileNotFoundError(f"Video tidak ditemukan: {src}")

    out_dir: Path = ctx.settings.outputs_dir / ctx.job_id
    out_dir.mkdir(parents=True, exist_ok=True)

    await ctx.set_status("Status: Menganalisis video…")
    await ctx.set_progress(10, "Status: Probe durasi…")
    duration = await ctx.engines.ffmpeg.duration(src)
    if duration <= 0:
        duration = 30.0

    await ctx.set_status("Status: Memilih segmen menarik…")
    await ctx.set_progress(30, "Status: Heuristik highlight…")
    segments = _pick_segments(duration, prompt=ctx.prompt)

    # Optional LLM refinement
    try:
        if await ctx.engines.llm.available() and duration >= 8:
            data = await ctx.engines.llm.generate_json(
                prompt=(
                    f"Video duration={duration:.1f}s. User request: {ctx.prompt}\n"
                    "Pilih 2-4 segmen highlight sebagai JSON "
                    '{"segments":[{"start":0,"end":3},...]} dalam detik, tanpa overlap.'
                ),
                system="Reply JSON only.",
                temperature=0.2,
            )
            segs = data.get("segments") or []
            parsed = []
            for s in segs:
                start = float(s.get("start", 0))
                end = float(s.get("end", start + 2))
                if end > start and start >= 0 and end <= duration + 0.5:
                    parsed.append((start, min(end, duration)))
            if parsed:
                segments = parsed
    except Exception:
        pass

    await ctx.set_status("Status: Memotong & menggabungkan (FFmpeg)…")
    await ctx.set_progress(60, "Status: Cut & concat…")
    final = out_dir / "highlights.mp4"
    await ctx.engines.ffmpeg.cut_segments(src, segments, final)

    await ctx.set_progress(100, "Status: Clipper selesai")
    await ctx.set_status(f"Selesai: {final}")
    return str(final)


def _pick_segments(duration: float, prompt: str = "") -> list[tuple[float, float]]:
    """Simple heuristic: take early hook, mid peak, late beat."""
    if duration <= 8:
        return [(0.0, duration)]
    clip = min(4.0, duration / 4)
    points = [0.05, 0.45, 0.75]
    segs: list[tuple[float, float]] = []
    for p in points:
        start = max(0.0, duration * p)
        end = min(duration, start + clip)
        if end - start >= 1.0:
            segs.append((start, end))
    # dedupe / merge tiny overlaps
    return segs[:3] or [(0.0, min(6.0, duration))]
