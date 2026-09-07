# MCP ocr_process happy path: e2e test

## What this verifies

- `tools/call` for `name="ocr_process"` with arguments `{"file_uri": "<object-store-url>", "lang": "en"}` returns
  HTTP 200 and a JSON-RPC `result` whose content is the serialised `OcrJsonResponse`.
- `file_uri` is fetched by ascend-ocr over HTTP. The runner uploads the fixture into the dedicated `e2e-fixtures`
  bucket on the object store, and ascend-ocr reaches back out to the host-published endpoint at
  `host.docker.internal:9070` to download it. The MCP tool does **not** assume any host-side mount; the fixture flows
  over the same wire any real client would use.
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

Check the ascend-ocr server is reachable.

```powershell
curl -fsS http://localhost:7022/health
```

Expect HTTP 200 with `"status":"ok"` in the body.

Check the English canary fixture exists on the host.

```powershell
Test-Path apps/ascend-ocr/e2e/fixtures/argent-saga-chronicles-page1.png
```

Expect `True`.

Check the object store is reachable on the host. It serves the S3 API on port 9070 without authentication, so
this spec needs no client, no credentials, and no container name.

```powershell
curl.exe -fsS http://localhost:9070/_floci/health
```

Expect HTTP 200 with `"s3":"running"` in the JSON body.

Check the ascend-ocr container has `MCP_ALLOWED_HOSTS` including `host.docker.internal`. The MCP tool's SSRF guard blocks RFC1918 destinations by default; the docker-internal `host.docker.internal` host-gateway resolves to a private IP and must be explicitly allowlisted. See [ADR-001](../../docs/architecture/decisions/ADR-001-mcp-file-transport-uri-only.md) for the policy.

```powershell
docker exec ascend-ocr printenv MCP_ALLOWED_HOSTS
```

Expect `host.docker.internal,localhost,127.0.0.1` (or any superset containing `host.docker.internal`). If empty, set the env var in `docker-compose.yaml` under the `ascend-ocr` service and recreate the container.

## Reset state

Every command below names the `e2e-fixtures` bucket literally. That bucket belongs to this repository. Never issue a
command that sweeps buckets instead of naming one, because the same object store also backs other projects on this
machine.

Create the dedicated `e2e-fixtures` bucket. The call is idempotent: an existing bucket answers HTTP 200 exactly like a
freshly created one.

```powershell
curl.exe -sS -o NUL -w "%{http_code}\n" -X PUT "http://localhost:9070/e2e-fixtures"
```

Expect `200`.

Drop only this test's fixture so the re-upload is clean. A key that is already gone also returns HTTP 204, so the step
is safe to re-run.

```powershell
curl.exe -fsS -X DELETE "http://localhost:9070/e2e-fixtures/argent-saga-chronicles-page1.png"
```

Upload the fixture straight from the host. No client and no intermediate container copy: the S3 endpoint takes the
bytes on a plain `PUT`.

```powershell
curl.exe -sS -o NUL -w "%{http_code}\n" -X PUT -H "Content-Type: image/png" --data-binary "@apps/ascend-ocr/e2e/fixtures/argent-saga-chronicles-page1.png" "http://localhost:9070/e2e-fixtures/argent-saga-chronicles-page1.png"
```

Expect `200`.

Verify the object lands in the bucket.

```powershell
curl.exe -fsS "http://localhost:9070/e2e-fixtures?list-type=2&prefix=argent-saga"
```

Expect a `ListBucketResult` carrying `<Key>argent-saga-chronicles-page1.png</Key>` with a `<Size>` of `212563`.

## Run

```powershell
cd docs/api/request/AscendAI
```

**Step 1.** Open an MCP session via the `initialize` handshake. Capture the `Mcp-Session-Id` value from the response headers.

```powershell
curl.exe -fsS -i -X POST http://localhost:7022/mcp -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"initialize\",\"params\":{\"protocolVersion\":\"2025-11-25\",\"capabilities\":{},\"clientInfo\":{\"name\":\"e2e\",\"version\":\"0.1.0\"}}}"
```

Look for `Mcp-Session-Id: <uuid>` in the response. Use that UUID as the value of the `mcp_session_id` env-var in the next step.

**Step 2.** Send the `tools/call` with the captured session ID injected:

```powershell
bru run "ocr/testing/mcp-ocr.yml" --env ascend-local --env-var "mcp_session_id=<paste UUID from step 1>"
```

## Post-run cleanup

Drop the fixture this spec uploaded, so the bucket is left exactly as the spec found it. Run it regardless of whether
the Run step passed or failed. The command names the `e2e-fixtures` bucket literally and one key, and a key that is
already gone also returns HTTP 204, so the step is safe to re-run.

```powershell
curl.exe -fsS -X DELETE "http://localhost:9070/e2e-fixtures/argent-saga-chronicles-page1.png"
```

Leave the bucket itself in place. This spec creates it only if absent, and other specs seed their own fixtures into
it, so deleting the bucket would break them.

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

- [`apps/ascend-ocr/e2e/fixtures/argent-saga-chronicles-page1.png`](../fixtures/argent-saga-chronicles-page1.png) — same
  fixture as tests 2 and 4, served to ascend-ocr over HTTP from the object store at
  `http://host.docker.internal:9070/e2e-fixtures/argent-saga-chronicles-page1.png`.

## Concurrency

**Engine-bound. Must run sequentially relative to other engine specs (2, 3, 4, 6).**

The MCP path mirrors the REST path once the URL is resolved: `ocr_service.process_file` invokes PaddleOCR's
blocking `engine.predict` inside the OCR worker process. CPU contention with another engine spec running at the same
moment exhausts `OCR_REQUEST_TIMEOUT=300` and the JSON-RPC envelope returns `result.isError=true` instead of the
expected `result.content[0]` payload.

Safe to run in parallel with reject-fast specs (1, 5, 7, 8, 9, 10, 11, 12). Unsafe with 2, 3, 4, 6.

- **Mutates:** object-store bucket `e2e-fixtures` (object key `argent-saga-chronicles-page1.png`). `Reset state`
  uploads that key and `Post-run cleanup` deletes it again, so the spec leaves no object behind. The bucket itself is
  created if absent and is never deleted, because other specs seed their own fixtures into it.
- **Conflicts with:** any future test that also writes `e2e-fixtures/argent-saga-chronicles-page1.png` — none
  currently exist.

See [`apps/ascend-ocr/e2e/testing/README.md`](README.md) "Execution order".
