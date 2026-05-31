# MCP ocr_process happy path: e2e test

## What this verifies

- `tools/call` for `name="ocr_process"` with arguments `{"file_path": "<container-path>", "lang": "en"}` returns
  HTTP 200 and a JSON-RPC `result` whose content is the serialised `OcrJsonResponse`.
- `file_path` is interpreted **inside the container**: the runner must mount `PaddleOCR/e2e/fixtures/` into the
  container at a known path and pass that container-side path as the argument. The MCP tool short-circuits with
  `FileNotFoundError` otherwise.
- `language` echoes back `"en"`.
- The concatenated `pages[*].lines[*].text` (case-insensitive) contains the canary substring `Argent Saga`, `Aenaria`, or `Halen Veyr`.
- This is the MCP-transport mirror of test 2 — the assertion content is the same; the only difference is that the
  fixture reaches the OCR engine via the MCP tool's file-path argument rather than via a multipart upload.

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

Check the fixtures directory is mounted into the container at `/e2e-fixtures/`. The Bruno request's `file_path`
argument is hard-coded to `/e2e-fixtures/argent-saga-chronicles-page1.png`; if the deployment mounts the directory elsewhere, edit
the request before running.

```powershell
docker exec paddle-ocr test -f /e2e-fixtures/argent-saga-chronicles-page1.png
```

Expect exit code `0`. If the file is missing inside the container, add a `volumes:` entry to the PaddleOCR service in
`docker-compose.yaml` mapping `./PaddleOCR/e2e/fixtures:/e2e-fixtures:ro` and recreate the container.

## Reset state

None.

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
- The concatenated text from `pages[*].lines[*].text` (case-insensitive) contains the substring `Argent Saga`, `Aenaria`, or `Halen Veyr`.
- `processing_time_seconds` is a finite non-negative number.

## Fixtures

- [`PaddleOCR/e2e/fixtures/argent-saga-chronicles-page1.png`](../fixtures/argent-saga-chronicles-page1.png) — same fixture as tests 2 and 4,
  reached via container path `/e2e-fixtures/argent-saga-chronicles-page1.png`.
