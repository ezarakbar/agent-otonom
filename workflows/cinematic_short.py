"""Generative cinematic short FROM TEXT — audio + still + motion + finish + QC + pack."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from agent_otonom.engines.lifecycle import ensure_media_engines, release_media_engines
from agent_otonom.engines.qc import run_qc, write_qc_report
from agent_otonom.engines.subtitles import burn_srt, script_to_srt
from agent_otonom.production.hardware import build_render_profile
from agent_otonom.production.publish import build_publish_pack


async def run(ctx) -> str | None:
    topic = (ctx.meta or {}).get("topic") or ctx.prompt
    brief = (ctx.meta or {}).get("production_brief") or {}
    option = (ctx.meta or {}).get("selected_option") or "standard"
    out_dir: Path = ctx.settings.outputs_dir / ctx.job_id
    out_dir.mkdir(parents=True, exist_ok=True)

    # Start heavy engines only for this job; always release RAM afterwards.
    await ctx.set_status("Status: Menyalakan ComfyUI + GPT-SoVITS (on-demand)…")
    await ensure_media_engines(
        comfy_base_url=ctx.settings.comfyui_base_url,
        sovits_base_url=ctx.settings.sovits_base_url,
    )
    if not getattr(ctx.settings, "allow_engine_fallback", False):
        await _require_primary_engines(ctx)

    try:
        return await _produce(ctx, topic=topic, brief=brief, option=option, out_dir=out_dir)
    finally:
        await ctx.set_status("Status: Mematikan ComfyUI + GPT-SoVITS (bebasin RAM)…")
        await release_media_engines(comfy_base_url=ctx.settings.comfyui_base_url)


async def _produce(ctx, *, topic: str, brief: dict, option: str, out_dir: Path) -> str | None:
    target_sec = brief.get("target_duration_sec")
    if target_sec is None:
        target_sec = _extract_duration_sec(topic, ctx.meta or {})

    mode = "patient"
    if option == "fast_preview":
        mode = "fast"
    elif option in {"quality_patient", "standard", "generative"}:
        mode = "patient"
    profile = build_render_profile(ctx.capability, target_sec=target_sec, mode=mode)

    await ctx.set_status(
        f"Status: Generatif dari teks · hardware `{profile.name}` · Comfy AnimateDiff"
    )
    await ctx.set_progress(5, "Status: Naskah & storyboard…")

    scenes = list(brief.get("scenes") or [])
    script = str(brief.get("script") or "")
    if not scenes or not script:
        board = await _write_storyboard(ctx, topic, target_sec=target_sec, max_scenes=profile.max_scenes)
        script = board["script"]
        scenes = board["scenes"]
        brief = {**brief, **board}
    scenes = scenes[: profile.max_scenes]
    visual_prompts = [_force_human_prompt(s.get("visual_prompt") or topic, topic) for s in scenes]

    (out_dir / "script.txt").write_text(script, encoding="utf-8")
    (out_dir / "storyboard.json").write_text(
        json.dumps({"brief": brief, "scenes": scenes, "option": option, "mode": "text_to_av"}, indent=2),
        encoding="utf-8",
    )

    # 1) TEXT → AUDIO (GPT-SoVITS)
    await ctx.set_status("Status: Teks → audio (GPT-SoVITS)…")
    await ctx.set_progress(15, "Status: GPT-SoVITS…")
    voice = out_dir / "voice.wav"
    vback = await ctx.engines.voice.synthesize(script, voice)
    await ctx.set_status(f"Status: Audio siap ({vback})")

    mix_seconds = float(target_sec) if target_sec else max(5.0, await ctx.engines.ffmpeg.duration(voice) or 5.0)
    bg_kind = "cafe" if re.search(r"kopi|coffee|cafe|kafe", topic, re.I) else "room"
    bg = out_dir / "bg.wav"
    await ctx.engines.ffmpeg.make_ambience(bg, seconds=mix_seconds + 0.5, kind=bg_kind)
    mastered = out_dir / "master.wav"
    await ctx.engines.audio.master_mix(
        voice, bg, mastered, target_seconds=mix_seconds, bg_volume=0.18
    )

    # 2) TEXT → PHOTO (storyboard stills)
    await ctx.set_status("Status: Teks → foto keyframe (ComfyUI)…")
    await ctx.set_progress(30, "Status: ComfyUI stills…")
    frames_dir = out_dir / "frames"
    stills, sback = await ctx.engines.vision.make_visuals(
        visual_prompts, frames_dir, quality=profile.quality_key
    )
    await ctx.set_status(f"Status: Keyframe siap ({sback}, {len(stills)})")

    # 3) TEXT → VIDEO MOTION (AnimateDiff) — generative, not photo-warp
    await ctx.set_status("Status: Teks → video gerak (AnimateDiff)… sabar di CPU…")
    await ctx.set_progress(45, "Status: AnimateDiff…")
    clips: list[Path] = []
    motion_backend = "none"
    for i, prompt in enumerate(visual_prompts):
        clip = out_dir / f"motion_{i:02d}.mp4"
        try:
            path, motion_backend = await ctx.engines.vision.make_motion_clip(
                prompt,
                clip,
                quality=profile.quality_key,
                timeout=float(profile.comfy_timeout_sec),
            )
            clips.append(path)
            await ctx.set_status(f"Status: Clip gerak {i+1}/{len(visual_prompts)} OK ({motion_backend})")
        except Exception as exc:
            await ctx.set_status(f"Status: AnimateDiff gagal ({exc}); fallback Ken Burns keyframe")
            # Last-resort motion from GENERATED still (still originated from text)
            kb = out_dir / f"kb_{i:02d}.mp4"
            await ctx.engines.ffmpeg.cinematic_from_stills(
                [stills[i]],
                mastered,
                kb,
                width=profile.out_width,
                height=profile.out_height,
                target_seconds=mix_seconds / max(1, len(visual_prompts)),
            )
            clips.append(kb)
            motion_backend = "kenburns_from_generated_still"

    # Concat motion clips if multiple
    await ctx.set_progress(70, "Status: Gabung timeline…")
    video_only = out_dir / "video_only.mp4"
    if len(clips) == 1:
        shutil.copy2(clips[0], video_only)
    else:
        concat = out_dir / "motion_concat.txt"
        concat.write_text("\n".join(f"file '{c.resolve()}'" for c in clips), encoding="utf-8")
        await ctx.engines.ffmpeg.run(
            ["-f", "concat", "-safe", "0", "-i", str(concat), "-c", "copy", str(video_only)]
        )

    # 4) Lipsync (if service up) + mux mastered audio
    await ctx.set_progress(78, "Status: Lipsync / mux audio…")
    lip_out = out_dir / "lip.mp4"
    lip_path, lip_back = await ctx.engines.lipsync.apply(video_only, mastered, lip_out)
    await ctx.set_status(f"Status: Lipsync mode: {lip_back}")

    draft = out_dir / "draft.mp4"
    try:
        await ctx.engines.ffmpeg.mux_av(lip_path, mastered, draft, shortest=True)
    except Exception:
        shutil.copy2(lip_path, draft)

    # Fit duration
    timed = out_dir / "timed.mp4"
    await ctx.engines.ffmpeg.run(
        [
            "-i",
            str(draft),
            "-t",
            f"{mix_seconds:.3f}",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            str(timed),
        ]
    )

    # 5) Subtitles
    await ctx.set_progress(86, "Status: Subtitle…")
    srt = script_to_srt(script, mix_seconds, out_dir / "captions.srt")
    subtitled = out_dir / "subtitled.mp4"
    try:
        await burn_srt(ctx.engines.ffmpeg, timed, srt, subtitled)
        final_src = subtitled
    except Exception:
        final_src = timed

    final = out_dir / "final.mp4"
    shutil.copy2(final_src, final)

    # 6) Publish pack
    await ctx.set_progress(92, "Status: Pack upload…")
    pack = await build_publish_pack(
        llm=ctx.engines.llm,
        ffmpeg=ctx.engines.ffmpeg,
        out_dir=out_dir / "publish",
        video_path=final,
        brief=brief or {"theme": topic, "script": script, "logline": topic},
        topic=topic,
    )

    # 7) QC gate
    await ctx.set_progress(96, "Status: QC…")
    expect_human = bool(re.search(r"orang|manusia|person|kopi|coffee|minum", topic, re.I))
    report = await run_qc(
        ffmpeg=ctx.engines.ffmpeg,
        video=final,
        voice=voice,
        frames_dir=frames_dir,
        publish_dir=out_dir / "publish",
        expect_human=expect_human,
        target_sec=float(target_sec) if target_sec else mix_seconds,
    )
    report["motion_backend"] = motion_backend
    report["lipsync"] = lip_back
    report["voice"] = vback
    write_qc_report(out_dir, report)
    if not report.get("ok"):
        await ctx.set_status("Status: QC WARN — cek QC_REPORT.md sebelum upload publik")
    else:
        await ctx.set_status("Status: QC PASS — siap upload")

    await ctx.set_progress(100, "Status: Produksi generatif selesai")
    title0 = (pack.get("titles") or ["video"])[0]
    await ctx.set_status(f"Selesai: {final} | {title0} | motion={motion_backend}")
    return str(final)


async def _require_primary_engines(ctx) -> None:
    missing: list[str] = []
    if not await ctx.engines.vision.available():
        missing.append(f"ComfyUI ({ctx.engines.vision.comfyui_url})")
    if not await ctx.engines.voice.available():
        missing.append(f"GPT-SoVITS ({ctx.engines.voice.sovits_url})")
    if missing:
        raise RuntimeError("Engine utama belum jalan: " + ", ".join(missing))


def _extract_duration_sec(topic: str, meta: dict) -> float | None:
    if meta.get("duration_sec"):
        try:
            return float(meta["duration_sec"])
        except (TypeError, ValueError):
            pass
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:detik|seconds?|secs?)\b", str(topic), re.I)
    if m:
        return float(m.group(1).replace(",", "."))
    return None


def _force_human_prompt(visual: str, topic: str) -> str:
    text = " ".join(str(visual).split())
    need_human = bool(re.search(r"orang|manusia|person|people|woman|man|kopi|coffee|minum", topic, re.I))
    if need_human and not re.search(r"\b(human|person|man|woman|adult|people)\b", text, re.I):
        text = "photoreal real adult human clearly visible in frame, " + text
    if re.search(r"kopi|coffee", topic, re.I) and "coffee" not in text.lower() and "mug" not in text.lower():
        text += ", drinking coffee from a ceramic mug, subtle natural motion, steam rising"
    text += ", living motion, natural body language"
    return text


async def _write_storyboard(ctx, topic: str, *, target_sec: float | None, max_scenes: int) -> dict:
    system = (
        "Film director. JSON only. Photoreal real adult human when asked. "
        "visual_prompt English with action + motion cues."
    )
    prompt = (
        f"Durasi:{target_sec or 'n/a'} MaxScenes:{max_scenes}\nPermintaan:{topic}\n"
        'JSON:{"theme":"...","script":"...","scenes":[{"title":"...","voiceover":"...","visual_prompt":"..."}]}'
    )
    try:
        if await ctx.engines.llm.available():
            data = await ctx.engines.llm.generate_json(prompt, system=system, temperature=0.45)
            if isinstance(data, dict) and data.get("scenes"):
                scenes = data["scenes"][:max_scenes]
                script = data.get("script") or " ".join(
                    str(s.get("voiceover") or "") for s in scenes if isinstance(s, dict)
                )
                return {"theme": data.get("theme") or topic[:80], "script": script, "scenes": scenes}
    except Exception:
        pass
    script = "Kopi ini hangat. Aku butuh jeda sejenak hari ini."
    visual = (
        "photoreal adult human drinking coffee from ceramic mug in cozy cafe, "
        "subtle natural motion, steam, morning light, 35mm, realistic skin"
    )
    return {
        "theme": "Lifestyle cafe",
        "script": script,
        "scenes": [{"title": "Coffee", "voiceover": script, "visual_prompt": visual}],
    }
