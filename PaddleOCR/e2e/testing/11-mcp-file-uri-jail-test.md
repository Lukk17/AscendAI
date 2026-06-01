# MCP `file://` jail rejection: e2e test

## What this verifies

`file://` URIs are rejected when `MCP_FILE_URI_ROOT` is unset (default secure posture). Validates the path
traversal Critical from the security audit.

## Prerequisites

```powershell
bru --version
```

```powershell
curl -fsS http://localhost:7022/health
```

Check that `MCP_FILE_URI_ROOT` is unset.

```powershell
docker exec ascend-paddle-ocr printenv MCP_FILE_URI_ROOT
```

Expect empty output (env var unset). If set, this spec instead drives the second case below.

## Reset state

None.

## Run

Open MCP session per spec 8, then:

```powershell
bru run "paddle-ocr/testing/mcp-file-uri-disabled.yml" --env ascend-local --env-var "mcp_session_id=<paste UUID>"
```

## Expected

- HTTP 200 carrying a JSON-RPC error envelope referencing `UNSAFE_URI`.
- PaddleOCR did NOT open `/etc/passwd` (verifiable via process audit if `auditd` is configured).

## Optional second case — root configured

When `MCP_FILE_URI_ROOT=/var/lib/paddle-ocr/uploads` is set, attempt
`file:///var/lib/paddle-ocr/uploads/../../etc/passwd`. The jail rejects with the same `UNSAFE_URI` code via the
`realpath` escape check.
