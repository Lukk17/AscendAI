# MCP tools/list contract: run tasks template

Spec: [../4-mcp-tools-list-test.md](../4-mcp-tools-list-test.md)

Copy this file to `../runs/<UTC-timestamp>_4-mcp-tools-list-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [ ] Bruno CLI present (`bru --version` returns a version)
- [ ] AscendWebSearch `/health` returns HTTP 200 with `{"status":"ok"}`

### Reset state

- [ ] None required

### Run

- [ ] Step 1: `curl.exe -fsS -i -X POST http://localhost:7021/mcp ... initialize ...` returns HTTP 200 with an `Mcp-Session-Id` header; capture the UUID
- [ ] Send `mcp-list-tools.yml` via `bru run` with `--env-var "mcp_session_id=<captured UUID>"` and wait for HTTP 200

### Expected

- [ ] Step 1: response header `Mcp-Session-Id` is a UUID
- [ ] Step 2: HTTP 200; `result.tools` is a non-empty array
- [ ] Some entry has `name="web_search"` with `inputSchema.required` containing `"query"` and `properties` advertising `query` and `limit`
- [ ] Some entry has `name="web_read"` with `inputSchema.required` containing `"url"` and `properties` advertising `url` plus at least one of `include_links` / `link_filter` / `heavy_mode`

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
