# Pipeline Blueprint

## cinematic_short

1. Intent → `cinematic_short`
2. LLM writes 65–110 word voiceover (ID/EN)
3. Voice engine synthesizes WAV (SoVITS → Piper → espeak)
4. Vision creates scene stills (ComfyUI if available, else color-card Ken-Burns frames)
5. FFmpeg slideshow + AAC mux → optional drawtext → `outputs/<job>/final.mp4`

## video_clipper

1. Intent → `video_clipper` (requires uploaded / absolute path)
2. Probe duration via ffprobe
3. Heuristic highlight windows (+ optional LLM refine)
4. FFmpeg cut parts + concat → `outputs/<job>/highlights.mp4`

## dynamic

1. Intent unknown / `other`
2. UI asks confirmation (default)
3. LLM writes `workflows/_generated/gen_*.py`
4. Sandbox AST validation
5. Register + enqueue like a built-in workflow

## Status lines (UI contract)

Only clean messages reach the chat, e.g.:

- `Status: Menulis naskah (Ollama)…`
- `Status: Voiceover selesai (piper)`
- `Status: Merender video via FFmpeg (h264_amf)…`
- `Selesai: outputs/.../final.mp4`

Raw ffmpeg/ollama logs go to `logs/agent-otonom.log`.
