# MCP bad scheme rejection: e2e test

## What this verifies

- `ocr_submit` refuses any scheme other than `http`, `https` or `file`, including `ftp://`, `data:` and bare
  Windows paths.
- The refusal carries the `UNSAFE_URI` code.
- No identifier is issued, and nothing is queued.

## Prerequisites

Check Bruno CLI is installed.

```bash
bru --version
```

Expect a version string.

Check the ascend-ocr server is reachable.

```bash
curl -fsS http://localhost:7022/health
```

Expect HTTP 200 with `"status":"ok"` in the body.

Check nothing is in flight, because step 4 asserts an empty listing.

```bash
curl -fsS http://localhost:7022/ready
```

Expect `"jobs_queued":0` and `"jobs_running":0`. Anything else means an earlier run left work behind: wait for it to
finish or reset per [`../README.md`](../README.md) "Resetting between runs" before starting.

## Reset state

None. The guard refuses the submission before any fetch, so nothing reaches the queue, the jobs directory or the
bucket.

## Run

Open an MCP session and keep the session id. FastMCP answers the `initialize` call with an
`Mcp-Session-Id` response header, and every `tools/call` in this spec carries it back.

```bash
curl -isS -X POST http://localhost:7022/mcp -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" -d "{\"jsonrpc\":\"2.0\",\"id\":0,\"method\":\"initialize\",\"params\":{\"protocolVersion\":\"2025-06-18\",\"capabilities\":{},\"clientInfo\":{\"name\":\"e2e\",\"version\":\"1\"}}}"
```

Expect HTTP 200 and an `mcp-session-id` response header. Use that value as the `mcp_session_id` env-var below.

```bash
cd docs/api/request/AscendAI
```

Complete the handshake. The MCP protocol requires the client to send the `notifications/initialized` notification
after `initialize` and before any other request on the session.

```bash
bru run "ocr/testing/mcp-initialized.yml" --env ascend-local --env-var "mcp_session_id=<paste session id>"
```

Expect HTTP 202 with an empty body.

Step 1. Submit an `ftp://` URI.

```bash
bru run "ocr/testing/mcp-bad-scheme.yml" --env ascend-local --env-var "mcp_session_id=<paste session id>"
```

Step 2. Submit a `data:` URI carrying a one pixel PNG inline.

```bash
bru run "ocr/testing/mcp-bad-scheme-data.yml" --env ascend-local --env-var "mcp_session_id=<paste session id>"
```

Step 3. Submit a bare Windows path, `C:\Users\Public\scan.png`, which a URI parser reads as the scheme `c`.

```bash
bru run "ocr/testing/mcp-bad-scheme-windows-path.yml" --env ascend-local --env-var "mcp_session_id=<paste session id>"
```

Step 4. Read the listing.

```bash
bru run "ocr/testing/ocr-jobs-list-empty.yml" --env ascend-local
```

## Expected

Steps 1 to 3:

- HTTP 200 at the transport, with a JSON-RPC error frame or an `isError` result.
- The message carries `UNSAFE_URI`.
- No `job_id` anywhere in the answer.

Step 1:

- The message carries `Unsupported URI scheme: 'ftp'`.

Step 2:

- The message carries `Unsupported URI scheme: 'data'`.

Step 3:

- The message carries `Unsupported URI scheme: 'c'`.

Step 4:

- HTTP 200 with `{"jobs": []}`. None of the three refused submissions was queued.

## Fixtures

None.

## Concurrency

Reject-fast. The submission is refused at the request boundary before anything is queued, so this spec never reaches
the OCR engine and finishes in well under two seconds. Safe to run in parallel with the other reject-fast specs, up
to the runner's default cap of five concurrent. Never alongside an engine-bound spec
(2, 3, 4, 6, 13, 14, 15, 16, 17, 18, 19).
