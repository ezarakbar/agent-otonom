# Roadmap

## v0.1 (current) — Foundation

- [x] Capability probe + quality profiles
- [x] FastAPI + WebSocket WebGUI
- [x] Async job queue + SQLite
- [x] Built-in `cinematic_short` & `video_clipper`
- [x] Dynamic workflow generator + sandbox
- [x] Engine degrade: Ollama / Piper|espeak / slideshow / FFmpeg AMF→x264
- [x] Multi-OS install scripts

## v0.2 — Stronger media

- [x] ComfyUI as primary image engine (live txt2img via `/prompt`, not a stub)
- [x] GPT-SoVITS as primary audio engine (api_v2 `/tts` + legacy shapes)
- [x] Storyboard JSON so visuals follow the user prompt
- [ ] Native I2V (Wan / SVD) when those Comfy nodes exist
- [ ] GPT-SoVITS speaker profiles UI
- [ ] Better clipper: scene-detect via PySceneDetect

## v0.3 — Autonomy hardening

- [ ] Workflow unit tests + eval harness
- [ ] Per-job resource budgets (RAM/CPU)
- [ ] Multi-worker safe file locking
- [ ] Plugin marketplace folder convention

## v1.0 — Production local studio

- [ ] Signed workflow packages
- [ ] Timeline editor in WebGUI
- [ ] Project workspaces / multi-brand profiles
