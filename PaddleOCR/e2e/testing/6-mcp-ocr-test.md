# MCP ocr_process happy path: e2e test

## What this verifies

- `tools/call` for `name="ocr_process"` with arguments `{"file_uri": "<minio-url>", "lang": "en"}` returns HTTP 200
  and a JSON-RPC `result` whose content is the serialised `OcrJsonResponse`.
- `file_uri` is fetched by PaddleOCR over HTTP — the runner uploads the fixture to MinIO under a dedicated
  `e2e-fixtures` bucket, and PaddleOCR resolves the docker-internal hostname `minio:9000` to download it. The MCP
  tool does **not** assume any host-side mount; the fixture flows over the same wire any real client would use.
- `language` echoes back `"en"`.
- The concatenated `pages[*].lines[*].text` (case-insensitive) contains the canary substring `Argent Saga`,
  `Aenaria`, or `Halen Veyr`.
- This is the MCP-transport mirror of test 2 — the assertion content is the same; the only difference is that
  the fixture reaches the OCR engine via the MCP tool's URL argument rather than via a multipart upload.

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

Check the English canary fixture exists on the host.

```powershell
Test-Path PaddleOCR/e2e/fixtures/argent-saga-chronicles-page1.png
```

Expect `True`.

Check MinIO is reachable on the host.

```powershell
curl -fsS http://localhost:9070/minio/health/live
```

Expect HTTP 200.

Check the MinIO `mc` client is available inside the `minio` container (it ships with the image).

```powershell
docker exec minio mc --version
```

Expect a version string.

Check the PaddleOCR container has `MCP_ALLOWED_HOSTS` including `host.docker.internal`. The MCP tool's SSRF guard blocks RFC1918 destinations by default; the docker-internal `host.docker.internal` host-gateway resolves to a private IP and must be explicitly allowlisted. See [ADR-001](../../docs/architecture/decisions/ADR-001-mcp-file-transport-uri-only.md) for the policy.

```powershell
docker exec ascend-paddle-ocr printenv MCP_ALLOWED_HOSTS
```

Expect `host.docker.internal,localhost,127.0.0.1` (or any superset containing `host.docker.internal`). If empty, set the env var in `docker-compose.yaml` under the `ascend-paddle-ocr` service and recreate the container.

## Reset state

Register the MinIO alias inside the `minio` container (idempotent). Credentials are the single source of truth in
`docker-compose.yaml` under the `minio` service env (`MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD`). The command below
runs through `sh -c` so the env vars expand *inside* the container.

```powershell
docker exec minio sh -c 'mc alias set local http://localhost:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD"'
```

Create the dedicated `e2e-fixtures` bucket (idempotent — `mc mb` with `--ignore-existing` is a no-op when the bucket
already exists).

```powershell
docker exec minio mc mb --ignore-existing local/e2e-fixtures
```

Open the bucket for anonymous downloads so PaddleOCR can fetch the URL without an auth header.

```powershell
docker exec minio mc anonymous set download local/e2e-fixtures
```

Drop only this test's fixture from MinIO so re-upload is clean.

```powershell
docker exec minio mc rm --force local/e2e-fixtures/argent-saga-chronicles-page1.png
```

Copy the fixture from the host into the `minio` container.

```powershell
docker cp PaddleOCR/e2e/fixtures/argent-saga-chronicles-page1.png minio:/tmp/argent-saga-chronicles-page1.png
```

Upload the fixture into the bucket.

```powershell
docker exec minio mc cp /tmp/argent-saga-chronicles-page1.png local/e2e-fixtures/argent-saga-chronicles-page1.png
```

Verify the object lands in the bucket.

```powershell
docker exec minio mc ls local/e2e-fixtures/argent-saga-chronicles-page1.png
```

Expect a single-line listing showing the object name.

## Run

```powershell
cd docs/api/request/AscendAI
```

**Step 1.** Open an MCP session via the `initialize` handshake. Capture the `Mcp-Session-Id` value from the response headers.

```powershell
curl.exe -fsS -i -X POST http://localhost:7022/mcp/ -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"initialize\",\"params\":{\"protocolVersion\":\"2025-11-25\",\"capabilities\":{},\"clientInfo\":{\"name\":\"e2e\",\"version\":\"0.1.0\"}}}"
```

Look for `Mcp-Session-Id: <uuid>` in the response. Use that UUID as the value of the `mcp_session_id` env-var in the next step.

**Step 2.** Send the `tools/call` with the captured session ID injected:

```powershell
bru run "paddle-ocr/testing/mcp-ocr.yml" --env ascend-local --env-var "mcp_session_id=<paste UUID from step 1>"
```

## Expected

- HTTP 200.
- The JSON-RPC `result.content` array carries a serialised `OcrJsonResponse` whose deserialised shape matches the
  REST endpoint's response model.
- `language` equals `"en"`.
- `filename` equals `"argent-saga-chronicles-page1.png"`.
- `pages` is non-empty.
- The concatenated text from `pages[*].lines[*].text` (case-insensitive) contains the substring `Argent Saga`,
  `Aenaria`, or `Halen Veyr`.
- `processing_time_seconds` is a finite non-negative number.

## Fixtures

- [`PaddleOCR/e2e/fixtures/argent-saga-chronicles-page1.png`](../fixtures/argent-saga-chronicles-page1.png) — same
  fixture as tests 2 and 4, served to PaddleOCR over HTTP from MinIO at
  `http://host.docker.internal:9070/e2e-fixtures/argent-saga-chronicles-page1.png`.

## Concurrency

**Engine-bound. Must run sequentially relative to other engine specs (2, 3, 4, 6).**

The MCP path mirrors the REST path once the URL is resolved: `ocr_service.process_file` invokes PaddleOCR's
blocking `engine.predict` inside `asyncio.to_thread`. CPU contention with another engine spec running at the same
moment exhausts `OCR_REQUEST_TIMEOUT=300` and the JSON-RPC envelope returns `result.isError=true` instead of the
expected `result.content[0]` payload.

Safe to run in parallel with reject-fast specs (1, 5, 7, 8, 9, 10, 11, 12). Unsafe with 2, 3, 4, 6.

- **Mutates:** MinIO bucket `e2e-fixtures` (object key `argent-saga-chronicles-page1.png`); MinIO anonymous-download
  policy on the `e2e-fixtures` bucket.
- **Conflicts with:** any future test that also writes `e2e-fixtures/argent-saga-chronicles-page1.png` — none
  currently exist.

See [`PaddleOCR/e2e/testing/README.md`](README.md) "Execution order".
