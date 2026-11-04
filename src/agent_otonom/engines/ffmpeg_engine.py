"""FFmpeg adapter — auto encoder selection (AMF / NVENC / VAAPI / libx264)."""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class FFmpegEngine:
    def __init__(self, encoder: str = "libx264") -> None:
        self.encoder = encoder
        self.ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
        self.ffprobe = shutil.which("ffprobe") or "ffprobe"

    def available(self) -> bool:
        return shutil.which("ffmpeg") is not None

    def _encode_args(self) -> list[str]:
        enc = self.encoder
        if enc == "h264_amf":
            return ["-c:v", "h264_amf", "-quality", "balanced", "-rc", "cqp", "-qp_i", "22", "-qp_p", "22"]
        if enc == "h264_nvenc":
            return ["-c:v", "h264_nvenc", "-preset", "p4", "-cq", "23"]
        if enc == "h264_qsv":
            return ["-c:v", "h264_qsv", "-global_quality", "23"]
        if enc == "h264_vaapi":
            return [
                "-vaapi_device",
                "/dev/dri/renderD128",
                "-vf",
                "format=nv12,hwupload",
                "-c:v",
                "h264_vaapi",
            ]
        if enc == "h264_videotoolbox":
            return ["-c:v", "h264_videotoolbox", "-b:v", "5M"]
        return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23"]

    async def run(self, args: list[str], timeout: float = 1800) -> None:
        cmd = [self.ffmpeg, "-y", *args]
        logger.info("ffmpeg: %s", " ".join(cmd))
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            raise RuntimeError("ffmpeg timed out")
        if proc.returncode != 0:
            err = stderr.decode("utf-8", errors="replace")[-2000:]
            # AMF sometimes fails — retry once with libx264
            if self.encoder != "libx264" and "amf" in self.encoder.lower():
                logger.warning("Encoder %s failed, retrying libx264: %s", self.encoder, err[-400:])
                old = self.encoder
                self.encoder = "libx264"
                try:
                    # Replace encoder flags is hard mid-args; caller should use encode helpers.
                    raise RuntimeError(err)
                finally:
                    self.encoder = old
            raise RuntimeError(f"ffmpeg failed ({proc.returncode}): {err}")

    async def probe(self, path: Path) -> dict[str, Any]:
        proc = await asyncio.create_subprocess_exec(
            self.ffprobe,
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        if proc.returncode != 0:
            return {}
        return json.loads(stdout.decode())

    async def duration(self, path: Path) -> float:
        info = await self.probe(path)
        try:
            return float(info.get("format", {}).get("duration", 0))
        except (TypeError, ValueError):
            return 0.0

    async def mux_av(
        self,
        video: Path,
        audio: Path,
        out: Path,
        *,
        shortest: bool = True,
    ) -> Path:
        out.parent.mkdir(parents=True, exist_ok=True)
        args = [
            "-i",
            str(video),
            "-i",
            str(audio),
            *_safe_encode(self),
            "-c:a",
            "aac",
            "-b:a",
            "192k",
        ]
        if shortest:
            args.append("-shortest")
        args.append(str(out))
        try:
            await self.run(args)
        except RuntimeError:
            if self.encoder != "libx264":
                self.encoder = "libx264"
                args = [
                    "-i",
                    str(video),
                    "-i",
                    str(audio),
                    "-c:v",
                    "libx264",
                    "-preset",
                    "veryfast",
                    "-crf",
                    "23",
                    "-c:a",
                    "aac",
                    "-b:a",
                    "192k",
                    "-shortest",
                    str(out),
                ]
                await self.run(args)
            else:
                raise
        return out

    async def cinematic_from_stills(
        self,
        images: list[Path],
        audio: Path,
        out: Path,
        *,
        width: int = 1080,
        height: int = 1920,
        fps: int = 30,
    ) -> Path:
        """Ken-Burns clips from Comfy stills, then mux voiceover."""
        try:
            return await self._kenburns(images, audio, out, width=width, height=height, fps=fps)
        except Exception as exc:
            logger.warning("Ken Burns failed (%s); using slideshow", exc)
            return await self.slideshow(images, audio, out, width=width, height=height, fps=fps)

    async def _kenburns(
        self,
        images: list[Path],
        audio: Path,
        out: Path,
        *,
        width: int,
        height: int,
        fps: int,
    ) -> Path:
        if not images:
            raise ValueError("No images for cinematic render")
        out.parent.mkdir(parents=True, exist_ok=True)
        dur = await self.duration(audio)
        if dur <= 0:
            dur = max(4.0, len(images) * 3.0)
        per = max(2.5, dur / len(images))
        frames = max(int(per * fps), fps * 2)
        clips: list[Path] = []
        for i, img in enumerate(images):
            clip = out.parent / f"kb_{i:02d}.mp4"
            vf = (
                f"scale={width}:{height}:force_original_aspect_ratio=increase,"
                f"crop={width}:{height},"
                f"zoompan=z='min(zoom+0.0012,1.12)':d={frames}:"
                f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={width}x{height}:fps={fps},"
                "format=yuv420p"
            )
            args = [
                "-loop",
                "1",
                "-i",
                str(img),
                "-vf",
                vf,
                "-t",
                f"{per:.3f}",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "20",
                "-an",
                str(clip),
            ]
            await self.run(args)
            clips.append(clip)
        concat = out.parent / "kb_concat.txt"
        concat.write_text("\n".join(f"file '{c.resolve()}'" for c in clips), encoding="utf-8")
        video_only = out.parent / "kb_video.mp4"
        await self.run(
            [
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat),
                "-c",
                "copy",
                str(video_only),
            ]
        )
        return await self.mux_av(video_only, audio, out)

    async def slideshow(
        self,
        images: list[Path],
        audio: Path,
        out: Path,
        *,
        width: int = 1080,
        height: int = 1920,
        fps: int = 30,
    ) -> Path:
        """Ken-Burns style slideshow from stills + audio → vertical short."""
        if not images:
            raise ValueError("No images for slideshow")
        out.parent.mkdir(parents=True, exist_ok=True)
        dur = await self.duration(audio)
        if dur <= 0:
            dur = max(4.0, len(images) * 3.0)
        per = max(2.0, dur / len(images))

        # Build concat demuxer with zoompan-ish simple scale+pad
        list_file = out.parent / "slides.txt"
        lines: list[str] = []
        for img in images:
            lines.append(f"file '{img.resolve()}'")
            lines.append(f"duration {per:.3f}")
        lines.append(f"file '{images[-1].resolve()}'")
        list_file.write_text("\n".join(lines), encoding="utf-8")

        vf = (
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,"
            f"fps={fps},format=yuv420p"
        )
        args = [
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_file),
            "-i",
            str(audio),
            "-vf",
            vf,
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "23",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-shortest",
            "-movflags",
            "+faststart",
            str(out),
        ]
        # slideshow uses libx264 for filter graph reliability; remux optional
        await self.run(args)
        return out

    async def burn_subtitle_text(
        self,
        video: Path,
        text: str,
        out: Path,
    ) -> Path:
        """Simple drawtext overlay (first ~80 chars)."""
        safe = text.replace(":", "\\:").replace("'", "").replace("%", "")[:80]
        vf = f"drawtext=text='{safe}':fontcolor=white:fontsize=36:x=(w-text_w)/2:y=h-120:box=1:boxcolor=black@0.45"
        args = [
            "-i",
            str(video),
            "-vf",
            vf,
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "23",
            "-c:a",
            "copy",
            str(out),
        ]
        try:
            await self.run(args)
            return out
        except RuntimeError:
            # drawtext may be missing — copy through
            shutil.copy2(video, out)
            return out

    async def cut_segments(
        self,
        src: Path,
        segments: list[tuple[float, float]],
        out: Path,
    ) -> Path:
        """Cut and concat interesting segments."""
        out.parent.mkdir(parents=True, exist_ok=True)
        if not segments:
            raise ValueError("No segments to cut")
        parts: list[Path] = []
        for i, (start, end) in enumerate(segments):
            part = out.parent / f"part_{i:02d}.mp4"
            dur = max(0.5, end - start)
            args = [
                "-ss",
                f"{start:.3f}",
                "-i",
                str(src),
                "-t",
                f"{dur:.3f}",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "23",
                "-c:a",
                "aac",
                str(part),
            ]
            await self.run(args)
            parts.append(part)

        concat = out.parent / "concat.txt"
        concat.write_text(
            "\n".join(f"file '{p.resolve()}'" for p in parts),
            encoding="utf-8",
        )
        args = [
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat),
            "-c",
            "copy",
            str(out),
        ]
        await self.run(args)
        return out

    async def color_card(
        self,
        out: Path,
        *,
        color: str = "0x1a1f2e",
        duration: float = 3.0,
        width: int = 1080,
        height: int = 1920,
        label: str = "",
    ) -> Path:
        """Generate a solid-color video frame sequence as still image via ffmpeg."""
        out.parent.mkdir(parents=True, exist_ok=True)
        # Produce a PNG still
        png = out if out.suffix.lower() == ".png" else out.with_suffix(".png")
        vf = f"color=c={color}:s={width}x{height}:d=1"
        if label:
            safe = label.replace(":", "\\:").replace("'", "")[:40]
            vf += f",drawtext=text='{safe}':fontcolor=white:fontsize=48:x=(w-text_w)/2:y=(h-text_h)/2"
        args = ["-f", "lavfi", "-i", vf, "-frames:v", "1", str(png)]
        await self.run(args)
        return png


def _safe_encode(engine: FFmpegEngine) -> list[str]:
    # Avoid vaapi complex filter interaction in mux helper
    if engine.encoder == "h264_vaapi":
        return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23"]
    return engine._encode_args()
