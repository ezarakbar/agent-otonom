"""Vision engine — ComfyUI is the primary image/video generator."""

from __future__ import annotations

import asyncio
import logging
import random
import uuid
from pathlib import Path
from typing import Any

import httpx

from agent_otonom.engines.ffmpeg_engine import FFmpegEngine

logger = logging.getLogger(__name__)

PALETTE = [
    ("0x0f1c2e", "Dawn"),
    ("0x1b2838", "Harbor"),
    ("0x2c1810", "Ember"),
    ("0x102820", "Forest"),
    ("0x1a1028", "Night"),
    ("0x241c14", "Dust"),
]

NEGATIVE = (
    "(deformed iris, deformed pupils, semi-realistic, cgi, 3d, render, sketch, "
    "cartoon, drawing, anime:1.4), text, watermark, logo, subtitles, close up cropped, "
    "out of frame, worst quality, low quality, jpeg artifacts, ugly, duplicate, "
    "morbid, mutilated, extra fingers, mutated hands, poorly drawn hands, "
    "poorly drawn face, mutation, deformed, blurry, dehydrated, bad anatomy, "
    "bad proportions, extra limbs, cloned face, disfigured, gross proportions, "
    "malformed limbs, missing arms, missing legs, fused fingers, long neck, "
    "plastic skin, mannequin, doll, empty scene without person when a person is required"
)

POSITIVE_SUFFIX = (
    "photoreal documentary still, real human subject with natural skin texture, "
    "cinematic 35mm film, natural lighting, shallow depth of field, "
    "vertical composition, highly detailed, no cartoon, no anime"
)

SAMPLER_PREF = ("euler", "euler_ancestral", "dpmpp_2m", "dpmpp_sde", "ddim")
SCHEDULER_PREF = ("normal", "karras", "simple", "exponential")


class VisionEngine:
    def __init__(
        self,
        comfyui_url: str,
        ffmpeg: FFmpegEngine,
        *,
        checkpoint: str = "",
        allow_fallback: bool = False,
    ) -> None:
        self.comfyui_url = comfyui_url.rstrip("/")
        self.ffmpeg = ffmpeg
        self.checkpoint_override = checkpoint.strip()
        self.allow_fallback = allow_fallback
        self._backend: str | None = None
        self._ckpt: str | None = None
        self._vae: str | None = None
        self._graph_ready: bool = False
        self._sampler: str = "euler"
        self._scheduler: str = "normal"

    async def available(self) -> bool:
        return await self._comfy_ok()

    async def resolve_backend(self) -> str:
        if self._backend:
            return self._backend
        if await self._comfy_ok():
            self._backend = "comfyui"
        else:
            self._backend = "slideshow"
        return self._backend

    async def _comfy_ok(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                r = await client.get(f"{self.comfyui_url}/system_stats")
                return r.status_code == 200
        except Exception:
            return False

    async def make_visuals(
        self,
        scenes: list[str],
        out_dir: Path,
        *,
        quality: str = "medium",
    ) -> tuple[list[Path], str]:
        """Create one visual per scene prompt. Returns (paths, backend)."""
        out_dir.mkdir(parents=True, exist_ok=True)
        backend = await self.resolve_backend()
        if backend == "comfyui":
            paths = await self._comfy_stills(scenes, out_dir, quality=quality)
            if paths:
                return paths, "comfyui"
            if not self.allow_fallback:
                raise RuntimeError(
                    "ComfyUI merespons tapi gagal menghasilkan gambar. "
                    "Pasang checkpoint SD/SDXL di ComfyUI, atau set COMFY_CHECKPOINT."
                )

        if not self.allow_fallback:
            raise RuntimeError(
                "ComfyUI adalah engine utama untuk image/video. "
                f"Jalankan ComfyUI di {self.comfyui_url} lalu ulangi perintah."
            )

        logger.warning("ComfyUI unavailable; ALLOW_ENGINE_FALLBACK uses color cards")
        paths = await self._slideshow_stills(scenes, out_dir, quality=quality)
        return paths, "slideshow"

    async def animatediff_available(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                r = await client.get(f"{self.comfyui_url}/object_info/ADE_AnimateDiffLoaderGen1")
                if r.status_code != 200:
                    return False
                data = r.json().get("ADE_AnimateDiffLoaderGen1") or {}
                opts = (
                    ((data.get("input") or {}).get("required") or {})
                    .get("model_name", [None, {}])[1]
                    .get("options")
                    or []
                )
                return bool(opts)
        except Exception:
            return False

    async def make_motion_clip(
        self,
        prompt: str,
        out_mp4: Path,
        *,
        quality: str = "balanced_cpu",
        frames: int | None = None,
        fps: int = 8,
        timeout: float = 2400.0,
    ) -> tuple[Path, str]:
        """Text → AnimateDiff motion clip (generative video from zero)."""
        out_mp4.parent.mkdir(parents=True, exist_ok=True)
        if not await self.animatediff_available():
            raise RuntimeError(
                "AnimateDiff belum siap di ComfyUI. "
                "Install ComfyUI-AnimateDiff-Evolved + mm_sd_v15_v2.ckpt."
            )
        await self._discover_graph()
        if not self._ckpt:
            raise RuntimeError("No Comfy checkpoint for AnimateDiff")
        w, h, steps = _size_steps(quality, self._ckpt)
        # motion needs smaller latents on CPU
        w = min(w, 512)
        h = min(h, 768)
        n_frames = frames or _motion_frames(quality)
        graph = _animatediff_graph(
            ckpt=self._ckpt,
            motion_name="mm_sd_v15_v2.ckpt",
            prompt=_visual_prompt(prompt),
            negative=NEGATIVE + ", static image, still photo, freeze frame",
            width=w,
            height=h,
            frames=n_frames,
            steps=max(10, steps - 2),
            sampler=self._sampler,
            scheduler=self._scheduler,
            seed=random.randint(1, 2**31 - 1),
            fps=fps,
            prefix=f"agent_ad_{uuid.uuid4().hex[:8]}",
            vae=self._vae,
        )
        webp = out_mp4.with_suffix(".webp")
        async with httpx.AsyncClient(timeout=30.0) as client:
            await self._run_and_save(client, graph, webp, timeout=timeout, prefer_animated=True)
        # Convert animated webp/png sequence to mp4
        if webp.exists() and webp.stat().st_size > 0:
            await self.ffmpeg.run(
                [
                    "-i",
                    str(webp),
                    "-vf",
                    f"fps={fps},format=yuv420p",
                    "-c:v",
                    "libx264",
                    "-preset",
                    "veryfast",
                    "-crf",
                    "20",
                    "-an",
                    str(out_mp4),
                ]
            )
            return out_mp4, "animatediff"
        raise RuntimeError("AnimateDiff finished without animation asset")

    async def _comfy_stills(
        self,
        scenes: list[str],
        out_dir: Path,
        *,
        quality: str,
    ) -> list[Path]:
        await self._discover_graph()
        if not self._ckpt:
            raise RuntimeError(
                "Tidak ada checkpoint ComfyUI. Taruh model .safetensors di folder "
                "models/checkpoints ComfyUI, atau set COMFY_CHECKPOINT."
            )

        w, h, steps = _size_steps(quality, self._ckpt)
        paths: list[Path] = []
        async with httpx.AsyncClient(timeout=30.0) as client:
            for i, scene in enumerate(scenes):
                prompt = _visual_prompt(scene)
                graph = _txt2img_graph(
                    ckpt=self._ckpt,
                    prompt=prompt,
                    negative=NEGATIVE,
                    width=w,
                    height=h,
                    steps=steps,
                    sampler=self._sampler,
                    scheduler=self._scheduler,
                    seed=random.randint(1, 2**31 - 1),
                    prefix=f"agent_{uuid.uuid4().hex[:8]}_{i:02d}",
                    vae=self._vae,
                )
                png = out_dir / f"scene_{i:02d}.png"
                await self._run_and_save(client, graph, png)
                paths.append(png)
        return paths

    async def _discover_graph(self) -> None:
        if self._graph_ready and self._ckpt:
            return
        async with httpx.AsyncClient(timeout=10.0) as client:
            ckpts = await self._list_checkpoints(client)
            if self.checkpoint_override:
                if self.checkpoint_override not in ckpts and ckpts:
                    logger.warning(
                        "COMFY_CHECKPOINT=%s not in Comfy list; trying anyway",
                        self.checkpoint_override,
                    )
                self._ckpt = self.checkpoint_override
            else:
                self._ckpt = _pick_checkpoint(ckpts)

            self._vae = await self._pick_vae(client)

            info = await self._node_info(client, "KSampler")
            samplers = _combo(info, "sampler_name")
            schedulers = _combo(info, "scheduler")
            self._sampler = _first_match(samplers, SAMPLER_PREF) or "euler"
            self._scheduler = _first_match(schedulers, SCHEDULER_PREF) or "normal"
            self._graph_ready = True

    async def _pick_vae(self, client: httpx.AsyncClient) -> str | None:
        names: list[str] = []
        try:
            r = await client.get(f"{self.comfyui_url}/models/vae")
            if r.status_code == 200 and isinstance(r.json(), list):
                names.extend(str(x) for x in r.json())
        except Exception:
            pass
        info = await self._node_info(client, "VAELoader")
        names.extend(_combo(info, "vae_name"))
        prefer = ("vae-ft-mse", "mse", "ema")
        for token in prefer:
            for n in names:
                if token in n.lower():
                    return n
        return names[0] if names else None

    async def _list_checkpoints(self, client: httpx.AsyncClient) -> list[str]:
        names: list[str] = []
        try:
            r = await client.get(f"{self.comfyui_url}/models/checkpoints")
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, list):
                    names.extend(str(x) for x in data)
        except Exception:
            pass
        info = await self._node_info(client, "CheckpointLoaderSimple")
        names.extend(_combo(info, "ckpt_name"))
        # unique, preserve order
        seen: set[str] = set()
        out: list[str] = []
        for n in names:
            if n and n not in seen:
                seen.add(n)
                out.append(n)
        return out

    async def _node_info(self, client: httpx.AsyncClient, node: str) -> dict[str, Any]:
        try:
            r = await client.get(f"{self.comfyui_url}/object_info/{node}")
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, dict):
                    return data.get(node) or data
        except Exception:
            logger.debug("object_info %s failed", node, exc_info=True)
        return {}

    async def _run_and_save(
        self,
        client: httpx.AsyncClient,
        graph: dict[str, Any],
        dest: Path,
        *,
        timeout: float = 1800.0,
        prefer_animated: bool = False,
    ) -> None:
        payload = {"prompt": graph, "client_id": uuid.uuid4().hex}
        r = await client.post(f"{self.comfyui_url}/prompt", json=payload, timeout=30.0)
        if r.status_code >= 400:
            raise RuntimeError(f"ComfyUI /prompt error {r.status_code}: {r.text[:800]}")
        body = r.json()
        if body.get("error") or body.get("node_errors"):
            raise RuntimeError(f"ComfyUI rejected workflow: {body}")
        prompt_id = body.get("prompt_id")
        if not prompt_id:
            raise RuntimeError(f"ComfyUI did not return prompt_id: {body}")

        outputs = await self._wait_history(client, str(prompt_id), timeout=timeout)
        image = _first_image(outputs, prefer_animated=prefer_animated)
        if not image:
            raise RuntimeError("ComfyUI finished without image output")

        params = {
            "filename": image.get("filename"),
            "subfolder": image.get("subfolder") or "",
            "type": image.get("type") or "output",
        }
        img = await client.get(f"{self.comfyui_url}/view", params=params, timeout=120.0)
        img.raise_for_status()
        if not img.content:
            raise RuntimeError("ComfyUI /view returned empty image")
        dest.write_bytes(img.content)

    async def img2img(
        self,
        image: Path,
        prompt: str,
        out_png: Path,
        *,
        quality: str = "medium",
        denoise: float = 0.45,
    ) -> Path:
        """Refine an input image via ComfyUI LoadImage + img2img."""
        await self._discover_graph()
        if not self._ckpt:
            raise RuntimeError("No ComfyUI checkpoint for img2img")
        w, h, steps = _size_steps(quality, self._ckpt)
        uploaded = await self._upload_image(image)
        graph = _img2img_graph(
            ckpt=self._ckpt,
            image_name=uploaded,
            prompt=_visual_prompt(prompt),
            negative=NEGATIVE,
            width=w,
            height=h,
            steps=steps,
            denoise=denoise,
            sampler=self._sampler,
            scheduler=self._scheduler,
            seed=random.randint(1, 2**31 - 1),
            prefix=f"agent_i2i_{uuid.uuid4().hex[:8]}",
            vae=self._vae,
        )
        async with httpx.AsyncClient(timeout=30.0) as client:
            await self._run_and_save(client, graph, out_png, timeout=1800.0)
        return out_png

    async def _upload_image(self, image: Path) -> str:
        data = image.read_bytes()
        async with httpx.AsyncClient(timeout=60.0) as client:
            files = {"image": (image.name, data, "image/png")}
            r = await client.post(f"{self.comfyui_url}/upload/image", files=files)
            r.raise_for_status()
            body = r.json()
            name = body.get("name") or body.get("filename")
            if not name:
                raise RuntimeError(f"Comfy upload failed: {body}")
            return str(name)

    async def _wait_history(
        self,
        client: httpx.AsyncClient,
        prompt_id: str,
        *,
        timeout: float = 1800.0,
    ) -> dict[str, Any]:
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            r = await client.get(f"{self.comfyui_url}/history/{prompt_id}", timeout=15.0)
            if r.status_code == 200:
                data = r.json()
                item = data.get(prompt_id) if isinstance(data, dict) else None
                if item:
                    status = (item.get("status") or {})
                    if status.get("status_str") == "error" or status.get("completed") is False:
                        msgs = status.get("messages") or []
                        if any(m and m[0] == "execution_error" for m in msgs if isinstance(m, list)):
                            raise RuntimeError(f"ComfyUI execution error: {msgs}")
                    outputs = item.get("outputs") or {}
                    if outputs:
                        return outputs
            await asyncio.sleep(2.0)
        raise RuntimeError(f"ComfyUI timed out waiting for prompt {prompt_id}")

    async def _slideshow_stills(
        self,
        scenes: list[str],
        out_dir: Path,
        *,
        quality: str = "medium",
    ) -> list[Path]:
        w, h = (1080, 1920)
        if quality == "low":
            w, h = (720, 1280)
        paths: list[Path] = []
        for i, scene in enumerate(scenes):
            color, _name = PALETTE[i % len(PALETTE)]
            label = (scene[:36] + "…") if len(scene) > 36 else scene
            png = out_dir / f"scene_{i:02d}.png"
            await self.ffmpeg.color_card(png, color=color, width=w, height=h, label=label)
            paths.append(png)
        return paths


def _visual_prompt(scene: str) -> str:
    text = " ".join(scene.split())
    if not text:
        text = "cinematic empty landscape at dusk"
    return f"{text}, {POSITIVE_SUFFIX}"


def _size_steps(quality: str, ckpt: str) -> tuple[int, int, int]:
    """Return (width, height, steps). Prefer smaller latents on CPU hosts."""
    sdxl = "xl" in ckpt.lower() or "sdxl" in ckpt.lower()
    q = (quality or "medium").lower()
    if q in {"fast", "preview", "smoke"}:
        return (512, 768, 10) if sdxl else (384, 640, 10)
    if q in {"balanced_cpu", "patient"}:
        # slower but clearer humans on CPU/AMD — user prefers completion over speed
        return (640, 960, 18) if sdxl else (512, 768, 16)
    if q == "low":
        return (640, 960, 14) if sdxl else (448, 768, 12)
    if q == "high":
        return (768, 1216, 24) if sdxl else (576, 960, 18)
    return (640, 1024, 16) if sdxl else (512, 768, 14)


def _pick_checkpoint(names: list[str]) -> str | None:
    if not names:
        return None
    scored: list[tuple[int, str]] = []
    for n in names:
        low = n.lower()
        if "inpaint" in low or "inpainting" in low:
            continue
        score = 0
        for token, pts in (
            ("realistic", 5),
            ("cinematic", 5),
            ("realvis", 4),
            ("juggernaut", 4),
            ("epicrealism", 4),
            ("photon", 3),
            ("sdxl", 2),
            ("lightning", -2),
        ):
            if token in low:
                score += pts
        scored.append((score, n))
    if not scored:
        return names[0]
    scored.sort(key=lambda x: (-x[0], x[1]))
    return scored[0][1]


def _combo(node_info: dict[str, Any], field: str) -> list[str]:
    try:
        spec = (node_info.get("input") or {}).get("required") or {}
        raw = spec.get(field)
        if isinstance(raw, list) and raw and isinstance(raw[0], list):
            return [str(x) for x in raw[0]]
    except Exception:
        return []
    return []


def _first_match(options: list[str], preferred: tuple[str, ...]) -> str | None:
    lower = {o.lower(): o for o in options}
    for p in preferred:
        if p in lower:
            return lower[p]
    return options[0] if options else None


def _motion_frames(quality: str) -> int:
    q = (quality or "").lower()
    if q in {"fast", "preview", "smoke"}:
        return 8
    if q in {"high", "quality"}:
        return 16
    return 12


def _with_optional_vae(graph: dict[str, Any], vae: str | None) -> dict[str, Any]:
    """Prefer dedicated VAE (needed for Realistic Vision noVAE checkpoints)."""
    if not vae:
        return graph
    graph = dict(graph)
    graph["15"] = {"class_type": "VAELoader", "inputs": {"vae_name": vae}}
    for node in graph.values():
        if not isinstance(node, dict):
            continue
        inputs = node.get("inputs")
        if isinstance(inputs, dict) and inputs.get("vae") == ["4", 2]:
            inputs["vae"] = ["15", 0]
    return graph


def _animatediff_graph(
    *,
    ckpt: str,
    motion_name: str,
    prompt: str,
    negative: str,
    width: int,
    height: int,
    frames: int,
    steps: int,
    sampler: str,
    scheduler: str,
    seed: int,
    fps: int,
    prefix: str,
    vae: str | None = None,
) -> dict[str, Any]:
    return _with_optional_vae(
        {
            "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": ckpt}},
            "14": {
                "class_type": "ADE_AnimateDiffLoaderGen1",
                "inputs": {
                    "model": ["4", 0],
                    "model_name": motion_name,
                    "beta_schedule": "autoselect",
                },
            },
            "5": {
                "class_type": "EmptyLatentImage",
                "inputs": {"batch_size": frames, "height": height, "width": width},
            },
            "6": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["4", 1], "text": prompt}},
            "7": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["4", 1], "text": negative}},
            "3": {
                "class_type": "KSampler",
                "inputs": {
                    "cfg": 6.5,
                    "denoise": 1,
                    "latent_image": ["5", 0],
                    "model": ["14", 0],
                    "negative": ["7", 0],
                    "positive": ["6", 0],
                    "sampler_name": sampler,
                    "scheduler": scheduler,
                    "seed": seed,
                    "steps": steps,
                },
            },
            "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
            "9": {
                "class_type": "SaveAnimatedWEBP",
                "inputs": {
                    "images": ["8", 0],
                    "filename_prefix": prefix,
                    "fps": float(fps),
                    "lossless": False,
                    "quality": 85,
                    "method": "default",
                },
            },
        },
        vae,
    )


def _img2img_graph(
    *,
    ckpt: str,
    image_name: str,
    prompt: str,
    negative: str,
    width: int,
    height: int,
    steps: int,
    denoise: float,
    sampler: str,
    scheduler: str,
    seed: int,
    prefix: str,
    vae: str | None = None,
) -> dict[str, Any]:
    _ = (width, height)  # latent follows source image size after VAEEncode
    return _with_optional_vae(
        {
            "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": ckpt}},
            "10": {"class_type": "LoadImage", "inputs": {"image": image_name}},
            "12": {"class_type": "VAEEncode", "inputs": {"pixels": ["10", 0], "vae": ["4", 2]}},
            "6": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["4", 1], "text": prompt}},
            "7": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["4", 1], "text": negative}},
            "3": {
                "class_type": "KSampler",
                "inputs": {
                    "cfg": 6.0,
                    "denoise": denoise,
                    "latent_image": ["12", 0],
                    "model": ["4", 0],
                    "negative": ["7", 0],
                    "positive": ["6", 0],
                    "sampler_name": sampler,
                    "scheduler": scheduler,
                    "seed": seed,
                    "steps": steps,
                },
            },
            "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
            "9": {
                "class_type": "SaveImage",
                "inputs": {"filename_prefix": prefix, "images": ["8", 0]},
            },
        },
        vae,
    )


def _txt2img_graph(
    *,
    ckpt: str,
    prompt: str,
    negative: str,
    width: int,
    height: int,
    steps: int,
    sampler: str,
    scheduler: str,
    seed: int,
    prefix: str,
    vae: str | None = None,
) -> dict[str, Any]:
    return _with_optional_vae(
        {
            "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": ckpt}},
            "5": {
                "class_type": "EmptyLatentImage",
                "inputs": {"batch_size": 1, "height": height, "width": width},
            },
            "6": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["4", 1], "text": prompt}},
            "7": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["4", 1], "text": negative}},
            "3": {
                "class_type": "KSampler",
                "inputs": {
                    "cfg": 6.5,
                    "denoise": 1,
                    "latent_image": ["5", 0],
                    "model": ["4", 0],
                    "negative": ["7", 0],
                    "positive": ["6", 0],
                    "sampler_name": sampler,
                    "scheduler": scheduler,
                    "seed": seed,
                    "steps": steps,
                },
            },
            "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
            "9": {
                "class_type": "SaveImage",
                "inputs": {"filename_prefix": prefix, "images": ["8", 0]},
            },
        },
        vae,
    )


def _first_image(
    outputs: dict[str, Any], *, prefer_animated: bool = False
) -> dict[str, Any] | None:
    animated: dict[str, Any] | None = None
    still: dict[str, Any] | None = None
    for node in outputs.values():
        if not isinstance(node, dict):
            continue
        for key in ("images", "gifs"):
            items = node.get(key)
            if not isinstance(items, list) or not items:
                continue
            for item in items:
                name = str(item.get("filename") or "").lower()
                if name.endswith((".webp", ".gif", ".mp4", ".webm")):
                    animated = animated or item
                else:
                    still = still or item
    if prefer_animated:
        return animated or still
    return still or animated
