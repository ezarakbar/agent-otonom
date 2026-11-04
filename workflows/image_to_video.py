"""Image → video: Ken Burns / Comfy img2img + voice + publish pack."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from agent_otonom.production.hardware import build_render_profile
from agent_otonom.production.publish import build_publish_pack


async def run(ctx) -> str | None:
    meta = ctx.meta or {}
    brief = meta.get("production_brief") or {}
    option = meta.get("selected_option") or "kenburns_talk"
    image = Path(meta.get("input_image") or brief.get("input_image") or "")
    if not image.is_file():
        raise RuntimeError(
            "Image-to-video butuh file gambar. Upload image dulu, lalu konfirmasi opsi."
        )

    out_dir: Path = ctx.settings.outputs_dir / ctx.job_id
    out_dir.mkdir(parents=True, exist_ok=True)
    topic = meta.get("topic") or ctx.prompt
    target_sec = brief.get("target_duration_sec") or meta.get("duration_sec") or 5
    try:
        target_sec = float(target_sec)
    except (TypeError, ValueError):
        target_sec = 5.0

    profile = build_render_profile(ctx.capability, target_sec=target_sec, mode="patient")
    script = str(brief.get("script") or topic)
    if len(script.split()) > 24:
        script = " ".join(script.split()[:18])

    (out_dir / "source_image").mkdir(exist_ok=True)
    src = out_dir / "source_image" / image.name
    if image.resolve() != src.resolve():
        shutil.copy2(image, src)

    frames_dir = out_dir / "frames"
    frames_dir.mkdir(exist_ok=True)
    frame = frames_dir / "scene_00.png"

    await ctx.set_status(f"Status: Image→video opsi `{option}`…")
    await ctx.set_progress(15, "Status: Menyiapkan visual…")

    if option == "still_pack_only":
        shutil.copy2(src, frame)
        pack = await build_publish_pack(
            llm=ctx.engines.llm,
            ffmpeg=ctx.engines.ffmpeg,
            out_dir=out_dir / "publish",
            video_path=None,
            brief=brief or {"theme": topic, "script": script, "logline": topic},
            topic=topic,
        )
        note = out_dir / "PACK_ONLY.txt"
        note.write_text(
            "Mode still_pack_only: metadata + thumbnail dari gambar, tanpa video motion.\n"
            f"Pack: {out_dir / 'publish'}\n",
            encoding="utf-8",
        )
        await ctx.set_progress(100, "Status: Pack selesai")
        await ctx.set_status(f"Selesai pack: {out_dir / 'publish'} | thumb={pack.get('thumbnail_path')}")
        return str(out_dir / "publish" / "UPLOAD_READY.md")

    if option == "comfy_img2img":
        if not await ctx.engines.vision.available():
            raise RuntimeError("ComfyUI wajib untuk opsi comfy_img2img")
        await ctx.set_status("Status: ComfyUI img2img refine…")
        prompt = (brief.get("scenes") or [{}])[0].get("visual_prompt") if brief.get("scenes") else topic
        prompt = prompt or topic
        await ctx.engines.vision.img2img(
            src, str(prompt), frame, quality=profile.quality_key, denoise=0.42
        )
    else:
        # kenburns_talk — use source image as-is (convert via ffmpeg if needed)
        if src.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
            await ctx.engines.ffmpeg.run(
                ["-i", str(src), "-frames:v", "1", str(frame)]
            )
        else:
            shutil.copy2(src, frame)

    await ctx.set_progress(35, "Status: GPT-SoVITS dialog…")
    if not await ctx.engines.voice.available() and not getattr(ctx.settings, "allow_engine_fallback", False):
        raise RuntimeError("GPT-SoVITS wajib untuk dialog image→video")
    voice = out_dir / "voice.wav"
    await ctx.engines.voice.synthesize(script, voice)

    await ctx.set_progress(50, "Status: Mix audio background…")
    bg = out_dir / "bg.wav"
    mixed = out_dir / "mix.wav"
    await ctx.engines.ffmpeg.make_ambience(bg, seconds=target_sec + 0.5, kind="cafe")
    await ctx.engines.ffmpeg.mix_voice_and_bg(
        voice, bg, mixed, bg_volume=0.2, target_seconds=target_sec
    )

    await ctx.set_progress(70, "Status: Render motion…")
    final = out_dir / "final.mp4"
    await ctx.engines.ffmpeg.cinematic_from_stills(
        [frame],
        mixed,
        final,
        width=profile.out_width,
        height=profile.out_height,
        target_seconds=target_sec,
    )

    await ctx.set_progress(88, "Status: Pack upload…")
    pack = await build_publish_pack(
        llm=ctx.engines.llm,
        ffmpeg=ctx.engines.ffmpeg,
        out_dir=out_dir / "publish",
        video_path=final,
        brief=brief or {"theme": topic, "script": script, "logline": topic},
        topic=topic,
    )
    (out_dir / "storyboard.json").write_text(
        json.dumps({"option": option, "brief": brief, "pack_titles": pack.get("titles")}, indent=2),
        encoding="utf-8",
    )
    await ctx.set_progress(100, "Status: Image→video siap upload")
    await ctx.set_status(f"Selesai: {final} | {(pack.get('titles') or ['video'])[0]}")
    return str(final)
