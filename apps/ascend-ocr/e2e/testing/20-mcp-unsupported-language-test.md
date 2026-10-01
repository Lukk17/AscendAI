# MCP unsupported language rejection: e2e test

## What this verifies

- `ocr_submit` with a well-formed `http://` URI but `lang` `korean`, a language the service no longer reads, is
  refused with `UNSUPPORTED_LANGUAGE`.
- The refusal names the languages the service does read (`Supported languages:`) and never echoes the caller's
  language.
- The language is checked before the URI is fetched: the answer carries no `DOWNLOAD_FAILED`, even though the
  fixture does not need to be in the bucket.
- No identifier is issued, and nothing is queued: the job listing is empty afterwards.

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

Check nothing is in flight, because step 3 asserts an empty listing.

```bash
curl -fsS http://localhost:7022/ready
```

Expect `"jobs_queued":0` and `"jobs_running":0`. Anything else means an earlier run left work behind: wait for it to
finish or reset per [`../README.md`](../README.md) "Resetting between runs" before starting.

## Reset state

None. The language is refused before any fetch, so nothing reaches the queue, the jobs directory or the bucket.

## Run

Step 1. Open an MCP session and keep the session id. FastMCP answers the `initialize` call with an `Mcp-Session-Id`
response header, and every `tools/call` in this spec carries it back.

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

Step 2. Submit an object-store URL with `lang` set to `korean`.

```bash
bru run "ocr/testing/mcp-unsupported-language.yml" --env ascend-local --env-var "mcp_session_id=<paste session id>"
```

Step 3. Read the listing.

```bash
bru run "ocr/testing/ocr-jobs-list-empty.yml" --env ascend-local
```

## Expected

Step 2:

- HTTP 200 at the transport, with a JSON-RPC error frame or an `isError` result.
- The message carries `UNSUPPORTED_LANGUAGE` and `Supported languages:`. The full list is not asserted, so adding a
  language later does not break this step.
- The message does not carry `DOWNLOAD_FAILED`, which proves the URI was never fetched, and does not carry `korean`.
- No `job_id` anywhere in the answer.

Step 3:

- HTTP 200 with `{"jobs": []}`.

## Fixtures

None. The URI names `argent-saga-chronicles-page1.png` in the `e2e-fixtures` bucket, but it is never fetched.

## Concurrency

Reject-fast. The submission is refused at the request boundary before anything is queued, so this spec never reaches
the OCR engine and finishes in well under two seconds. Safe to run in parallel with the other reject-fast specs, up
to the runner's default cap of five concurrent. Never alongside an engine-bound spec
(2, 3, 4, 6, 13, 14, 15, 16, 17, 18, 19).
