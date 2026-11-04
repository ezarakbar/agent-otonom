"""Pre-production brief — script / scenes / theme / options before render."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from agent_otonom.engines.llm import OllamaEngine
from agent_otonom.production.hardware import RenderProfile, build_render_profile
from agent_otonom.production.research import gather_references

logger = logging.getLogger(__name__)


async def build_production_brief(
    prompt: str,
    *,
    llm: OllamaEngine,
    capability: Any,
    enable_web: bool = True,
    input_image: str | None = None,
    input_video: str | None = None,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    meta = meta or {}
    target_sec = _duration(prompt, meta)
    profile = build_render_profile(capability, target_sec=target_sec)

    refs: dict[str, Any] = {"references": []}
    if enable_web:
        try:
            refs = await gather_references(prompt, limit=5)
        except Exception as exc:
            logger.warning("research skipped: %s", exc)

    kind = "image_to_video" if input_image else ("video_clipper" if input_video else "cinematic_short")
    draft = await _llm_brief(
        llm,
        prompt,
        kind=kind,
        target_sec=target_sec,
        refs=refs.get("references") or [],
        max_scenes=profile.max_scenes,
    )
    options = _options_for(kind, profile)
    brief = {
        "kind": kind,
        "user_prompt": prompt,
        "target_duration_sec": target_sec,
        "theme": draft.get("theme") or _guess_theme(prompt),
        "logline": draft.get("logline") or prompt[:160],
        "script": draft.get("script") or "",
        "scenes": draft.get("scenes") or [],
        "visual_style": draft.get("visual_style")
        or "photoreal natural lighting, real human subject, documentary-cinematic",
        "audio_plan": draft.get("audio_plan")
        or {"dialogue": True, "background": "ambient", "notes": "voice + room tone"},
        "character": draft.get("character")
        or {
            "description": "real adult human, natural proportions, realistic skin",
            "action": "matches user request exactly",
        },
        "references": refs.get("references") or [],
        "render_profile": profile.to_dict(),
        "options": options,
        "recommended_option": options[0]["id"] if options else "standard",
        "input_image": input_image,
        "input_video": input_video,
        "publish_hints": draft.get("publish_hints")
        or {
            "platforms": ["youtube_shorts", "tiktok", "instagram_reels"],
            "tone": "authentic lifestyle",
        },
    }
    if not brief["script"] and brief["scenes"]:
        brief["script"] = " ".join(
            str(s.get("voiceover") or "") for s in brief["scenes"] if isinstance(s, dict)
        ).strip()
    if not brief["scenes"]:
        brief["scenes"] = _fallback_scenes(prompt, profile.max_scenes, target_sec)
        brief["script"] = brief["scenes"][0]["voiceover"]
    return brief


def format_brief_message(brief: dict[str, Any]) -> str:
    """Human-readable brief for chat confirmation."""
    lines: list[str] = []
    lines.append("## Brief Produksi (konfirmasi dulu sebelum render)")
    lines.append(f"**Tema:** {brief.get('theme')}")
    lines.append(f"**Logline:** {brief.get('logline')}")
    if brief.get("target_duration_sec"):
        lines.append(f"**Durasi target:** {brief['target_duration_sec']} detik")
    rp = brief.get("render_profile") or {}
    lines.append(
        f"**Profil hardware:** {rp.get('name')} — {rp.get('notes')} "
        f"(max {rp.get('max_scenes')} scene, timeout Comfy {rp.get('comfy_timeout_sec')}s)"
    )
    char = brief.get("character") or {}
    if char:
        lines.append(f"**Karakter:** {char.get('description')} | aksi: {char.get('action')}")
    lines.append("")
    lines.append("### Naskah / dialog")
    lines.append(brief.get("script") or "(kosong)")
    lines.append("")
    lines.append("### Scene")
    for i, sc in enumerate(brief.get("scenes") or [], 1):
        if not isinstance(sc, dict):
            continue
        lines.append(
            f"{i}. **{sc.get('title') or 'Scene'}** — {sc.get('voiceover') or ''}\n"
            f"   Visual: {sc.get('visual_prompt') or ''}"
        )
    refs = brief.get("references") or []
    if refs:
        lines.append("")
        lines.append("### Referensi web")
        for r in refs[:5]:
            lines.append(f"- [{r.get('title')}]({r.get('url')}) — {r.get('snippet','')[:120]}")
    lines.append("")
    lines.append("### Pilihan eksekusi")
    for opt in brief.get("options") or []:
        mark = "← rekomendasi" if opt.get("id") == brief.get("recommended_option") else ""
        lines.append(f"- `{opt.get('id')}`: {opt.get('label')} — {opt.get('description')} {mark}")
    lines.append("")
    lines.append("Pilih opsi lalu konfirmasi untuk mulai render + pack upload.")
    return "\n".join(lines)


async def _llm_brief(
    llm: OllamaEngine,
    prompt: str,
    *,
    kind: str,
    target_sec: float | None,
    refs: list[dict[str, str]],
    max_scenes: int,
) -> dict[str, Any]:
    if not await llm.available():
        return {}
    ref_txt = "\n".join(
        f"- {r.get('title')}: {r.get('snippet')}" for r in refs[:4]
    ) or "(no web refs)"
    dur = f"{target_sec}s" if target_sec else "unspecified"
    system = (
        "You are a professional short-form film director & producer. Reply JSON only. "
        "For human subjects: always specify real adult human, photoreal, natural skin, "
        "clear action (e.g. drinking coffee from a mug). Never omit the person if asked. "
        "visual_prompt must be English and detailed (lens, light, wardrobe, action)."
    )
    user = (
        f"Kind: {kind}\nDuration: {dur}\nMax scenes: {max_scenes}\n"
        f"User request: {prompt}\n\nWeb refs:\n{ref_txt}\n\n"
        "JSON schema:\n"
        "{"
        '"theme":"...",'
        '"logline":"...",'
        '"script":"spoken dialogue/voiceover in user language",'
        '"visual_style":"...",'
        '"character":{"description":"...","action":"..."},'
        '"audio_plan":{"dialogue":true,"background":"cafe|room|none","notes":"..."},'
        '"scenes":[{"title":"...","voiceover":"...","visual_prompt":"..."}],'
        '"publish_hints":{"platforms":["youtube_shorts","tiktok"],"tone":"..."}'
        "}"
    )
    try:
        data = await llm.generate_json(user, system=system, temperature=0.45)
        if isinstance(data, dict):
            scenes = data.get("scenes")
            if isinstance(scenes, list):
                data["scenes"] = scenes[:max_scenes]
            return data
    except Exception as exc:
        logger.warning("brief LLM failed: %s", exc)
    return {}


def _options_for(kind: str, profile: RenderProfile) -> list[dict[str, str]]:
    if kind == "image_to_video":
        return [
            {
                "id": "kenburns_talk",
                "label": "Ken Burns + dialog + BGM",
                "description": "Gambar dianimasikan zoom/pan, suara SoVITS, ambience. Paling stabil.",
            },
            {
                "id": "comfy_img2img",
                "label": "ComfyUI img2img refine + motion",
                "description": "Refine gambar lewat Comfy lalu Ken Burns. Lebih sinematik, lebih lama.",
            },
            {
                "id": "still_pack_only",
                "label": "Publish pack saja",
                "description": "Tanpa render ulang panjang: buat judul/hashtag/thumbnail dari gambar.",
            },
        ]
    if kind == "video_clipper":
        return [
            {
                "id": "highlights",
                "label": "Highlight reel",
                "description": "Potong bagian menarik + pack upload.",
            },
            {
                "id": "highlights_captions",
                "label": "Highlight + metadata kuat",
                "description": "Sama + judul/hashtag agresif untuk algoritma.",
            },
        ]
    return [
        {
            "id": "standard",
            "label": f"Render standar ({profile.name})",
            "description": "Storyboard → SoVITS → ComfyUI → FFmpeg → pack upload.",
        },
        {
            "id": "quality_patient",
            "label": "Kualitas sabar",
            "description": "Timeout panjang, karakter manusia lebih detail. Cocok CPU/AMD.",
        },
        {
            "id": "fast_preview",
            "label": "Preview cepat",
            "description": "1 scene, resolusi kecil, untuk cek konsep dulu.",
        },
    ]


def _fallback_scenes(prompt: str, max_scenes: int, target_sec: float | None) -> list[dict[str, str]]:
    human = bool(re.search(r"orang|manusia|person|people|woman|man|kopi|coffee", prompt, re.I))
    if human or (target_sec and target_sec <= 8):
        script = "Kopi ini hangat. Aku butuh jeda sejenak hari ini."
        if "kopi" not in prompt.lower() and "coffee" not in prompt.lower():
            script = "Ini momen kecil yang terasa nyata."
        visual = (
            "photoreal portrait of a real adult human drinking coffee from a ceramic mug in a cozy cafe, "
            "natural morning window light, steam rising, candid lifestyle photography, 35mm, "
            "realistic skin texture, shallow depth of field, no cartoon, no anime"
        )
        if not re.search(r"kopi|coffee", prompt, re.I):
            visual = (
                f"photoreal documentary still of a real adult human performing: {prompt}. "
                "natural lighting, realistic skin, candid, 35mm film, no cartoon, no anime"
            )
        return [
            {
                "title": "Hero character",
                "voiceover": script,
                "visual_prompt": visual,
            }
        ]
    scenes = []
    for i in range(max(1, min(max_scenes, 3))):
        scenes.append(
            {
                "title": f"Scene {i+1}",
                "voiceover": prompt[:120],
                "visual_prompt": (
                    f"photoreal cinematic still for: {prompt}, detailed environment, "
                    "natural light, 35mm film"
                ),
            }
        )
    return scenes


def _duration(prompt: str, meta: dict[str, Any]) -> float | None:
    if meta.get("duration_sec"):
        try:
            return float(meta["duration_sec"])
        except (TypeError, ValueError):
            pass
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:detik|seconds?|secs?)\b", prompt, re.I)
    if m:
        return float(m.group(1).replace(",", "."))
    return None


def _guess_theme(prompt: str) -> str:
    if re.search(r"kopi|coffee|cafe|kafe", prompt, re.I):
        return "Lifestyle cafe — human drinking coffee"
    return "Short cinematic lifestyle"
