# Hardware Profiles

Capability probe assigns `quality_profile`:

| Profile | When | Behavior |
|---------|------|----------|
| `low` | RAM &lt; 12 GB | Smaller frames (720×1280), lighter scripts |
| `medium` | RAM ≥ 12 GB | 1080×1920 slideshow, default models |
| `high` | RAM ≥ 24 GB + discrete GPU | Larger Comfy latents / more sampler steps |

## This blueprint’s reference host

- CPU: Ryzen 7 5700X (16 threads)
- RAM: 16 GB → **medium**
- GPU: Radeon RX 580 (AMD, no CUDA) → encoder **h264_amf** (fallback libx264)
- LLM: `qwen2.5:3b` via Ollama

ComfyUI + GPT-SoVITS should be running on this host (or LAN) even on AMD — they are the media engines, FFmpeg only assembles the timeline.

## Portability rule

Never assume NVIDIA. Always call `agent-otonom doctor` after install. Doctor **fails** if ComfyUI or GPT-SoVITS is down (unless `ALLOW_ENGINE_FALLBACK=true`).
