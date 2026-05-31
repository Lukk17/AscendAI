# OCR default-language fallback: e2e test

## What this verifies

- `POST /v1/ocr` with the `argent-saga-chronicles-page1.png` fixture and **no** `lang` form field falls back to the server's
  `DEFAULT_LANGUAGE` setting (`"en"` out of the box per `src/config/config.py`).
- The response body's `language` field equals `"en"` — proof the server-side fallback fired, not the client.
- The concatenated `pages[*].lines[*].text` (case-insensitive) contains the canary substring `Argent Saga`, `Aenaria`, or `Halen Veyr`.
- The default-language path is functionally equivalent to the explicit `lang=en` path: both produce a populated
  `pages` array with the same canary substring.

This spec assumes the server is running with `DEFAULT_LANGUAGE=en` (the shipped default). If the deployment overrides
`DEFAULT_LANGUAGE` to a non-English value, this spec's assertion on `language="en"` is the wrong assertion to run;
update the spec to match the deployment's default before the run.

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

Expect `True`.

Check the running container's `DEFAULT_LANGUAGE` is `en` (the documented default). If unsure, inspect the container
environment.

```powershell
docker inspect paddle-ocr --format "{{range .Config.Env}}{{println .}}{{end}}"
```

Look for `DEFAULT_LANGUAGE=en` or its absence (absence means the in-code default of `en` applies).

## Reset state

None.

## Run

Single Bruno request.

```powershell
cd docs/api/request/AscendAI
```

```powershell
bru run "paddle-ocr/testing/ocr-default-lang.yml" --env ascend-local
```

## Expected

- HTTP 200.
- Response body matches the `OcrJsonResponse` schema.
- `language` equals `"en"` (the server's `DEFAULT_LANGUAGE`).
- `filename` equals `"argent-saga-chronicles-page1.png"`.
- `pages` is non-empty.
- The concatenated `pages[*].lines[*].text` (case-insensitive) contains the substring `Argent Saga`, `Aenaria`, or `Halen Veyr`.
- `processing_time_seconds` is a finite non-negative number.

## Fixtures

- [`PaddleOCR/e2e/fixtures/argent-saga-chronicles-page1.png`](../fixtures/argent-saga-chronicles-page1.png) — same fixture as test 2.
