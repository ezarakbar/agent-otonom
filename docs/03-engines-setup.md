# Engines Setup

## Required

### Ollama

```bash
# install from https://ollama.com
ollama serve
ollama pull qwen2.5:3b
```

Set `OLLAMA_BASE_URL` / `OLLAMA_MODEL` in `.env`.

### FFmpeg

Must include `ffmpeg` + `ffprobe` on PATH.  
Encoder is auto-selected:

| GPU | Preferred encoder |
|-----|-------------------|
| AMD | `h264_amf` → `h264_vaapi` → `libx264` |
| NVIDIA | `h264_nvenc` → `libx264` |
| Intel | `h264_qsv` → `h264_vaapi` → `libx264` |
| Apple | `h264_videotoolbox` → `libx264` |

## Recommended

### Piper (local TTS)

`install.sh` downloads Piper + `en_US-lessac-medium` when possible.  
Or set:

```
PIPER_BIN=/path/to/piper
PIPER_MODEL=/path/to/model.onnx
```

### espeak-ng

Fallback if Piper/SoVITS unavailable:

```bash
# Arch
sudo pacman -S espeak-ng
# Debian/Ubuntu
sudo apt install espeak-ng
```

## Optional (heavy)

### GPT-SoVITS API

Run your SoVITS API server (default `http://127.0.0.1:9880`).  
Agent detects it automatically and prefers it for voiceover.

### ComfyUI

Run ComfyUI on `http://127.0.0.1:8188`.  
v0.1 uses Comfy only when a future bundled graph is present; otherwise slideshow fallback keeps pipelines green on AMD/low-VRAM hosts.

### Wan 2.1 / SVD

Treat as ComfyUI custom nodes / workflows. Wire through Comfy API later (roadmap v0.2).
