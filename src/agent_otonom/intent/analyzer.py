"""Intent analyzer & router — maps natural language to workflows."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from agent_otonom.engines.llm import OllamaEngine

logger = logging.getLogger(__name__)

KNOWN = {
    "cinematic_short": {
        "title": "Cinematic Short",
        "hints": [
            "film",
            "sinematik",
            "cinematic",
            "short",
            "shorts",
            "reels",
            "tiktok",
            "video pendek",
            "buatkan video",
            "buat video",
            "bikin video",
            "generate video",
            "buat film",
            "bikin film",
            "naskah",
            "story",
            "cerita",
            "scene",
            "adegan",
            "minum kopi",
            "orang sedang",
            "dari teks",
            "dari ide",
            "produksi",
            "studio",
        ],
    },
    "image_to_video": {
        "title": "Image to Video",
        "hints": [
            "jadi video",
            "jadikan video",
            "image to video",
            "img2vid",
            "gambar jadi video",
            "foto jadi video",
            "animasikan gambar",
            "gerakkan gambar",
            "dari gambar",
            "from image",
        ],
    },
    "video_clipper": {
        "title": "Video Clipper",
        "hints": [
            "video clipper",
            "potong video",
            "trim video",
            "cut video",
            "highlight video",
            "bagian menarik dari video",
            "edit video yang sudah",
            "caper",
            "clip dari video",
        ],
    },
}


@dataclass
class IntentResult:
    workflow: str
    confidence: float
    title: str
    params: dict[str, Any] = field(default_factory=dict)
    needs_generation: bool = False
    raw: str = ""


class IntentAnalyzer:
    def __init__(self, llm: OllamaEngine | None = None) -> None:
        self.llm = llm

    def heuristic(self, prompt: str, meta: dict[str, Any] | None = None) -> IntentResult | None:
        meta = meta or {}
        text = prompt.lower()
        has_image = bool(meta.get("input_image"))
        has_video = bool(meta.get("input_video") or meta.get("upload_path"))
        if not has_video:
            has_video = bool(
                re.search(r"/(?:[\w.-]+/)+[\w.-]+\.(?:mp4|mov|mkv|webm)\b", prompt, re.I)
            )
        if not has_image:
            has_image = bool(
                re.search(r"/(?:[\w.-]+/)+[\w.-]+\.(?:png|jpg|jpeg|webp)\b", prompt, re.I)
            )

        # Uploaded / path assets dominate routing
        if has_image and not has_video:
            return IntentResult(
                workflow="image_to_video",
                confidence=0.93,
                title=KNOWN["image_to_video"]["title"],
                params=_extract_params(prompt, "image_to_video", meta),
                raw=prompt,
            )
        if has_video and (
            _score(text, "video_clipper") > 0
            or re.search(r"\b(potong|trim|cut|highlight|clipper|caper)\b", text)
        ):
            return IntentResult(
                workflow="video_clipper",
                confidence=0.9,
                title=KNOWN["video_clipper"]["title"],
                params=_extract_params(prompt, "video_clipper", meta),
                raw=prompt,
            )
        if has_video and not has_image:
            # Video uploaded without clear trim intent → still clipper (has source)
            return IntentResult(
                workflow="video_clipper",
                confidence=0.75,
                title=KNOWN["video_clipper"]["title"],
                params=_extract_params(prompt, "video_clipper", meta),
                raw=prompt,
            )

        # TEXT ONLY → generative studio (never video_clipper without a video)
        scores = {
            "cinematic_short": _score(text, "cinematic_short"),
            "image_to_video": _score(text, "image_to_video"),
            "video_clipper": _score(text, "video_clipper"),
        }
        # Ignore clipper for text-only prompts (no source media)
        scores["video_clipper"] = 0.0
        # image_to_video without image is wrong — fold into cinematic
        if scores["image_to_video"] > 0 and not has_image:
            scores["cinematic_short"] += scores["image_to_video"]
            scores["image_to_video"] = 0.0

        best = max(scores, key=scores.get)
        if scores[best] > 0:
            return IntentResult(
                workflow=best,
                confidence=min(0.95, 0.6 + 0.1 * scores[best]),
                title=KNOWN[best]["title"],
                params=_extract_params(prompt, best, meta),
                raw=prompt,
            )

        # Any plain creative / production text → cinematic short
        if _looks_like_production(text):
            return IntentResult(
                workflow="cinematic_short",
                confidence=0.72,
                title=KNOWN["cinematic_short"]["title"],
                params=_extract_params(prompt, "cinematic_short", meta),
                raw=prompt,
            )
        return None

    async def analyze(self, prompt: str, meta: dict[str, Any] | None = None) -> IntentResult:
        meta = meta or {}
        hit = self.heuristic(prompt, meta)
        if hit and hit.confidence >= 0.65:
            return _guard_assets(hit, meta)

        if self.llm and await self.llm.available():
            try:
                data = await self.llm.generate_json(
                    prompt=(
                        "Klasifikasikan intent pengguna ke salah satu workflow.\n"
                        "ATURAN KERAS:\n"
                        "- Jika TIDAK ada input_video dan TIDAK ada input_image, "
                        "pilih cinematic_short (buat video dari teks/ide).\n"
                        "- video_clipper HANYA jika ada video sumber untuk dipotong.\n"
                        "- image_to_video HANYA jika ada gambar/foto sumber.\n"
                        "- other: tugas non-video.\n\n"
                        f"Ada input_image: {bool(meta.get('input_image'))}\n"
                        f"Ada input_video: {bool(meta.get('input_video') or meta.get('upload_path'))}\n"
                        f"Prompt: {prompt}\n\n"
                        'Balas JSON: {"workflow":"...","confidence":0-1,"reason":"..."}'
                    ),
                    system="You are an intent router for a generative video studio. Reply JSON only.",
                    temperature=0.1,
                )
                wf = str(data.get("workflow", "other")).strip()
                conf = float(data.get("confidence", 0.5))
                if wf not in KNOWN:
                    # Non-video → still prefer cinematic for creative text
                    if _looks_like_production(prompt.lower()):
                        wf = "cinematic_short"
                        conf = max(conf, 0.7)
                    else:
                        return IntentResult(
                            workflow="dynamic",
                            confidence=conf,
                            title="Dynamic Workflow",
                            params={"idea": prompt, "reason": data.get("reason", "")},
                            needs_generation=True,
                            raw=prompt,
                        )
                result = IntentResult(
                    workflow=wf,
                    confidence=conf,
                    title=KNOWN[wf]["title"],
                    params=_extract_params(prompt, wf, meta),
                    raw=prompt,
                )
                return _guard_assets(result, meta)
            except Exception as exc:
                logger.warning("LLM intent failed: %s", exc)

        if hit:
            return _guard_assets(hit, meta)

        # Default studio behavior: one text command → full generative video pipeline
        return IntentResult(
            workflow="cinematic_short",
            confidence=0.55,
            title=KNOWN["cinematic_short"]["title"],
            params=_extract_params(prompt, "cinematic_short", meta),
            raw=prompt,
        )


def _score(text: str, workflow: str) -> float:
    score = 0.0
    for h in KNOWN[workflow]["hints"]:
        if h in text:
            score += 1.0
    return score


def _looks_like_production(text: str) -> bool:
    return bool(
        re.search(
            r"\b(buat|bikin|make|create|generate|produksi|film|video|short|reel|"
            r"cerita|naskah|scene|adegan|orang|manusia|kopi|cafe|kafe)\b",
            text,
            re.I,
        )
    )


def _guard_assets(intent: IntentResult, meta: dict[str, Any]) -> IntentResult:
    """Never run clipper/img2vid without the required media — fall back to text→video."""
    has_image = bool(meta.get("input_image") or intent.params.get("input_image"))
    has_video = bool(
        meta.get("input_video")
        or meta.get("upload_path")
        or intent.params.get("input_video")
    )
    if intent.workflow == "video_clipper" and not has_video:
        intent.workflow = "cinematic_short"
        intent.title = KNOWN["cinematic_short"]["title"]
        intent.params = _extract_params(intent.raw or intent.params.get("prompt", ""), "cinematic_short", meta)
        intent.confidence = max(intent.confidence, 0.8)
    if intent.workflow == "image_to_video" and not has_image:
        intent.workflow = "cinematic_short"
        intent.title = KNOWN["cinematic_short"]["title"]
        intent.params = _extract_params(intent.raw or intent.params.get("prompt", ""), "cinematic_short", meta)
        intent.confidence = max(intent.confidence, 0.8)
    return intent


def _extract_params(prompt: str, workflow: str, meta: dict[str, Any] | None = None) -> dict[str, Any]:
    meta = meta or {}
    params: dict[str, Any] = {"prompt": prompt}
    m = re.search(r"(/(?:[\w.-]+/)+[\w.-]+\.(?:mp4|mov|mkv|webm))", prompt, re.I)
    if m:
        params["input_video"] = m.group(1)
    m = re.search(r"(/(?:[\w.-]+/)+[\w.-]+\.(?:png|jpg|jpeg|webp))", prompt, re.I)
    if m:
        params["input_image"] = m.group(1)
    if meta.get("input_video"):
        params["input_video"] = meta["input_video"]
    if meta.get("upload_path") and str(meta["upload_path"]).lower().endswith(
        (".mp4", ".mov", ".mkv", ".webm")
    ):
        params.setdefault("input_video", meta["upload_path"])
    if meta.get("input_image"):
        params["input_image"] = meta["input_image"]
    if workflow in {"cinematic_short", "image_to_video"}:
        params["topic"] = prompt
    return params
