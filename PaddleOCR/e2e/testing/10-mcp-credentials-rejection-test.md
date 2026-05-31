# MCP credentials-in-URI rejection: e2e test

## What this verifies

The MCP tool rejects URIs containing `userinfo` (e.g. `http://user:pass@host/...`) before any DNS lookup or
HTTP fetch — closes the credential-leakage class flagged in the security audit.

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
bru run "paddle-ocr/testing/mcp-credentials-in-uri.yml" --env ascend-local --env-var "mcp_session_id=<paste UUID>"
```

## Expected

- HTTP 200 carrying a JSON-RPC error envelope referencing `UNSAFE_URI`.
- PaddleOCR logs (`docker logs ascend-paddle-ocr`) do NOT contain `user:pass`.
