"""Audio mastering: loudness normalize + optional ducking helpers via ffmpeg."""

from __future__ import annotations

import logging
from pathlib import Path

from agent_otonom.engines.ffmpeg_engine import FFmpegEngine

logger = logging.getLogger(__name__)


class AudioMaster:
    def __init__(self, ffmpeg: FFmpegEngine) -> None:
        self.ffmpeg = ffmpeg

    async def loudnorm(
        self,
        src: Path,
        out: Path,
        *,
        integrated_lufs: float = -14.0,
        true_peak: float = -1.5,
    ) -> Path:
        """Normalize to platform short-form loudness (~-14 LUFS)."""
        out.parent.mkdir(parents=True, exist_ok=True)
        af = (
            f"loudnorm=I={integrated_lufs}:TP={true_peak}:LRA=11:"
            f"print_format=summary"
        )
        try:
            await self.ffmpeg.run(
                ["-i", str(src), "-af", af, "-c:a", "pcm_s16le", str(out)]
            )
            return out
        except Exception as exc:
            logger.warning("loudnorm failed (%s); copy through", exc)
            await self.ffmpeg.run(["-i", str(src), "-c:a", "pcm_s16le", str(out)])
            return out

    async def master_mix(
        self,
        voice: Path,
        bg: Path,
        out: Path,
        *,
        target_seconds: float | None = None,
        bg_volume: float = 0.18,
    ) -> Path:
        mixed = out.parent / "pre_master.wav"
        await self.ffmpeg.mix_voice_and_bg(
            voice, bg, mixed, bg_volume=bg_volume, target_seconds=target_seconds
        )
        return await self.loudnorm(mixed, out)
