# MCP tools list: e2e test

## What this verifies

- `tools/list` over the MCP transport advertises exactly the four job tools: `ocr_submit`, `ocr_job_status`,
  `ocr_list_jobs` and `ocr_cancel_job`.
- `ocr_submit` declares `file_uri` (required) and `lang` (optional), plus `quality` (`normal` or `high`, default
  `high`) and `straighten` (boolean, default `false`), so a model offered the tool can ask for either mode and for
  straightening.
- `ocr_job_status` and `ocr_cancel_job` each declare `job_id`.
- The removed synchronous tool is not advertised under any name. A tool catalogue is discovered on every connection,
  so a removed tool is a tool the model stops being offered, and nothing should be offering it.

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

## Reset state

None. `tools/list` reads the catalogue and touches neither the queue nor the bucket.

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

```bash
bru run "ocr/testing/mcp-list-tools.yml" --env ascend-local --env-var "mcp_session_id=<paste session id>"
```

## Expected

- HTTP 200.
- The JSON-RPC result's `tools` array holds exactly four tools: `ocr_submit`, `ocr_job_status`, `ocr_list_jobs` and
  `ocr_cancel_job`, and nothing else.
- `ocr_submit`'s input schema has `file_uri` and `lang` properties.
- `ocr_submit`'s input schema has a `quality` property of type string with `enum` exactly `normal` and `high` and
  `default` `high`.
- `ocr_submit`'s input schema has a `straighten` property of type boolean with `default` `false`.
- `ocr_job_status` and `ocr_cancel_job` each have a `job_id` property.
- No advertised tool is named `ocr_process`, and no advertised tool name contains `process` at all.

## Fixtures

None.

## Concurrency

Reject-fast. `tools/list` reads the catalogue and submits nothing, so this spec never reaches the OCR engine and finishes in well under two seconds. Safe to run in parallel with the other reject-fast specs, up
to the runner's default cap of five concurrent. Never alongside an engine-bound spec
(2, 3, 4, 6, 13, 14, 15, 16, 17, 18, 19).
