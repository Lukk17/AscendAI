# PaddleOCR load profiles

Driven by the api-tester audit recommendation: find the breaking point of the `asyncio.to_thread` boundary
introduced when `process_ocr` was switched off the event loop.

## k6 ramp

[`k6-ocr-ramp.js`](k6-ocr-ramp.js) ramps 5 → 20 → 40 → 80 VUs with three soak plateaus. Run from the repo root:

```powershell
k6 run PaddleOCR/e2e/load/k6-ocr-ramp.js
```

Override target with `BASE_URL`:

```powershell
$env:BASE_URL = "http://localhost:7022"; k6 run PaddleOCR/e2e/load/k6-ocr-ramp.js
```

Override fixture path with `FIXTURE_PATH`.

## Thresholds

- p95 `http_req_duration` < 30s at the 20-VU plateau (well under `OCR_REQUEST_TIMEOUT=120s`).
- 5xx rate < 1% at the 20-VU plateau.

A run that fails either threshold means the event-loop / thread-pool fix has regressed. Compare against the
last green run baseline.
