"""Subtitle / caption generation from script timing."""

from __future__ import annotations

import re
from pathlib import Path

from agent_otonom.engines.ffmpeg_engine import FFmpegEngine


def script_to_srt(script: str, duration: float, out: Path) -> Path:
    """Split script into timed SRT cues spanning total duration."""
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", script.strip()) if s.strip()]
    if not sentences:
        sentences = [script.strip() or "..."]
    duration = max(1.0, float(duration))
    per = duration / len(sentences)
    lines: list[str] = []
    for i, sent in enumerate(sentences):
        start = i * per
        end = min(duration, (i + 1) * per)
        lines.append(str(i + 1))
        lines.append(f"{_ts(start)} --> {_ts(end)}")
        lines.append(sent[:120])
        lines.append("")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    return out


async def burn_srt(ffmpeg: FFmpegEngine, video: Path, srt: Path, out: Path) -> Path:
    # force_style keeps captions readable on Shorts
    vf = f"subtitles={srt}:force_style='Fontsize=28,PrimaryColour=&H00FFFFFF&,Outline=2'"
    try:
        await ffmpeg.run(
            [
                "-i",
                str(video),
                "-vf",
                vf,
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "20",
                "-c:a",
                "copy",
                str(out),
            ]
        )
        return out
    except Exception:
        # drawtext fallback: first line only
        text = srt.read_text(encoding="utf-8").splitlines()
        cue = next((ln for ln in text if ln and not ln.isdigit() and "-->" not in ln), "...")
        return await ffmpeg.burn_subtitle_text(video, cue, out)


def _ts(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    h, rem = divmod(ms, 3600_000)
    m, rem = divmod(rem, 60_000)
    s, milli = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{milli:03d}"
