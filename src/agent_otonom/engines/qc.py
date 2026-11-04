"""Pre-upload quality control gate."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent_otonom.engines.ffmpeg_engine import FFmpegEngine


async def run_qc(
    *,
    ffmpeg: FFmpegEngine,
    video: Path,
    voice: Path | None,
    frames_dir: Path | None,
    publish_dir: Path | None,
    expect_human: bool,
    target_sec: float | None,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    ok = True

    def add(name: str, passed: bool, detail: str) -> None:
        nonlocal ok
        checks.append({"name": name, "ok": passed, "detail": detail})
        if not passed:
            ok = False

    add("video_exists", video.is_file(), str(video))
    dur = await ffmpeg.duration(video) if video.is_file() else 0.0
    add("video_duration", dur >= 1.0, f"{dur:.2f}s")
    if target_sec:
        add(
            "duration_near_target",
            abs(dur - float(target_sec)) <= max(1.5, float(target_sec) * 0.35),
            f"got {dur:.2f}s target {target_sec}s",
        )

    info = await ffmpeg.probe(video) if video.is_file() else {}
    streams = info.get("streams") or []
    has_v = any(s.get("codec_type") == "video" for s in streams)
    has_a = any(s.get("codec_type") == "audio" for s in streams)
    add("has_video_stream", has_v, "video stream")
    add("has_audio_stream", has_a, "audio stream")

    if voice:
        add("voice_wav", voice.is_file() and voice.stat().st_size > 1000, str(voice))

    if frames_dir and frames_dir.is_dir():
        n = len(list(frames_dir.glob("*.png")) + list(frames_dir.glob("*.webp")))
        add("visual_assets", n >= 1, f"{n} assets")

    if publish_dir and publish_dir.is_dir():
        add("publish_guide", (publish_dir / "UPLOAD_READY.md").is_file(), "UPLOAD_READY.md")
        add(
            "thumbnail",
            (publish_dir / "thumbnail.jpg").is_file() or (publish_dir / "thumbnail.png").is_file(),
            "thumbnail",
        )

    if expect_human:
        add(
            "human_prompt_intent",
            True,
            "character requested — verify visually before public upload",
        )

    report = {"ok": ok, "checks": checks, "duration_sec": dur}
    return report


def write_qc_report(out_dir: Path, report: dict[str, Any]) -> Path:
    path = out_dir / "QC_REPORT.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md = out_dir / "QC_REPORT.md"
    lines = [f"# QC {'PASS' if report.get('ok') else 'FAIL'}", ""]
    for c in report.get("checks") or []:
        mark = "OK" if c.get("ok") else "FAIL"
        lines.append(f"- [{mark}] **{c.get('name')}**: {c.get('detail')}")
    md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
