# MCP `file://` jail rejection: run tasks template

Spec: [../11-mcp-file-uri-jail-test.md](../11-mcp-file-uri-jail-test.md)

Copy this file to `../runs/<UTC-timestamp>_11-mcp-file-uri-jail-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [ ] Bruno CLI present (`bru --version` returns a version)
- [ ] PaddleOCR `/health` returns HTTP 200 with `"status":"ok"`
- [ ] `docker exec ascend-paddle-ocr printenv MCP_FILE_URI_ROOT` returns empty output (env var unset)

### Reset state

- [ ] None required

### Run

- [ ] Step 1: `curl.exe -fsS -i -X POST http://localhost:7022/mcp/ ... initialize ...` returns HTTP 200 with an `Mcp-Session-Id` header; capture the UUID
- [ ] Send `mcp-file-uri-disabled.yml` via `bru run` with `--env-var "mcp_session_id=<captured UUID>"` and wait for HTTP 200

### Expected

- [ ] Step 1 returns HTTP 200 and the `Mcp-Session-Id` header value is non-empty
- [ ] Step 2 returns HTTP 200 carrying a JSON-RPC error envelope referencing `UNSAFE_URI` (file:// disabled when root unset)
- [ ] PaddleOCR did NOT open `/etc/passwd` (verifiable via process audit if `auditd` is configured)

### Verdict

- [ ] Verdict: PASS / FAIL (delete the wrong one)

## Result summary



Input tokens: 0

Output tokens: 0

Start (UTC):

End (UTC):

Duration:

---

## Additional tasks I did

<!-- Optional. List anything outside the spec, e.g. diagnostic curls, manual log inspection, retries with different inputs. Leave empty if nothing extra. -->
