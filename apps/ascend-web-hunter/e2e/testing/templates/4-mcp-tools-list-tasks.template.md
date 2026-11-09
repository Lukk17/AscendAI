# MCP tools/list contract: run tasks template

Spec: [../4-mcp-tools-list-test.md](../4-mcp-tools-list-test.md)

Copy this file to `../runs/<UTC-timestamp>_4-mcp-tools-list-tasks.md` before starting a run. For a repeated run of the same spec in the same sweep, which shares the sweep's timestamp, add `-rerun<N>` before `.md` (`-rerun2` for the second run, `-rerun3` for the third). Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [ ] Bruno CLI present (`bru --version` returns a version)
- [ ] ascend-web-hunter `/health` returns HTTP 200 with `status` `ok`, `service` `ascend-web-hunter` and a non-empty `version`

### Reset state

- [ ] None required

### Run

- [ ] Step 1: `curl.exe -fsS -i -X POST http://127.0.0.1:7021/mcp ... initialize ...` returns HTTP 200 with no `Mcp-Session-Id` header (service is stateless)
- [ ] Send `mcp-list-tools.yml` via `bru run` with `--env-var "mcp_session_id=00000000000000000000000000000000"` (any dummy value; service is stateless) and wait for HTTP 200

### Expected

- [ ] Step 1: HTTP 200 with no `Mcp-Session-Id` response header
- [ ] Step 2: HTTP 200; `result.tools` is a non-empty array
- [ ] Some entry has `name="web_search"` with `inputSchema.required` containing `"query"` and `properties` advertising `query` and `limit`
- [ ] Some entry has `name="web_read"` with `inputSchema.required` containing `"url"` and `properties` advertising `url`, `include_links`, `link_filter` and `heavy_mode`

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
