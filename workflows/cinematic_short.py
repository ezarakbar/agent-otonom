"""Built-in workflow: cinematic short (script → voice → visuals → ffmpeg)."""

from __future__ import annotations

import re
import shutil
from pathlib import Path


async def run(ctx) -> str | None:
    topic = (ctx.meta or {}).get("topic") or ctx.prompt
    out_dir: Path = ctx.settings.outputs_dir / ctx.job_id
    out_dir.mkdir(parents=True, exist_ok=True)

    await ctx.set_status("Status: Menulis naskah (Ollama)…")
    await ctx.set_progress(8, "Status: Menulis naskah…")

    script = await _write_script(ctx, topic)
    (out_dir / "script.txt").write_text(script, encoding="utf-8")
    scenes = _split_scenes(script)

    await ctx.set_status("Status: Voiceover…")
    await ctx.set_progress(25, "Status: Menjalankan voice engine…")
    wav = out_dir / "voice.wav"
    backend = await ctx.engines.voice.synthesize(script, wav)
    await ctx.set_status(f"Status: Voiceover selesai ({backend})")

    await ctx.set_status("Status: Membuat visual…")
    await ctx.set_progress(45, "Status: Vision engine…")
    quality = getattr(ctx.capability, "quality_profile", "medium")
    images, vback = await ctx.engines.vision.make_visuals(scenes, out_dir / "frames", quality=quality)
    await ctx.set_status(f"Status: Visual siap ({vback}, {len(images)} scene)")

    await ctx.set_status(f"Status: Merender video via FFmpeg ({ctx.engines.ffmpeg.encoder})…")
    await ctx.set_progress(70, "Status: Render FFmpeg…")
    draft = out_dir / "draft.mp4"
    await ctx.engines.ffmpeg.slideshow(images, wav, draft)

    final = out_dir / "final.mp4"
    await ctx.set_progress(88, "Status: Subtitle overlay…")
    try:
        await ctx.engines.ffmpeg.burn_subtitle_text(draft, scenes[0] if scenes else topic, final)
    except Exception:
        shutil.copy2(draft, final)

    await ctx.set_progress(100, "Status: Cinematic short selesai")
    await ctx.set_status(f"Selesai: {final}")
    return str(final)


async def _write_script(ctx, topic: str) -> str:
    system = (
        "You write short vertical-video voiceover scripts. "
        "Language: Indonesian if the user writes Indonesian, else English. "
        "65-110 words. 3-5 short scenes. Cinematic, concrete imagery. "
        "No markdown, no bullet points — plain paragraphs separated by blank lines."
    )
    try:
        if await ctx.engines.llm.available():
            text = await ctx.engines.llm.generate(
                f"Buatkan naskah voiceover sinematik untuk: {topic}",
                system=system,
                temperature=0.7,
            )
            if text and len(text.split()) >= 40:
                return text.strip()
    except Exception:
        pass
    return (
        f"Di tengah senja yang tenang, sebuah cerita tentang {topic} mulai terungkap. "
        "Cahaya lembut menyentuh permukaan yang sunyi, membawa kita lebih dekat ke detil yang terlupakan. "
        "Setiap langkah terasa lebih berat, namun harapan tetap menyala di kejauhan. "
        "Angin membawa bisikan masa lalu, sementara masa depan menunggu tanpa suara. "
        "Dan di detik terakhir, kita memahami: keindahan sering hadir dalam kesederhanaan."
    )


def _split_scenes(script: str) -> list[str]:
    parts = [p.strip() for p in re.split(r"\n\s*\n", script) if p.strip()]
    if len(parts) >= 2:
        return parts[:5]
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", script) if s.strip()]
    if not sentences:
        return [script[:80] or "Scene"]
    # group into ~3 scenes
    n = max(1, len(sentences) // 3)
    scenes = []
    for i in range(0, len(sentences), n):
        scenes.append(" ".join(sentences[i : i + n]))
    return scenes[:5] or [script[:80]]
