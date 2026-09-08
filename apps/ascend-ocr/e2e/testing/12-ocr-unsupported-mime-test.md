# REST OCR unsupported MIME rejection: e2e test

## What this verifies

`POST /v1/ocr` rejects payloads whose magic bytes do not match the allowed image / PDF signatures, even when the
client lies about `Content-Type`. The `src/api/mime_sniffer.py` module performs byte-level inspection rather than
trusting headers.

## Prerequisites

```bash
bru --version
```

```bash
curl -fsS http://localhost:7022/health
```

```bash
ls apps/ascend-ocr/e2e/fixtures/not-an-image.txt
```

Expect `True`.

## Reset state

None.

## Run

```bash
cd docs/api/request/AscendAI
```

```bash
bru run "ocr/testing/ocr-unsupported-mime.yml" --env ascend-local
```

## Expected

- HTTP 400.
- Body `code` equals `UNSUPPORTED_FILE_TYPE`.
- Body `detail` equals `Unsupported file type` (generic, no upstream leak).
