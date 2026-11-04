"""Engine registry — wires adapters from settings + capability report."""

from __future__ import annotations

from dataclasses import dataclass

from agent_otonom.capability import CapabilityReport
from agent_otonom.config import Settings
from agent_otonom.engines.audio_master import AudioMaster
from agent_otonom.engines.ffmpeg_engine import FFmpegEngine
from agent_otonom.engines.lipsync import LipsyncEngine
from agent_otonom.engines.llm import OllamaEngine
from agent_otonom.engines.vision import VisionEngine
from agent_otonom.engines.voice import VoiceEngine


@dataclass
class EngineHub:
    llm: OllamaEngine
    voice: VoiceEngine
    vision: VisionEngine
    ffmpeg: FFmpegEngine
    audio: AudioMaster
    lipsync: LipsyncEngine
    capability: CapabilityReport


def build_engines(settings: Settings, capability: CapabilityReport) -> EngineHub:
    piper_bin = settings.piper_bin or (capability.engines.get("piper", {}) or {}).get("bin", "")
    piper_model = settings.piper_model or (capability.engines.get("piper", {}) or {}).get(
        "model", ""
    )
    ffmpeg = FFmpegEngine(encoder=capability.video_encoder)
    llm = OllamaEngine(settings.ollama_base_url, settings.ollama_model)
    voice = VoiceEngine(
        settings.sovits_base_url,
        piper_bin=piper_bin or "",
        piper_model=piper_model or "",
        ref_audio=settings.sovits_ref_audio,
        prompt_text=settings.sovits_prompt_text,
        prompt_lang=settings.sovits_prompt_lang,
        allow_fallback=settings.allow_engine_fallback,
        voices_dir=settings.agent_root / "models" / "sovits",
    )
    vision = VisionEngine(
        settings.comfyui_base_url,
        ffmpeg,
        checkpoint=settings.comfy_checkpoint,
        allow_fallback=settings.allow_engine_fallback,
    )
    audio = AudioMaster(ffmpeg)
    lipsync = LipsyncEngine(
        getattr(settings, "lipsync_base_url", "") or "",
        ffmpeg=ffmpeg,
    )
    return EngineHub(
        llm=llm,
        voice=voice,
        vision=vision,
        ffmpeg=ffmpeg,
        audio=audio,
        lipsync=lipsync,
        capability=capability,
    )
