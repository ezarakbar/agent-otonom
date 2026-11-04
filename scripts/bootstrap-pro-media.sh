#!/usr/bin/env bash
# Install generative media add-ons for ComfyUI (AnimateDiff + realistic SD1.5 + VAE).
set -euo pipefail
COMFY="${COMFYUI_ROOT:-$HOME/ComfyUI}"
CN="$COMFY/custom_nodes"
CKPT_DIR="$COMFY/models/checkpoints"
VAE_DIR="$COMFY/models/vae"
AD_DIR="$COMFY/models/animatediff_models"
mkdir -p "$CN" "$CKPT_DIR" "$VAE_DIR" "$AD_DIR"

if [[ ! -d "$CN/ComfyUI-AnimateDiff-Evolved" ]]; then
  git clone --depth 1 https://github.com/Kosinkadink/ComfyUI-AnimateDiff-Evolved.git \
    "$CN/ComfyUI-AnimateDiff-Evolved"
fi

MM="$AD_DIR/mm_sd_v15_v2.ckpt"
if [[ ! -s "$MM" ]]; then
  curl -L --fail --retry 5 -C - -o "$MM.partial" \
    "https://huggingface.co/guoyww/animatediff/resolve/main/mm_sd_v15_v2.ckpt"
  mv "$MM.partial" "$MM"
fi

# Photoreal SD1.5 (far better humans than stock v1-5-pruned)
RV="$CKPT_DIR/Realistic_Vision_V5.1_fp16-no-ema.safetensors"
if [[ ! -s "$RV" ]]; then
  curl -L --fail --retry 5 -C - -o "$RV.partial" \
    "https://huggingface.co/SG161222/Realistic_Vision_V5.1_noVAE/resolve/main/Realistic_Vision_V5.1_fp16-no-ema.safetensors"
  mv "$RV.partial" "$RV"
fi

# Recommended VAE for Realistic Vision (sharper, fewer gray artifacts)
VAE="$VAE_DIR/vae-ft-mse-840000-ema-pruned.safetensors"
if [[ ! -s "$VAE" ]]; then
  curl -L --fail --retry 5 -C - -o "$VAE.partial" \
    "https://huggingface.co/stabilityai/sd-vae-ft-mse-original/resolve/main/vae-ft-mse-840000-ema-pruned.safetensors"
  mv "$VAE.partial" "$VAE"
fi

echo "Ready:"
echo "  AnimateDiff: $MM"
echo "  Checkpoint:  $RV"
echo "  VAE:         $VAE"
echo
echo "Set in .env:"
echo "  COMFY_CHECKPOINT=Realistic_Vision_V5.1_fp16-no-ema.safetensors"
echo
echo "ComfyUI + GPT-SoVITS are on-demand (start during a job, stop after)."
echo "Optional lipsync server → set LIPSYNC_BASE_URL in .env"
echo "Optional next plugins (heavy on 16GB): ComfyUI_IPAdapter_plus + FaceID, ControlNet OpenPose"
