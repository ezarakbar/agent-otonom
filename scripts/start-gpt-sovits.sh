#!/usr/bin/env bash
set -euo pipefail
ROOT="${SOVITS_ROOT:-$HOME/GPT-SoVITS}"
cd "$ROOT"
export PYTHONUNBUFFERED=1
exec "$ROOT/venv/bin/python" api_v2.py -a 127.0.0.1 -p 9880 -c GPT_SoVITS/configs/tts_infer.yaml
