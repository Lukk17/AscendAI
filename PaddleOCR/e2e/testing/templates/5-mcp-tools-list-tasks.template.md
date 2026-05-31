# MCP tools/list contract: run tasks template

Spec: [../5-mcp-tools-list-test.md](../5-mcp-tools-list-test.md)

Copy this file to `../runs/<UTC-timestamp>_5-mcp-tools-list-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [ ] Bruno CLI present (`bru --version` returns a version)
- [ ] PaddleOCR `/health` returns HTTP 200 with `"status":"ok"`

### Reset state

- [ ] None required

### Run

- [ ] Step 1: `curl.exe -fsS -i -X POST http://localhost:7022/mcp/ ... initialize ...` returns HTTP 200 with an `Mcp-Session-Id` header; capture the UUID
- [ ] Send `mcp-list-tools.yml` via `bru run` with `--env-var "mcp_session_id=<captured UUID>"` and wait for HTTP 200

### Expected

- [ ] `initialize` returns HTTP 200 with a non-empty `Mcp-Session-Id` header
- [ ] `mcp-list-tools.yml` returns HTTP 200
- [ ] `result.tools` array contains an entry with `name="ocr_process"`
- [ ] That entry's `inputSchema.properties` includes a key `file_path` and a key `lang`
- [ ] That entry's `inputSchema.required` array contains `"file_path"`

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
