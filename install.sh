#!/usr/bin/env bash
# AGENT OTONOM — multi-distro installer (Linux/macOS)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

echo "==> AGENT OTONOM installer"
echo "    root: $ROOT"

os="$(uname -s | tr '[:upper:]' '[:lower:]')"
need_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "ERROR: '$1' tidak ditemukan. Install dulu lalu jalankan ulang."
    exit 1
  fi
}

need_cmd python3
need_cmd ffmpeg

if ! command -v ollama >/dev/null 2>&1; then
  echo "WARN: ollama belum ada. Install dari https://ollama.com lalu: ollama pull qwen2.5:3b"
fi

PY=python3
if command -v python3.12 >/dev/null 2>&1; then PY=python3.12; fi
if command -v python3.11 >/dev/null 2>&1; then PY=python3.11; fi

echo "==> Python: $($PY --version)"
$PY -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --upgrade pip wheel
python -m pip install -e .

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "==> Created .env from .env.example"
fi

mkdir -p outputs jobs logs uploads workflows/_generated models/piper models/sovits

# Optional: Piper TTS (Linux x86_64)
install_piper() {
  local ver="2023.11.14-2"
  local arch
  arch="$(uname -m)"
  local asset=""
  if [[ "$os" == "linux" && "$arch" == "x86_64" ]]; then
    asset="piper_linux_x86_64.tar.gz"
  elif [[ "$os" == "linux" && ( "$arch" == "aarch64" || "$arch" == "arm64" ) ]]; then
    asset="piper_linux_aarch64.tar.gz"
  elif [[ "$os" == "darwin" && "$arch" == "arm64" ]]; then
    asset="piper_macos_aarch64.tar.gz"
  elif [[ "$os" == "darwin" ]]; then
    asset="piper_macos_x64.tar.gz"
  else
    echo "WARN: Piper auto-install tidak didukung untuk $os/$arch — skip"
    return 0
  fi
  if [[ -x "$ROOT/piper/piper" ]]; then
    echo "==> Piper already present"
    return 0
  fi
  echo "==> Downloading Piper ($asset)…"
  mkdir -p "$ROOT/piper"
  local url="https://github.com/rhasspy/piper/releases/download/${ver}/${asset}"
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL -o /tmp/piper.tgz "$url" || { echo "WARN: gagal unduh Piper"; return 0; }
  else
    wget -q -O /tmp/piper.tgz "$url" || { echo "WARN: gagal unduh Piper"; return 0; }
  fi
  tar -xzf /tmp/piper.tgz -C "$ROOT/piper" --strip-components=1 2>/dev/null \
    || tar -xzf /tmp/piper.tgz -C "$ROOT/piper"
  # normalize binary path
  if [[ ! -x "$ROOT/piper/piper" ]]; then
    find "$ROOT/piper" -type f -name piper -executable | head -1 | while read -r p; do
      ln -sf "$p" "$ROOT/piper/piper"
    done
  fi
  chmod +x "$ROOT/piper/piper" 2>/dev/null || true
}

install_piper_voice() {
  local model_dir="$ROOT/models/piper"
  mkdir -p "$model_dir"
  if ls "$model_dir"/*.onnx >/dev/null 2>&1; then
    echo "==> Piper voice model already present"
    return 0
  fi
  echo "==> Downloading Piper voice (en_US-lessac-medium)…"
  local base="https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium"
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL -o "$model_dir/en_US-lessac-medium.onnx" "$base/en_US-lessac-medium.onnx" || true
    curl -fsSL -o "$model_dir/en_US-lessac-medium.onnx.json" "$base/en_US-lessac-medium.onnx.json" || true
  fi
}

install_piper || true
install_piper_voice || true

# Wire piper into .env if found
if [[ -x "$ROOT/piper/piper" ]]; then
  model="$(ls "$ROOT/models/piper"/*.onnx 2>/dev/null | head -1 || true)"
  if [[ -n "${model:-}" ]]; then
    if grep -q '^PIPER_BIN=' .env; then
      sed -i.bak "s|^PIPER_BIN=.*|PIPER_BIN=$ROOT/piper/piper|" .env || true
    else
      echo "PIPER_BIN=$ROOT/piper/piper" >> .env
    fi
    if grep -q '^PIPER_MODEL=' .env; then
      sed -i.bak "s|^PIPER_MODEL=.*|PIPER_MODEL=$model|" .env || true
    else
      echo "PIPER_MODEL=$model" >> .env
    fi
    rm -f .env.bak
  fi
fi

# Pull Ollama model if available
MODEL="$(grep -E '^OLLAMA_MODEL=' .env | cut -d= -f2- || echo qwen2.5:3b)"
MODEL="${MODEL:-qwen2.5:3b}"
if command -v ollama >/dev/null 2>&1; then
  echo "==> Ensuring Ollama model: $MODEL"
  ollama serve >/dev/null 2>&1 &
  sleep 1 || true
  ollama pull "$MODEL" || echo "WARN: ollama pull gagal — jalankan manual: ollama pull $MODEL"
fi

echo "==> Running doctor…"
python -m agent_otonom doctor || true

echo ""
echo "Selesai. Jalankan:"
echo "  source .venv/bin/activate"
echo "  agent-otonom serve"
echo "  # buka http://127.0.0.1:8790"
