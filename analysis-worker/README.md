# PadelIQ analysis worker

An initial commercially friendly video-analysis service for court calibration, selected-player tracking, court positions, movement heatmaps, distance and recovery-position proxies.

## Open-source components

- OpenCV — Apache 2.0
- Paddle/RT-DETR model architecture accessed through Transformers — Apache 2.0 code; verify the selected checkpoint card before production
- ByteTrack through Supervision — MIT
- PyTorch — BSD-style
- Transformers — Apache 2.0

Keep all dependency licence and notice files in production distributions. Do not substitute Ultralytics models without reviewing their AGPL/commercial terms.

## Run locally

```bash
docker build -t padeliq-analysis .
docker run --rm -p 8080:8080 \
  -e ALLOWED_ORIGINS=https://your-app.vercel.app \
  padeliq-analysis
```

`POST /jobs` accepts a `video` file and a JSON `calibration` form field. Court corners must be ordered top-left, top-right, bottom-right and bottom-left in original video pixel coordinates. `player` is the selected player's pixel position in the same frame.

The current in-memory job store is suitable for a controlled prototype. Production requires object storage, a persistent queue/database, authentication, file limits and scheduled deletion of raw footage.

