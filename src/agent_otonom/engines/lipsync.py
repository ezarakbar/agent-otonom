"""Lipsync adapter — hooks external MuseTalk/Wav2Lip when available."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

import httpx

from agent_otonom.engines.ffmpeg_engine import FFmpegEngine

logger = logging.getLogger(__name__)


class LipsyncEngine:
    """
    Professional path: call local MuseTalk/Wav2Lip HTTP if configured.
    Otherwise return source video unchanged (QC notes the skip).
    """

    def __init__(
        self,
        base_url: str = "",
        ffmpeg: FFmpegEngine | None = None,
    ) -> None:
        self.base_url = (base_url or "").rstrip("/")
        self.ffmpeg = ffmpeg

    async def available(self) -> bool:
        if not self.base_url:
            return False
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                r = await client.get(f"{self.base_url}/health")
                return r.status_code < 500
        except Exception:
            return False

    async def apply(
        self,
        video: Path,
        audio: Path,
        out: Path,
    ) -> tuple[Path, str]:
        out.parent.mkdir(parents=True, exist_ok=True)
        if await self.available():
            try:
                async with httpx.AsyncClient(timeout=600.0) as client:
                    with video.open("rb") as vf, audio.open("rb") as af:
                        r = await client.post(
                            f"{self.base_url}/lipsync",
                            files={
                                "video": (video.name, vf, "video/mp4"),
                                "audio": (audio.name, af, "audio/wav"),
                            },
                        )
                    r.raise_for_status()
                    out.write_bytes(r.content)
                    return out, "lipsync_api"
            except Exception as exc:
                logger.warning("Lipsync API failed (%s)", exc)

        # Passthrough — still mux exact audio timing
        if self.ffmpeg:
            try:
                await self.ffmpeg.mux_av(video, audio, out, shortest=True)
                return out, "passthrough_mux"
            except Exception:
                pass
        shutil.copy2(video, out)
        return out, "passthrough"
