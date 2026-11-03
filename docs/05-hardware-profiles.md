# Hardware Profiles

Capability probe assigns `quality_profile`:

| Profile | When | Behavior |
|---------|------|----------|
| `low` | RAM &lt; 12 GB | Smaller frames (720×1280), lighter scripts |
| `medium` | RAM ≥ 12 GB | 1080×1920 slideshow, default models |
| `high` | RAM ≥ 24 GB + discrete GPU | Reserved for heavier Comfy/I2V paths (v0.2+) |

## This blueprint’s reference host

- CPU: Ryzen 7 5700X (16 threads)
- RAM: 16 GB → **medium**
- GPU: Radeon RX 580 (AMD, no CUDA) → encoder **h264_amf** (fallback libx264)
- LLM: `qwen2.5:3b` via Ollama

## Portability rule

Never assume NVIDIA. Always call `agent-otonom doctor` after install.
