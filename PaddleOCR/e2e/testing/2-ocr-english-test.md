# OCR English canary: e2e test

## What this verifies

- `POST /v1/ocr` with the `argent-saga-chronicles-page1.png` fixture and `lang=en` returns HTTP 200.
- The response body parses as an `OcrJsonResponse` with `filename`, `language`, `pages`, `processing_time_seconds`.
- `language` echoes back `"en"`.
- `pages` is a non-empty array; at least one `OcrPageResult` has at least one `OcrTextLine`.
- The concatenated `pages[*].lines[*].text` (case-insensitive) contains the canary substring `Argent Saga`, `Aenaria`, or `Halen Veyr`.
- Each `OcrTextLine.confidence` is a finite number in `[0.0, 1.0]`.
- Each `OcrTextLine.bounding_box` is a non-empty list of `[x, y]` coordinate pairs.
- `processing_time_seconds` is a finite non-negative number.

## Prerequisites

Check Bruno CLI is installed.

```powershell
bru --version
```

Expect a version string.

Check the PaddleOCR server is reachable.

```powershell
curl -fsS http://localhost:7022/health
```

Expect HTTP 200 with `"status":"ok"` in the body.

Check the English canary fixture exists.

```powershell
Test-Path PaddleOCR/e2e/fixtures/argent-saga-chronicles-page1.png
```

Expect `True`. If missing, generate it per [`PaddleOCR/e2e/fixtures/README.md`](../fixtures/README.md).

## Reset state

None. OCR is stateless except for the warmed engine cache, which is initialised at container startup for the
`DEFAULT_LANGUAGE` and re-used for every request in that language.

## Run

Single Bruno request.

```powershell
cd docs/api/request/AscendAI
```

```powershell
bru run "paddle-ocr/testing/ocr-english.yml" --env ascend-local
```

## Expected

- HTTP 200.
- Response body matches the `OcrJsonResponse` schema.
- `language` equals `"en"`.
- `filename` equals `"argent-saga-chronicles-page1.png"`.
- `pages` is non-empty.
- The concatenated text from `pages[*].lines[*].text` (case-insensitive) contains the substring `Argent Saga`, `Aenaria`, or `Halen Veyr`.
- For every `OcrTextLine`: `confidence` is a finite number in `[0.0, 1.0]`; `bounding_box` is a list of length ≥ 1
  where each element is a list of length 2 with two finite numbers.
- `processing_time_seconds` is a finite non-negative number.

## Fixtures

- [`PaddleOCR/e2e/fixtures/argent-saga-chronicles-page1.png`](../fixtures/argent-saga-chronicles-page1.png) — black `Argent Saga / Aenaria / Halen Veyr` text on
  a white background, single line, ~120 pt sans-serif font.

## Concurrency

**Engine-bound. Must run sequentially relative to other engine specs (2, 3, 4, 6).**

This spec calls `ocr_service.process_file` which invokes PaddleOCR's blocking `engine.predict` inside
`asyncio.to_thread`. PaddleOCR inference is CPU-bound; on WSL2 / Docker Desktop with 4 vCPUs allocated to the
container, a single 212 KB image takes 5–15 s. Two or more engine specs running at the same time saturate all
cores; throughput per call drops 4–8× and each `asyncio.wait_for` window (`OCR_REQUEST_TIMEOUT=300`) starts to
expire, returning `HTTP 500 INTERNAL_ERROR` instead of the expected 200.

Safe to run in parallel with: reject-fast specs that never reach the engine (specs 1, 5, 7, 8, 9, 10, 11, 12).
Unsafe to run in parallel with: any of specs 2, 3, 4, 6.

See [`PaddleOCR/e2e/testing/README.md`](README.md) "Execution order" section for the canonical fan-out shape.
