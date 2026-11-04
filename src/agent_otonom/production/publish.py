"""Ready-to-upload publish pack: titles, hashtags, captions, thumbnail."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from agent_otonom.engines.ffmpeg_engine import FFmpegEngine
from agent_otonom.engines.llm import OllamaEngine

logger = logging.getLogger(__name__)


async def build_publish_pack(
    *,
    llm: OllamaEngine,
    ffmpeg: FFmpegEngine,
    out_dir: Path,
    video_path: Path | None,
    brief: dict[str, Any],
    topic: str,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    meta = await _llm_meta(llm, topic, brief)
    pack = {
        "titles": meta.get("titles") or _fallback_titles(topic, brief),
        "description": meta.get("description") or _fallback_description(topic, brief),
        "hashtags": meta.get("hashtags") or _fallback_hashtags(topic),
        "captions": meta.get("captions")
        or {
            "tiktok": _fallback_description(topic, brief)[:150],
            "youtube_shorts": _fallback_description(topic, brief)[:100],
            "instagram_reels": _fallback_description(topic, brief)[:150],
        },
        "algorithm_hooks": meta.get("algorithm_hooks")
        or [
            "Hook di 1 detik pertama: aksi manusia jelas (minum kopi / gesture)",
            "Teks on-screen singkat + CTA follow",
            "Posting 3x seminggu di jam aktif lokal",
            "Pakai suara asli + caption; jangan full silent",
        ],
        "thumbnail_text": meta.get("thumbnail_text") or (brief.get("theme") or topic)[:40],
        "platforms": ["youtube_shorts", "tiktok", "instagram_reels", "facebook_reels"],
    }

    thumb = out_dir / "thumbnail.jpg"
    if video_path and video_path.is_file():
        try:
            await _thumbnail_from_video(ffmpeg, video_path, thumb, pack["thumbnail_text"])
            pack["thumbnail_path"] = str(thumb)
        except Exception as exc:
            logger.warning("thumbnail from video failed: %s", exc)
    frames = out_dir / "frames"
    if "thumbnail_path" not in pack and frames.is_dir():
        pngs = sorted(frames.glob("scene_*.png"))
        if pngs:
            try:
                await _thumbnail_from_image(ffmpeg, pngs[0], thumb, pack["thumbnail_text"])
                pack["thumbnail_path"] = str(thumb)
            except Exception as exc:
                logger.warning("thumbnail from frame failed: %s", exc)

    # Platform-ready text files
    (out_dir / "publish.json").write_text(
        json.dumps(pack, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    yt = out_dir / "youtube.txt"
    yt.write_text(
        _yt_block(pack),
        encoding="utf-8",
    )
    tt = out_dir / "tiktok.txt"
    tt.write_text(
        f"{pack['captions'].get('tiktok', '')}\n\n"
        + " ".join(f"#{h.lstrip('#')}" for h in pack["hashtags"][:12]),
        encoding="utf-8",
    )
    ig = out_dir / "instagram.txt"
    ig.write_text(
        f"{pack['captions'].get('instagram_reels', '')}\n\n"
        + " ".join(f"#{h.lstrip('#')}" for h in pack["hashtags"][:20]),
        encoding="utf-8",
    )
    guide = out_dir / "UPLOAD_READY.md"
    guide.write_text(_upload_guide(pack, video_path), encoding="utf-8")
    pack["files"] = {
        "publish_json": str(out_dir / "publish.json"),
        "youtube": str(yt),
        "tiktok": str(tt),
        "instagram": str(ig),
        "guide": str(guide),
        "thumbnail": pack.get("thumbnail_path"),
    }
    return pack


async def _llm_meta(llm: OllamaEngine, topic: str, brief: dict[str, Any]) -> dict[str, Any]:
    if not await llm.available():
        return {}
    system = (
        "You are a short-form growth editor for YouTube Shorts, TikTok, Instagram Reels. "
        "Reply JSON only. Indonesian titles OK if topic is Indonesian. "
        "Hashtags without # prefix. Include algorithm hooks."
    )
    user = (
        f"Topic: {topic}\nTheme: {brief.get('theme')}\nLogline: {brief.get('logline')}\n"
        f"Script: {brief.get('script')}\n\n"
        "JSON: {"
        '"titles":["...","...","..."],'
        '"description":"...",'
        '"hashtags":["..."],'
        '"captions":{"tiktok":"...","youtube_shorts":"...","instagram_reels":"..."},'
        '"algorithm_hooks":["..."],'
        '"thumbnail_text":"3-5 words"'
        "}"
    )
    try:
        data = await llm.generate_json(user, system=system, temperature=0.5)
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        logger.warning("publish LLM failed: %s", exc)
        return {}


async def _thumbnail_from_video(
    ffmpeg: FFmpegEngine, video: Path, out: Path, label: str
) -> None:
    safe = re.sub(r"[:'\\]", "", label)[:36]
    vf = (
        f"thumbnail,scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
        f"drawtext=text='{safe}':fontcolor=white:fontsize=64:x=(w-text_w)/2:y=h-220:"
        f"box=1:boxcolor=black@0.55"
    )
    await ffmpeg.run(
        ["-i", str(video), "-frames:v", "1", "-q:v", "2", "-vf", vf, str(out)]
    )


async def _thumbnail_from_image(
    ffmpeg: FFmpegEngine, image: Path, out: Path, label: str
) -> None:
    safe = re.sub(r"[:'\\]", "", label)[:36]
    vf = (
        f"scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
        f"drawtext=text='{safe}':fontcolor=white:fontsize=64:x=(w-text_w)/2:y=h-220:"
        f"box=1:boxcolor=black@0.55"
    )
    await ffmpeg.run(["-i", str(image), "-frames:v", "1", "-q:v", "2", "-vf", vf, str(out)])


def _fallback_titles(topic: str, brief: dict[str, Any]) -> list[str]:
    theme = brief.get("theme") or topic
    return [
        f"{theme} — momen nyata ☕",
        f"Jeda sejenak: {theme}",
        f"POV: {topic[:48]}",
    ]


def _fallback_description(topic: str, brief: dict[str, Any]) -> str:
    script = brief.get("script") or ""
    return (
        f"{brief.get('logline') or topic}\n\n"
        f"{script}\n\n"
        "Like & follow untuk konten lifestyle berikutnya."
    )


def _fallback_hashtags(topic: str) -> list[str]:
    base = [
        "fyp",
        "foryou",
        "viral",
        "shorts",
        "reels",
        "lifestyle",
        "cinematic",
        "dailylife",
        "indonesia",
        "kontenkreator",
    ]
    if re.search(r"kopi|coffee|cafe", topic, re.I):
        base = ["coffee", "kopi", "cafevibes", "coffeetime", "morningroutine"] + base
    return base[:18]


def _yt_block(pack: dict[str, Any]) -> str:
    titles = pack.get("titles") or []
    tags = ", ".join(pack.get("hashtags") or [])
    return (
        f"TITLE OPTIONS:\n"
        + "\n".join(f"- {t}" for t in titles)
        + f"\n\nDESCRIPTION:\n{pack.get('description')}\n\n"
        f"TAGS:\n{tags}\n\n"
        "HOOKS:\n"
        + "\n".join(f"- {h}" for h in pack.get("algorithm_hooks") or [])
    )


def _upload_guide(pack: dict[str, Any], video_path: Path | None) -> str:
    return (
        "# Siap Upload\n\n"
        f"- Video: `{video_path or 'final.mp4'}`\n"
        f"- Thumbnail: `{pack.get('thumbnail_path')}`\n"
        "- Salin `youtube.txt` / `tiktok.txt` / `instagram.txt`\n"
        "- Pakai judul opsi #1 dulu; A/B test opsi lain minggu berikutnya\n"
        "- Centang Shorts / Reels sesuai platform\n"
        "- Jangan auto-translate caption jika dialog sudah bahasa target\n"
    )
