"""Built-in workflow: cinematic short (storyboard → SoVITS → ComfyUI → ffmpeg)."""

from __future__ import annotations

import json
from pathlib import Path


async def run(ctx) -> str | None:
    topic = (ctx.meta or {}).get("topic") or ctx.prompt
    out_dir: Path = ctx.settings.outputs_dir / ctx.job_id
    out_dir.mkdir(parents=True, exist_ok=True)

    if not getattr(ctx.settings, "allow_engine_fallback", False):
        await _require_primary_engines(ctx)

    await ctx.set_status("Status: Menulis naskah & storyboard (Ollama)…")
    await ctx.set_progress(8, "Status: Menulis naskah…")

    board = await _write_storyboard(ctx, topic)
    script = board["script"]
    scenes = board["scenes"]
    visual_prompts = [s["visual_prompt"] for s in scenes]
    (out_dir / "script.txt").write_text(script, encoding="utf-8")
    (out_dir / "storyboard.json").write_text(
        json.dumps(board, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    await ctx.set_status("Status: Voiceover via GPT-SoVITS…")
    await ctx.set_progress(25, "Status: Menjalankan GPT-SoVITS…")
    wav = out_dir / "voice.wav"
    backend = await ctx.engines.voice.synthesize(script, wav)
    await ctx.set_status(f"Status: Voiceover selesai ({backend})")

    await ctx.set_status("Status: Generate visual via ComfyUI…")
    await ctx.set_progress(45, "Status: ComfyUI txt2img…")
    quality = getattr(ctx.capability, "quality_profile", "medium")
    images, vback = await ctx.engines.vision.make_visuals(
        visual_prompts, out_dir / "frames", quality=quality
    )
    await ctx.set_status(f"Status: Visual siap ({vback}, {len(images)} scene)")

    await ctx.set_status(f"Status: Merender video via FFmpeg ({ctx.engines.ffmpeg.encoder})…")
    await ctx.set_progress(70, "Status: Render FFmpeg…")
    final = out_dir / "final.mp4"
    width, height = (720, 1280) if quality == "low" else (1080, 1920)
    await ctx.engines.ffmpeg.cinematic_from_stills(
        images, wav, final, width=width, height=height
    )

    await ctx.set_progress(100, "Status: Cinematic short selesai")
    await ctx.set_status(f"Selesai: {final}")
    return str(final)


async def _require_primary_engines(ctx) -> None:
    missing: list[str] = []
    if not await ctx.engines.vision.available():
        missing.append(f"ComfyUI ({ctx.engines.vision.comfyui_url})")
    if not await ctx.engines.voice.available():
        missing.append(f"GPT-SoVITS ({ctx.engines.voice.sovits_url})")
    if missing:
        raise RuntimeError(
            "Engine utama belum jalan: "
            + ", ".join(missing)
            + ". Jalankan ComfyUI (image/video) dan GPT-SoVITS (audio), lalu ulangi perintah."
        )


async def _write_storyboard(ctx, topic: str) -> dict:
    system = (
        "You are a film director for short vertical videos. Reply JSON only. "
        "Match the user's subject, place, time of day, and mood exactly. "
        "Do not invent a generic sunset harbor unless the user asked for it. "
        "visual_prompt must be English, photoreal, specific (lens, light, action, location). "
        "script is the spoken voiceover in the user's language. 65-110 words, 3-5 scenes."
    )
    prompt = (
        "Buat storyboard video pendek dari permintaan ini:\n"
        f"{topic}\n\n"
        "JSON schema:\n"
        "{"
        '"language":"id|en",'
        '"script":"full voiceover",'
        '"scenes":[{"title":"...","voiceover":"...","visual_prompt":"..."}]'
        "}"
    )
    try:
        if await ctx.engines.llm.available():
            data = await ctx.engines.llm.generate_json(prompt, system=system, temperature=0.55)
            board = _normalize_board(data, topic)
            if board["scenes"] and len(board["script"].split()) >= 20:
                return board
    except Exception:
        pass
    return _fallback_board(topic)


def _normalize_board(data: dict, topic: str) -> dict:
    scenes_in = data.get("scenes") if isinstance(data, dict) else None
    scenes: list[dict] = []
    if isinstance(scenes_in, list):
        for item in scenes_in[:5]:
            if isinstance(item, str):
                scenes.append(
                    {
                        "title": item[:40],
                        "voiceover": item,
                        "visual_prompt": _visual_from_topic(topic, item),
                    }
                )
            elif isinstance(item, dict):
                voice = str(item.get("voiceover") or item.get("narration") or item.get("text") or "").strip()
                visual = str(item.get("visual_prompt") or item.get("prompt") or "").strip()
                title = str(item.get("title") or voice[:32] or "scene").strip()
                if not visual:
                    visual = _visual_from_topic(topic, voice or title)
                if voice or visual:
                    scenes.append(
                        {
                            "title": title,
                            "voiceover": voice or visual,
                            "visual_prompt": visual,
                        }
                    )
    script = str((data or {}).get("script") or "").strip()
    if not script:
        script = " ".join(s["voiceover"] for s in scenes).strip()
    if not scenes:
        return _fallback_board(topic)
    return {
        "language": str((data or {}).get("language") or "id"),
        "script": script,
        "scenes": scenes,
    }


def _fallback_board(topic: str) -> dict:
    clean = " ".join(str(topic).split())
    beats = [
        ("Establishing", f"Wide establishing shot of {clean}, cinematic photoreal, environment and scale"),
        ("Detail", f"Intimate detail shot from the world of {clean}, tactile textures, cinematic lighting"),
        ("Motion", f"Human-scale moment connected to {clean}, natural gesture, documentary-cinematic"),
        ("Close", f"Emotional close-up still that concludes {clean}, rim light, film grain"),
    ]
    script = (
        f"{clean}. "
        "Gambar mengikuti permintaan itu secara langsung: lokasi, waktu, dan suasana yang diminta. "
        "Kamera mendekat ke detil, lalu ke gerakan manusia di dalamnya. "
        "Di detik terakhir, satu gambar penutup yang masih setia pada ide yang sama."
    )
    scenes = [
        {"title": t, "voiceover": script, "visual_prompt": p} for t, p in beats
    ]
    # Split voiceover-ish lines from the topic itself when it is long
    return {"language": "id", "script": script, "scenes": scenes}


def _visual_from_topic(topic: str, extra: str = "") -> str:
    base = " ".join(str(topic).split())
    more = " ".join(str(extra).split())[:180]
    if more and more.lower() not in base.lower():
        return f"{base}. {more}. cinematic photoreal still, dramatic lighting, 35mm film"
    return f"{base}, cinematic photoreal still, dramatic lighting, 35mm film, vertical frame"
