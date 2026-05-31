# MCP insert and search round-trip: run tasks template

Spec: [../5-mcp-insert-and-search-test.md](../5-mcp-insert-and-search-test.md)

Copy this file to `../runs/<UTC-timestamp>_5-mcp-insert-and-search-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [ ] Bruno CLI present (`bru --version` returns a version)
- [ ] AscendMemory `/health` returns HTTP 200 with `{"status":"ok"}`
- [ ] Qdrant `:6333/readyz` returns HTTP 200

### Reset state

- [ ] `POST /api/v1/memory/wipe?user_id=frostyMemoryMcpInsertSearchTest` returns HTTP 200 with `{"status":"success", ...}`

### Run

- [ ] Step 1: `curl.exe -fsS -i -X POST http://localhost:7020/mcp ... initialize ...` returns HTTP 200 with an `Mcp-Session-Id` header; capture the UUID
- [ ] Send `mcp-insert.yml` via `bru run` with `--env-var "mcp_session_id=<captured UUID>"` and wait for HTTP 200
- [ ] Send `mcp-search.yml` via `bru run` with `--env-var "mcp_session_id=<captured UUID>"` and wait for HTTP 200

### Expected

- [ ] `mcp-insert.yml`: JSON-RPC response body has a `result` object (no `error` field); `result.content` is non-empty
- [ ] `mcp-search.yml`: JSON-RPC response body has a `result` object containing a non-empty list of memory entries
- [ ] At least one MCP search entry's `memory` contains `"Helsinki"` (case-insensitive)
- [ ] That entry's `user_id` equals `"frostyMemoryMcpInsertSearchTest"`
- [ ] That entry's `score` is a finite number > 0

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
