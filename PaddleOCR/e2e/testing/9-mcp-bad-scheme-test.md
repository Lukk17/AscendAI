# MCP unsupported scheme rejection: e2e test

## What this verifies

The MCP tool's scheme dispatch (`src/api/mcp/mcp_server.py:_fetch_file`) raises `UnsafeUriError` for any scheme
other than `http`, `https`, or `file` — including `ftp://`, `data:`, `gopher://`.

## Prerequisites

```powershell
bru --version
```

```powershell
curl -fsS http://localhost:7022/health
```

## Reset state

None.

## Run

Open MCP session per spec 8, then:

```powershell
bru run "paddle-ocr/testing/mcp-bad-scheme.yml" --env ascend-local --env-var "mcp_session_id=<paste UUID>"
```

## Expected

- HTTP 200 carrying a JSON-RPC error envelope referencing `UNSAFE_URI` semantics.
