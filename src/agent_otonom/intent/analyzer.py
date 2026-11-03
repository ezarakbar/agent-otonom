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
            "video pendek",
            "buatkan video",
            "buat film",
            "naskah",
            "story",
            "cerita",
        ],
    },
    "video_clipper": {
        "title": "Video Clipper",
        "hints": [
            "clip",
            "clipper",
            "potong",
            "caper",
            "highlight",
            "bagian menarik",
            "edit video",
            "cut",
            "trim",
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

    def heuristic(self, prompt: str) -> IntentResult | None:
        text = prompt.lower()
        scores: dict[str, float] = {}
        for wid, meta in KNOWN.items():
            score = 0.0
            for h in meta["hints"]:
                if h in text:
                    score += 1.0
            scores[wid] = score
        best = max(scores, key=scores.get) if scores else None
        if best and scores[best] > 0:
            return IntentResult(
                workflow=best,
                confidence=min(0.95, 0.55 + 0.1 * scores[best]),
                title=KNOWN[best]["title"],
                params=_extract_params(prompt, best),
                raw=prompt,
            )
        return None

    async def analyze(self, prompt: str) -> IntentResult:
        hit = self.heuristic(prompt)
        if hit and hit.confidence >= 0.65:
            return hit

        if self.llm and await self.llm.available():
            try:
                data = await self.llm.generate_json(
                    prompt=(
                        "Klasifikasikan intent pengguna ke salah satu workflow:\n"
                        "- cinematic_short: membuat film/video pendek sinematik dari ide\n"
                        "- video_clipper: memotong/highlight video yang sudah ada\n"
                        "- other: tugas lain yang butuh workflow baru\n\n"
                        f"Prompt: {prompt}\n\n"
                        'Balas JSON: {"workflow":"...","confidence":0-1,"reason":"..."}'
                    ),
                    system="You are an intent router. Reply JSON only.",
                    temperature=0.1,
                )
                wf = str(data.get("workflow", "other")).strip()
                conf = float(data.get("confidence", 0.5))
                if wf in KNOWN:
                    return IntentResult(
                        workflow=wf,
                        confidence=conf,
                        title=KNOWN[wf]["title"],
                        params=_extract_params(prompt, wf),
                        raw=prompt,
                    )
                return IntentResult(
                    workflow="dynamic",
                    confidence=conf,
                    title="Dynamic Workflow",
                    params={"idea": prompt, "reason": data.get("reason", "")},
                    needs_generation=True,
                    raw=prompt,
                )
            except Exception as exc:
                logger.warning("LLM intent failed: %s", exc)

        if hit:
            return hit

        # Default: treat creative prompts as cinematic
        if re.search(r"\b(buat|make|create|generate|tulis)\b", prompt.lower()):
            return IntentResult(
                workflow="cinematic_short",
                confidence=0.45,
                title="Cinematic Short",
                params=_extract_params(prompt, "cinematic_short"),
                raw=prompt,
            )

        return IntentResult(
            workflow="dynamic",
            confidence=0.4,
            title="Dynamic Workflow",
            params={"idea": prompt},
            needs_generation=True,
            raw=prompt,
        )


def _extract_params(prompt: str, workflow: str) -> dict[str, Any]:
    params: dict[str, Any] = {"prompt": prompt}
    # path-like mention
    m = re.search(r"(/(?:[\w.-]+/)+[\w.-]+\.(?:mp4|mov|mkv|webm))", prompt, re.I)
    if m:
        params["input_video"] = m.group(1)
    if workflow == "cinematic_short":
        params["topic"] = prompt
    return params
