# AGENT OTONOM

**Local autonomous AI agent** controlled by chat.  
Dynamic workflow router & generator · capability-aware media pipeline · professional WebGUI.

[![License: MIT](https://img.shields.io/badge/License-MIT-teal.svg)](LICENSE)

## What it does

You type natural language:

- *“Buatkan film sinematik tentang pelabuhan di senja”* → **cinematic short**
- *“Potong video ini jadi highlight”* → **video clipper**
- Unknown task → agent **writes a new Python workflow**, sandboxes it, then runs it

Background workers keep the UI responsive. Chat shows clean status lines only — no terminal noise.

## Quick start

### Linux / macOS

```bash
git clone https://github.com/ezarakbar/agent-otonom.git
cd agent-otonom
chmod +x install.sh
./install.sh
source .venv/bin/activate
agent-otonom doctor
agent-otonom serve
```

Open **http://127.0.0.1:8790**

### Windows

```powershell
git clone https://github.com/ezarakbar/agent-otonom.git
cd agent-otonom
.\install.ps1
.\.venv\Scripts\Activate.ps1
agent-otonom doctor
agent-otonom serve
```

### Prerequisites

| Tool | Required | Notes |
|------|----------|-------|
| Python 3.11+ | yes | 3.12 recommended |
| FFmpeg | yes | with ffprobe |
| Ollama + model | yes | naskah / storyboard (`qwen2.5:3b`) |
| ComfyUI | yes | **engine utama image & video** (`:8188`) |
| GPT-SoVITS | yes | **engine utama audio** (`:9880`) |
| Piper / espeak-ng | no | hanya jika `ALLOW_ENGINE_FALLBACK=true` |

## CLI

```bash
agent-otonom doctor
agent-otonom workflows
agent-otonom chat "Buatkan film sinematik tentang laut"
agent-otonom chat "Potong highlight" --input-video /path/to/in.mp4
agent-otonom serve --host 127.0.0.1 --port 8790
```

## Architecture (short)

See [docs/00-architecture.md](docs/00-architecture.md).

```
Chat → Intent Router → Workflow Manager → Async Queue
                         ↘ generate+sandbox if missing
Engines: Ollama · **GPT-SoVITS (audio)** · **ComfyUI (image/video)** · FFmpeg
```

Hardware probe picks encoder automatically (**AMF** on AMD, **NVENC** on NVIDIA, etc.).

## Project layout

```
src/agent_otonom/   # core package
workflows/          # built-in + _generated dynamic modules
web/                # WebGUI
docs/               # blueprint, roadmap, engines, security
outputs/            # job artifacts
```

## Documentation

| Doc | Topic |
|-----|-------|
| [00-architecture](docs/00-architecture.md) | System design |
| [01-roadmap](docs/01-roadmap.md) | Version plan |
| [02-blueprint-pipelines](docs/02-blueprint-pipelines.md) | Media pipelines |
| [03-engines-setup](docs/03-engines-setup.md) | Ollama / Piper / Comfy / SoVITS |
| [04-security-sandbox](docs/04-security-sandbox.md) | Dynamic code safety |
| [05-hardware-profiles](docs/05-hardware-profiles.md) | Adaptive quality |

## Systemd (Linux user unit)

```bash
mkdir -p ~/.config/systemd/user
cp systemd/agent-otonom.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now agent-otonom.service
```

## Safety

- Artifacts stay local under `outputs/`
- No auto-upload to social platforms
- Dynamic workflows require confirmation by default

## License

MIT © ezarakbar
