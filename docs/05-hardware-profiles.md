# Hardware Profiles

Capability probe assigns `quality_profile`, then production brief picks a **render profile**:

| Profile | When | Behavior |
|---------|------|----------|
| `fast` | short preview / low RAM | 1–2 scene, small latent, short timeout |
| `balanced` | default discrete GPU | 1080×1920, medium steps |
| `quality` | high RAM + NVIDIA/Apple | more steps / scenes |
| `patient` | AMD / CPU Comfy hosts | smaller output, **long** Comfy timeout — slow OK, finish required |

## This blueprint’s reference host

- CPU: Ryzen 7 5700X (16 threads)
- RAM: 16 GB
- GPU: Radeon RX 580 (AMD, no modern ROCm) → Comfy often on **CPU**, encoder **h264_amf**
- Profile: **patient** for cinematic shorts

ComfyUI + GPT-SoVITS are primary media engines. FFmpeg only assembles timeline + publish thumbnail.

## Portability rule

Never assume NVIDIA. `agent-otonom doctor` after install. Doctor fails if ComfyUI/GPT-SoVITS down (unless `ALLOW_ENGINE_FALLBACK=true`).
