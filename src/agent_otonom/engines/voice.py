"""Voice engine — GPT-SoVITS is the primary TTS; Piper/espeak only if fallback is allowed."""

from __future__ import annotations

import asyncio
import logging
import re
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
        *,
        ref_audio: str = "",
        prompt_text: str = "",
        prompt_lang: str = "auto",
        allow_fallback: bool = False,
        voices_dir: Path | None = None,
    ) -> None:
        self.sovits_url = sovits_url.rstrip("/")
        self.piper_bin = piper_bin
        self.piper_model = piper_model
        self.ref_audio = ref_audio.strip()
        self.prompt_text = prompt_text
        self.prompt_lang = prompt_lang or "auto"
        self.allow_fallback = allow_fallback
        self.voices_dir = voices_dir
        self._backend: str | None = None

    async def available(self) -> bool:
        return await self._sovits_ok()

    async def resolve_backend(self) -> str:
        if self._backend:
            return self._backend
        if await self._sovits_ok():
            self._backend = "gpt_sovits"
        elif self.allow_fallback and self._piper_ready():
            self._backend = "piper"
        elif self.allow_fallback and (shutil.which("espeak-ng") or shutil.which("espeak")):
            self._backend = "espeak"
        elif self.allow_fallback:
            self._backend = "silence"
        else:
            self._backend = "unavailable"
        return self._backend

    async def _sovits_ok(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                for path in ("/docs", "/tts", "/", "/control"):
                    try:
                        r = await client.get(f"{self.sovits_url}{path}")
                        if r.status_code < 500:
                            return True
                    except Exception:
                        continue
        except Exception:
            return False
        return False

    def _piper_ready(self) -> bool:
        bin_ok = bool(self.piper_bin and Path(self.piper_bin).exists()) or bool(
            shutil.which("piper")
        )
        model_ok = bool(self.piper_model and Path(self.piper_model).exists())
        return bin_ok and model_ok

    def _ref_path(self) -> str:
        if self.ref_audio and Path(self.ref_audio).is_file():
            return self.ref_audio
        if self.voices_dir and self.voices_dir.is_dir():
            for ext in ("*.wav", "*.mp3", "*.ogg"):
                found = sorted(self.voices_dir.glob(ext))
                if found:
                    return str(found[0])
        return ""

    async def synthesize(self, text: str, out_wav: Path) -> str:
        """Synthesize speech to WAV. Returns backend name used."""
        out_wav.parent.mkdir(parents=True, exist_ok=True)
        backend = await self.resolve_backend()
        clean = " ".join(text.split())
        if not clean:
            clean = "..."

        if backend == "unavailable":
            raise RuntimeError(
                "GPT-SoVITS adalah engine utama untuk audio. "
                f"Jalankan API di {self.sovits_url} (biasanya python api_v2.py -p 9880)."
            )

        if backend == "gpt_sovits":
            try:
                await self._sovits(clean, out_wav)
                return backend
            except Exception as exc:
                if not self.allow_fallback:
                    raise RuntimeError(f"GPT-SoVITS gagal: {exc}") from exc
                logger.warning("SoVITS failed (%s), falling back", exc)
                backend = (
                    "piper"
                    if self._piper_ready()
                    else ("espeak" if (shutil.which("espeak-ng") or shutil.which("espeak")) else "silence")
                )

        if backend == "piper":
            try:
                await self._piper(clean, out_wav)
                return "piper"
            except Exception as exc:
                logger.warning("Piper failed (%s), falling back", exc)
                backend = (
                    "espeak" if (shutil.which("espeak-ng") or shutil.which("espeak")) else "silence"
                )

        if backend == "espeak":
            await self._espeak(clean, out_wav)
            return "espeak"

        await self._silence(out_wav, seconds=max(2.0, len(clean.split()) * 0.35))
        return "silence"

    async def _sovits(self, text: str, out_wav: Path) -> None:
        lang = _detect_lang(text)
        ref = self._ref_path()
        prompt_lang = self.prompt_lang if self.prompt_lang != "auto" else lang
        payloads: list[tuple[str, str, dict]] = []

        v2 = {
            "text": text,
            "text_lang": lang,
            "prompt_lang": prompt_lang,
            "prompt_text": self.prompt_text,
            "text_split_method": "cut5",
            "media_type": "wav",
            "streaming_mode": False,
            "batch_size": 1,
        }
        if ref:
            v2["ref_audio_path"] = ref

        v1 = {
            "text": text,
            "text_language": lang,
            "prompt_language": prompt_lang,
            "prompt_text": self.prompt_text,
        }
        if ref:
            v1["refer_wav_path"] = ref
            v1["ref_audio_path"] = ref

        payloads.append(("POST", "/tts", v2))
        payloads.append(("POST", "/", v1))
        payloads.append(("POST", "/tts", v1))

        async with httpx.AsyncClient(timeout=180.0) as client:
            last_err = "no response"
            for method, path, body in payloads:
                url = f"{self.sovits_url}{path}"
                try:
                    if method == "POST":
                        r = await client.post(url, json=body)
                    else:
                        r = await client.get(url, params=body)
                    if r.status_code >= 400:
                        last_err = f"{path} {r.status_code}: {r.text[:400]}"
                        continue
                    if _write_audio(out_wav, r.content, r.headers.get("content-type", "")):
                        return
                    last_err = f"{path} returned non-audio ({r.headers.get('content-type')})"
                except Exception as exc:
                    last_err = f"{path}: {exc}"
                    continue

            # GET query-style (api_v2 and legacy api.py)
            params_list = [
                {
                    "text": text,
                    "text_lang": lang,
                    "prompt_lang": prompt_lang,
                    "prompt_text": self.prompt_text,
                    "media_type": "wav",
                    "streaming_mode": "false",
                    **({"ref_audio_path": ref} if ref else {}),
                },
                {
                    "text": text,
                    "text_language": lang,
                    "prompt_language": prompt_lang,
                    "prompt_text": self.prompt_text,
                    **({"refer_wav_path": ref} if ref else {}),
                },
            ]
            for path in ("/tts", "/"):
                for params in params_list:
                    try:
                        r = await client.get(f"{self.sovits_url}{path}", params=params)
                        if r.status_code < 400 and _write_audio(
                            out_wav, r.content, r.headers.get("content-type", "")
                        ):
                            return
                        last_err = f"GET {path} {r.status_code}: {r.text[:300]}"
                    except Exception as exc:
                        last_err = str(exc)
            hint = ""
            if not ref:
                hint = (
                    " Set SOVITS_REF_AUDIO ke file wav referensi speaker "
                    "(wajib untuk api_v2) di models/sovits/."
                )
            raise RuntimeError(f"GPT-SoVITS tidak menghasilkan audio. {last_err}.{hint}")

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
        _stdout, stderr = await proc.communicate()
        if proc.returncode != 0 or not out_wav.exists():
            raise RuntimeError(stderr.decode() or "piper failed")

    async def _espeak(self, text: str, out_wav: Path) -> None:
        bin_name = shutil.which("espeak-ng") or shutil.which("espeak")
        if not bin_name:
            raise RuntimeError("espeak not found")
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


def _detect_lang(text: str) -> str:
    if re.search(r"[\u4e00-\u9fff]", text):
        return "zh"
    if re.search(r"[\u3040-\u30ff]", text):
        return "ja"
    if re.search(r"[\uac00-\ud7af]", text):
        return "ko"
    # GPT-SoVITS has no dedicated Indonesian; latin scripts use en/auto.
    return "auto"


def _write_audio(path: Path, content: bytes, content_type: str) -> bool:
    if not content or len(content) < 64:
        return False
    head = content[:16]
    if head.startswith(b"{") or head.startswith(b"["):
        return False
    ctype = content_type.lower()
    if "json" in ctype or "html" in ctype:
        return False
    if head.startswith(b"RIFF") or "wav" in ctype:
        path.write_bytes(content)
        return True
    if head.startswith(b"OggS") or "ogg" in ctype:
        path.write_bytes(content)
        return True
    if "audio" in ctype or "octet-stream" in ctype:
        path.write_bytes(content)
        return True
    if head.startswith(b"ID3") or head[0:2] == b"\xff\xfb":
        path.write_bytes(content)
        return True
    return False
