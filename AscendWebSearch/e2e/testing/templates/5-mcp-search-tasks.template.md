# MCP web_search happy path: run tasks template

Spec: [../5-mcp-search-test.md](../5-mcp-search-test.md)

Copy this file to `../runs/<UTC-timestamp>_5-mcp-search-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [ ] Bruno CLI present (`bru --version` returns a version)
- [ ] AscendWebSearch `/health` returns HTTP 200 with `{"status":"ok"}`
- [ ] SearXNG `/search?q=test&format=html` returns HTTP 200 with HTML content

### Reset state

- [ ] None required

### Run

- [ ] Step 1: `curl.exe -fsS -i -X POST http://localhost:7021/mcp ... initialize ...` returns HTTP 200 with an `Mcp-Session-Id` header; capture the UUID
- [ ] Send `mcp-search.yml` via `bru run` with `--env-var "mcp_session_id=<captured UUID>"` and wait for HTTP 200

### Expected

- [ ] Step 1: response header `Mcp-Session-Id` is a UUID
- [ ] Step 2: HTTP 200; `result.isError` is absent or `false`
- [ ] The search hits are accessible in EITHER `result.structuredContent.result` (array) OR `result.content[0].text` (JSON-parseable to an array)
- [ ] The decoded array has length in `[1, 3]`
- [ ] Every result has non-empty string `title`
- [ ] Every result has a string `url` starting with `http://` or `https://`
- [ ] Every result has a string `content` field (may be empty)

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
