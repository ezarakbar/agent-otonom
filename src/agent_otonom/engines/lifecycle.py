"""Start/stop heavy media engines on demand so idle RAM stays free."""

from __future__ import annotations

import asyncio
import logging
import shutil
from typing import Iterable

import httpx

log = logging.getLogger(__name__)

COMFY_UNIT = "agent-otonom-comfyui.service"
SOVITS_UNIT = "agent-otonom-gpt-sovits.service"


async def _systemctl(*args: str) -> tuple[int, str]:
    if not shutil.which("systemctl"):
        return 1, "systemctl missing"
    proc = await asyncio.create_subprocess_exec(
        "systemctl",
        "--user",
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    out, _ = await proc.communicate()
    return proc.returncode or 0, (out or b"").decode("utf-8", errors="replace").strip()


async def ensure_started(units: Iterable[str], *, timeout_sec: float = 120.0) -> None:
    for unit in units:
        code, _ = await _systemctl("is-active", unit)
        if code == 0:
            continue
        log.info("Starting media engine unit %s", unit)
        await _systemctl("start", unit)


async def wait_http(url: str, *, timeout_sec: float = 120.0) -> bool:
    deadline = asyncio.get_event_loop().time() + timeout_sec
    while asyncio.get_event_loop().time() < deadline:
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                r = await client.get(url)
                if r.status_code < 500:
                    return True
        except Exception:
            pass
        await asyncio.sleep(1.5)
    return False


async def free_comfy_memory(comfy_base_url: str) -> None:
    """Ask ComfyUI to unload models from RAM/VRAM after a job."""
    url = f"{comfy_base_url.rstrip('/')}/free"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            await client.post(url, json={"unload_models": True, "free_memory": True})
    except Exception as exc:
        log.debug("Comfy free_memory skipped: %s", exc)


async def stop_units(units: Iterable[str]) -> None:
    for unit in units:
        log.info("Stopping idle media engine unit %s", unit)
        await _systemctl("stop", unit)


async def ensure_media_engines(
    *,
    comfy_base_url: str,
    sovits_base_url: str,
    need_comfy: bool = True,
    need_sovits: bool = True,
) -> None:
    units: list[str] = []
    if need_comfy:
        units.append(COMFY_UNIT)
    if need_sovits:
        units.append(SOVITS_UNIT)
    if units:
        await ensure_started(units)
    if need_comfy:
        ok = await wait_http(f"{comfy_base_url.rstrip('/')}/system_stats", timeout_sec=180.0)
        if not ok:
            raise RuntimeError(f"ComfyUI tidak siap di {comfy_base_url}")
    if need_sovits:
        # SoVITS api_v2 may 404 on /, so probe a light path or accept connect
        base = sovits_base_url.rstrip("/")
        ok = await wait_http(f"{base}/", timeout_sec=180.0)
        if not ok:
            # some builds only answer POST — treat TCP connect via any response as enough
            try:
                async with httpx.AsyncClient(timeout=3.0) as client:
                    await client.get(base)
            except httpx.ConnectError as exc:
                raise RuntimeError(f"GPT-SoVITS tidak siap di {sovits_base_url}") from exc


async def release_media_engines(
    *,
    comfy_base_url: str,
    stop_comfy: bool = True,
    stop_sovits: bool = True,
) -> None:
    if stop_comfy:
        await free_comfy_memory(comfy_base_url)
        await stop_units([COMFY_UNIT])
    if stop_sovits:
        await stop_units([SOVITS_UNIT])
