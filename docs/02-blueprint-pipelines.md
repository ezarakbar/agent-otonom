# Pipeline Blueprint

## cinematic_short (generatif dari teks)

1. Intent → `cinematic_short`
2. Brief produksi + riset web (otomatis dijalankan bila `AUTO_EXECUTE_PRODUCTION=true`)
3. **Teks → audio** via GPT-SoVITS + ambience + loudnorm (−14 LUFS)
4. **Teks → foto** keyframe via ComfyUI txt2img
5. **Teks → video gerak** via ComfyUI **AnimateDiff** (bukan mengubah foto user)
6. Lipsync (jika `LIPSYNC_BASE_URL` aktif) + mux audio
7. Subtitle SRT burn-in
8. Publish pack (judul/hashtag/thumbnail) + **QC gate**

Fallback gerak: Ken Burns dari **still yang digenerate dari teks** (bukan upload user).

## image_to_video (opsional / sekunder)

Hanya jika user sengaja upload gambar untuk refine. Produksi utama selalu text→AV.

## video_clipper

Potong highlight dari video sumber + pack upload.

## Status lines (UI contract)

- `Status: Teks → audio (GPT-SoVITS)…`
- `Status: Teks → foto keyframe (ComfyUI)…`
- `Status: Teks → video gerak (AnimateDiff)…`
- `Status: QC PASS — siap upload`
