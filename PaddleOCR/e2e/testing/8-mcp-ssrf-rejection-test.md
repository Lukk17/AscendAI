# MCP SSRF guard rejection: e2e test

## What this verifies

The MCP SSRF guard (`src/api/mcp/mcp_server.py:_validate_host`) rejects URIs whose resolved IP falls into the
private / loopback / link-local / multicast / reserved / unspecified blocks, **unless** the hostname is on
`MCP_ALLOWED_HOSTS`.

This spec drives the link-local IMDS case (`169.254.169.254`). The guard must refuse without any outbound
connection attempt; verifiable via dropping `MCP_ALLOWED_HOSTS` to a value not containing the test target.

## Prerequisites

```powershell
bru --version
```

```powershell
curl -fsS http://localhost:7022/health
```

Check that `169.254.169.254` is NOT in `MCP_ALLOWED_HOSTS`.

```powershell
docker exec ascend-paddle-ocr printenv MCP_ALLOWED_HOSTS
```

Expect the value not to contain `169.254.169.254`.

## Reset state

None.

## Run

**Step 1.** Open an MCP session via `initialize`; capture `Mcp-Session-Id`.

```powershell
curl.exe -fsS -i -X POST http://localhost:7022/mcp/ -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"initialize\",\"params\":{\"protocolVersion\":\"2025-11-25\",\"capabilities\":{},\"clientInfo\":{\"name\":\"e2e\",\"version\":\"0.1.0\"}}}"
```

**Step 2.** Send the SSRF probe with the captured session ID.

```powershell
bru run "paddle-ocr/testing/mcp-ssrf-link-local.yml" --env ascend-local --env-var "mcp_session_id=<paste UUID>"
```

## Expected

- Step 1 returns HTTP 200 with an `Mcp-Session-Id` header.
- Step 2 returns HTTP 200 carrying a JSON-RPC error envelope (`error` field present OR `result.isError` truthy).
- No outbound network call to `169.254.169.254` (verifiable by host firewall / docker network policy if installed).
