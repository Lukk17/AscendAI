# REST OCR unsupported MIME rejection: e2e test

## What this verifies

`POST /v1/ocr` rejects payloads whose magic bytes do not match the allowed image / PDF signatures, even when the
client lies about `Content-Type`. The `src/api/mime_sniffer.py` module performs byte-level inspection rather than
trusting headers.

## Prerequisites

```powershell
bru --version
```

```powershell
curl -fsS http://localhost:7022/health
```

```powershell
Test-Path PaddleOCR/e2e/fixtures/not-an-image.txt
```

Expect `True`.

## Reset state

None.

## Run

```powershell
cd docs/api/request/AscendAI
```

```powershell
bru run "paddle-ocr/testing/ocr-unsupported-mime.yml" --env ascend-local
```

## Expected

- HTTP 400.
- Body `code` equals `UNSUPPORTED_FILE_TYPE`.
- Body `detail` equals `Unsupported file type` (generic, no upstream leak).
