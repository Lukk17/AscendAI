# MCP SSRF guard rejection: run tasks template

Spec: [../8-mcp-ssrf-rejection-test.md](../8-mcp-ssrf-rejection-test.md)

Copy this file to `../runs/<UTC-timestamp>_8-mcp-ssrf-rejection-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [ ] Bruno CLI present (`bru --version` returns a version)
- [ ] ascend-ocr `/health` returns HTTP 200 with `"status":"ok"`
- [ ] `docker exec ascend-ocr printenv MCP_ALLOWED_HOSTS` does NOT contain `169.254.169.254`

### Reset state

- [ ] None required

### Run

- [ ] Step 1: `curl -fsS -i -X POST http://localhost:7022/mcp ... initialize ...` returns HTTP 200 with an `Mcp-Session-Id` header, capture the session id (32 character hexadecimal session id without hyphens)
- [ ] Send `mcp-ssrf-link-local.yml` via `bru run` with `--env-var "mcp_session_id=<captured session id>"` and wait for HTTP 200

### Expected

- [ ] Step 1 returns HTTP 200 and the `Mcp-Session-Id` header value is non-empty
- [ ] Step 2 returns HTTP 200 carrying a JSON-RPC error envelope (`error` field present OR `result.isError` truthy)

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
