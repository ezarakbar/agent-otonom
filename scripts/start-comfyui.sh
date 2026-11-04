#!/usr/bin/env bash
set -euo pipefail
ROOT="${COMFYUI_ROOT:-$HOME/ComfyUI}"
cd "$ROOT"
exec "$ROOT/.venv/bin/python" main.py --listen 127.0.0.1 --port 8188 --cpu
