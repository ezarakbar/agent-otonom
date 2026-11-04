# Engines Setup

## Required (media)

ComfyUI and GPT-SoVITS are **primary** tools for image, video, and audio.  
The agent will not silently replace them with color cards or espeak unless you set `ALLOW_ENGINE_FALLBACK=true`.

### ComfyUI (image / video)

```bash
# typical
cd /path/to/ComfyUI
python main.py --listen 127.0.0.1 --port 8188
```

- Default URL: `http://127.0.0.1:8188` (`COMFYUI_BASE_URL`)
- Put at least one **SD 1.5 or SDXL** checkpoint in Comfy `models/checkpoints/`
- Optional: `COMFY_CHECKPOINT=myModel.safetensors`
- Agent discovers checkpoints via `/models/checkpoints` + `/object_info`, queues txt2img on `/prompt`, then downloads `/view`

Without a checkpoint, ComfyUI is “up” but generation fails — install a realistic/cinematic model.

### GPT-SoVITS (audio)

```bash
cd /path/to/GPT-SoVITS
python api_v2.py -a 127.0.0.1 -p 9880
```

- Default URL: `http://127.0.0.1:9880` (`SOVITS_BASE_URL`)
- **api_v2 needs a reference voice**: put a short clean `.wav` in `models/sovits/` or set `SOVITS_REF_AUDIO=/path/to/ref.wav`
- Optional: `SOVITS_PROMPT_TEXT` (transcript of the ref clip), `SOVITS_PROMPT_LANG=auto`

Indonesian text is sent as `text_lang=auto` (SoVITS has no dedicated `id` code).

### Ollama

```bash
ollama serve
ollama pull qwen2.5:3b
```

Set `OLLAMA_BASE_URL` / `OLLAMA_MODEL` in `.env`. Used for storyboard + intent, not pixels.

### FFmpeg

Must include `ffmpeg` + `ffprobe` on PATH.  
Encoder is auto-selected:

| GPU | Preferred encoder |
|-----|-------------------|
| AMD | `h264_amf` → `h264_vaapi` → `libx264` |
| NVIDIA | `h264_nvenc` → `libx264` |
| Intel | `h264_qsv` → `h264_vaapi` → `libx264` |
| Apple | `h264_videotoolbox` → `libx264` |

## Fallback only (off by default)

Piper / espeak-ng / slideshow color-cards run **only** if:

```
ALLOW_ENGINE_FALLBACK=true
```

That mode is for machines without GPU services. It will **not** match the prompt visually.

```
PIPER_BIN=/path/to/piper
PIPER_MODEL=/path/to/model.onnx
```

## Wan 2.1 / SVD

Treat as ComfyUI custom nodes. Still muxed through the same Comfy API; native I2V graphs are next.
