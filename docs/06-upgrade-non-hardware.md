# Upgrade non-hardware (catatan)

Prioritas setelah hardware (mis. RTX 3060 12 GB + 32 GB RAM). Pasang bertahap; jangan semua sekaligus di mesin 16 GB.

## Sudah ada
- ComfyUI + **AnimateDiff Evolved** (`mm_sd_v15_v2`)
- Checkpoint **Realistic Vision V5.1** + **VAE ft-mse**
- GPT-SoVITS (TTS), FFmpeg finish (loudnorm, SRT, QC, publish pack)
- Comfy/SoVITS **on-demand** (nyala saat job, mati setelah selesai)
- Jalur utama WebGUI: **teks → cinematic_short** (bukan photo→video / clipper)

## Plugin / model berikutnya (kualitas)
| Item | Fungsi | Catatan |
|------|--------|---------|
| **Lipsync server** (MuseTalk / Wav2Lip) | Mulut sinkron audio | Set `LIPSYNC_BASE_URL` di `.env` |
| **ComfyUI_IPAdapter_plus** + FaceID | Wajah konsisten antar scene | Butuh model InsightFace/IP-Adapter |
| **ControlNet OpenPose** (SD1.5) | Pose/gerakan terkendali | Cocok digabung AnimateDiff |
| Checkpoint realistis lain (opsional) | Variasi gaya | EpicRealism / RealVis — tetap SD1.5 di VRAM 12 GB |
| Upscaler (4x-UltraSharp) | Still/thumbnail lebih tajam | Ringan dibanding video model |

## Bukan plugin, tapi dibutuhkan
- Speaker **reference WAV** berkualitas untuk SoVITS (`SOVITS_REF_AUDIO`)
- Prompt/brief yang memaksa manusia nyata (sudah di pipeline)
- QC + review Owner sebelum upload publik
- Jangan enable Comfy/SoVITS selalu-on — hemat RAM

## Urutan pasang disarankan
1. Lipsync server + `LIPSYNC_BASE_URL`
2. IP-Adapter FaceID
3. ControlNet OpenPose
4. Upscaler + fine-tune langkah/sampler di profile `quality`

## Skrip
```bash
./scripts/bootstrap-pro-media.sh   # AnimateDiff + Realistic Vision + VAE
```
