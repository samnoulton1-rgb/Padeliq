---
title: PadelIQ Analysis
emoji: 🎾
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 8080
pinned: false
---

# PadelIQ analysis worker

An initial commercially friendly video-analysis service for court calibration, selected-player tracking, court positions, movement heatmaps, distance and recovery-position proxies. The tracker supports multiple time-stamped player references, appearance-and-motion identity reacquisition, court-side constraints, short-gap interpolation and a reliability gate. An optional Qwen3-VL layer turns sampled frames and measured metrics into cautious coaching feedback only after the tracking-quality gate passes.

Users may explicitly opt in to 24-hour diagnostic retention. When enabled, the worker keeps the source video and a tracking-overlay copy behind an unguessable temporary token. Expired files are removed automatically; the default remains immediate deletion after analysis. Space storage is ephemeral, so diagnostics are best-effort and may disappear earlier if the worker restarts.

## Open-source components

- OpenCV — Apache 2.0
- Paddle/RT-DETR model architecture accessed through Transformers — Apache 2.0 code; verify the selected checkpoint card before production
- ByteTrack through Supervision — MIT
- PyTorch — BSD-style
- Transformers — Apache 2.0
- Qwen3-VL-2B-Instruct — Apache 2.0

Keep all dependency licence and notice files in production distributions. Do not substitute Ultralytics models without reviewing their AGPL/commercial terms.

## Run locally

```bash
docker build -t padeliq-analysis .
docker run --rm -p 8080:8080 \
  -e ALLOWED_ORIGINS=https://your-app.vercel.app \
  -e ENABLE_VIDEO_LLM=true \
  padeliq-analysis
```

`POST /jobs` accepts a `video` file and a JSON `calibration` form field. Court corners must be ordered top-left, top-right, bottom-right and bottom-left in original video pixel coordinates. `player` is the selected player's pixel position in the same frame.

The current in-memory job store is suitable for a controlled prototype. Production requires object storage, a persistent queue/database, authentication, file limits and scheduled deletion of raw footage.

The 2B video-language model is intended for prototype feedback. It does not yet make reliable shot-by-shot calls; those require a labelled padel dataset and a dedicated temporal classifier. On free CPU hosting, the first model download and each inference can take several minutes.
