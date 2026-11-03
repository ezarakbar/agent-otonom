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

- [ ] Bundle ComfyUI workflow JSON for still / I2V when API is up
- [ ] GPT-SoVITS first-class voice profiles (speaker refs)
- [ ] Better clipper: scene-detect via PySceneDetect
- [ ] Indonesian Piper voice pack in installer

## v0.3 — Autonomy hardening

- [ ] Workflow unit tests + eval harness
- [ ] Per-job resource budgets (RAM/CPU)
- [ ] Multi-worker safe file locking
- [ ] Plugin marketplace folder convention

## v1.0 — Production local studio

- [ ] Signed workflow packages
- [ ] Timeline editor in WebGUI
- [ ] Project workspaces / multi-brand profiles
