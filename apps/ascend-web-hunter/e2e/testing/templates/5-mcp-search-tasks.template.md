# MCP web_search happy path: run tasks template

Spec: [../5-mcp-search-test.md](../5-mcp-search-test.md)

Copy this file to `../runs/<UTC-timestamp>_5-mcp-search-tasks.md` before starting a run. For a repeated run of the same spec in the same sweep, which shares the sweep's timestamp, add `-rerun<N>` before `.md` (`-rerun2` for the second run, `-rerun3` for the third). Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [ ] Bruno CLI present (`bru --version` returns a version)
- [ ] ascend-web-hunter `/health` returns HTTP 200 with `status` `ok`, `service` `ascend-web-hunter` and a non-empty `version`
- [ ] SearXNG `/search?q=test&format=html` returns HTTP 200 with HTML content
- [ ] SearXNG `/search?q=OpenStreetMap&language=en-US&format=json` (the same query as the test call) prints a non-zero results count (on `0 results` mark the run BLOCKED, not FAIL)

### Reset state

- [ ] Listed the `LIMITS:LIMITER/ascend-web-hunter/*/web_search/*` rate limit key with one scan. When it printed a line, deleted that exact key with one `DEL` (`1`). When it printed no line, skipped the `DEL`

### Run

- [ ] From the repository root, `cd docs/api/request/AscendAI`
- [ ] Step 1: `curl.exe -fsS -i -X POST http://127.0.0.1:7021/mcp ... initialize ...` returns HTTP 200 with no `Mcp-Session-Id` header (service is stateless), answered as a server-sent event stream whose `data:` line holds the JSON-RPC result
- [ ] Send `mcp-search.yml` via `bru run` with `--env-var "mcp_session_id=00000000000000000000000000000000"` (any dummy value; service is stateless) and wait for HTTP 200

### Expected

- [ ] Step 1: HTTP 200 with no `Mcp-Session-Id` response header
- [ ] Step 2: HTTP 200; `result.isError` is absent or `false`
- [ ] The search hits are in `result.structuredContent.result` (array) and in the `text` of a `result.content` entry whose `type` is `text` (JSON-parseable to an array). The service answers both, the runner decodes the first one it finds
- [ ] The decoded array has length in `[1, 3]` (an empty array is a FAIL, or BLOCKED when the upstream check printed `0 results`)
- [ ] Every result has non-empty string `title`
- [ ] Every result has a string `url` starting with `http://` or `https://`
- [ ] Every result has a string `content` field (may be empty)

### Verdict

- [ ] Verdict: PASS / FAIL / BLOCKED (delete the two wrong ones)
- BLOCKED is correct only when the upstream check in Prerequisites printed `0 results` for the same query, which means upstream SearXNG itself returns nothing. The ascend-web-hunter service is not at fault. An empty list while the upstream check printed a non-zero count is a FAIL.

## Result summary



Input tokens: 0

Output tokens: 0

Start (UTC):

End (UTC):

Duration:

---

## Additional tasks I did

<!-- Optional. List anything outside the spec, e.g. diagnostic curls, manual log inspection, retries with different inputs. Leave empty if nothing extra. -->
