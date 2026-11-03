"""Voice engine: GPT-SoVITS → Piper → espeak-ng."""

from __future__ import annotations

import asyncio
import logging
import shutil
import wave
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)


class VoiceEngine:
    def __init__(
        self,
        sovits_url: str,
        piper_bin: str = "",
        piper_model: str = "",
    ) -> None:
        self.sovits_url = sovits_url.rstrip("/")
        self.piper_bin = piper_bin
        self.piper_model = piper_model
        self._backend: str | None = None

    async def resolve_backend(self) -> str:
        if self._backend:
            return self._backend
        if await self._sovits_ok():
            self._backend = "gpt_sovits"
        elif self._piper_ready():
            self._backend = "piper"
        elif shutil.which("espeak-ng") or shutil.which("espeak"):
            self._backend = "espeak"
        else:
            self._backend = "silence"
        return self._backend

    async def _sovits_ok(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                r = await client.get(self.sovits_url)
                return r.status_code < 500
        except Exception:
            return False

    def _piper_ready(self) -> bool:
        bin_ok = bool(self.piper_bin and Path(self.piper_bin).exists()) or bool(
            shutil.which("piper")
        )
        model_ok = bool(self.piper_model and Path(self.piper_model).exists())
        return bin_ok and model_ok

    async def synthesize(self, text: str, out_wav: Path) -> str:
        """Synthesize speech to WAV. Returns backend name used."""
        out_wav.parent.mkdir(parents=True, exist_ok=True)
        backend = await self.resolve_backend()
        clean = " ".join(text.split())
        if not clean:
            clean = "..."

        if backend == "gpt_sovits":
            try:
                await self._sovits(clean, out_wav)
                return backend
            except Exception as exc:
                logger.warning("SoVITS failed (%s), falling back", exc)
                backend = "piper" if self._piper_ready() else (
                    "espeak" if (shutil.which("espeak-ng") or shutil.which("espeak")) else "silence"
                )

        if backend == "piper":
            try:
                await self._piper(clean, out_wav)
                return "piper"
            except Exception as exc:
                logger.warning("Piper failed (%s), falling back", exc)
                backend = "espeak" if (shutil.which("espeak-ng") or shutil.which("espeak")) else "silence"

        if backend == "espeak":
            await self._espeak(clean, out_wav)
            return "espeak"

        await self._silence(out_wav, seconds=max(2.0, len(clean.split()) * 0.35))
        return "silence"

    async def _sovits(self, text: str, out_wav: Path) -> None:
        # Common GPT-SoVITS API shapes vary; try /tts then query style.
        async with httpx.AsyncClient(timeout=120.0) as client:
            for path in ("/tts", "/"):
                try:
                    r = await client.post(
                        f"{self.sovits_url}{path}",
                        json={"text": text, "text_language": "id"},
                    )
                    if r.status_code == 200 and r.content:
                        out_wav.write_bytes(r.content)
                        return
                except Exception:
                    continue
            r = await client.get(
                self.sovits_url,
                params={"text": text, "text_language": "id"},
            )
            r.raise_for_status()
            out_wav.write_bytes(r.content)

    async def _piper(self, text: str, out_wav: Path) -> None:
        piper = self.piper_bin or shutil.which("piper")
        if not piper or not self.piper_model:
            raise RuntimeError("Piper not configured")
        proc = await asyncio.create_subprocess_exec(
            piper,
            "--model",
            self.piper_model,
            "--output_file",
            str(out_wav),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        assert proc.stdin is not None
        proc.stdin.write(text.encode("utf-8"))
        await proc.stdin.drain()
        proc.stdin.close()
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0 or not out_wav.exists():
            raise RuntimeError(stderr.decode() or "piper failed")

    async def _espeak(self, text: str, out_wav: Path) -> None:
        bin_name = shutil.which("espeak-ng") or shutil.which("espeak")
        if not bin_name:
            raise RuntimeError("espeak not found")
        # Prefer WAV direct if supported
        proc = await asyncio.create_subprocess_exec(
            bin_name,
            "-v",
            "id",
            "-w",
            str(out_wav),
            text,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0 or not out_wav.exists():
            # retry default voice
            proc = await asyncio.create_subprocess_exec(
                bin_name,
                "-w",
                str(out_wav),
                text,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            if proc.returncode != 0 or not out_wav.exists():
                raise RuntimeError(stderr.decode() or "espeak failed")

    async def _silence(self, out_wav: Path, seconds: float = 3.0) -> None:
        frames = int(22050 * seconds)
        with wave.open(str(out_wav), "w") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(22050)
            wf.writeframes(b"\x00\x00" * frames)
