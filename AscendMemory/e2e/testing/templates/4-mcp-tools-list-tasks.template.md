# MCP tools/list discovery: run tasks template

Spec: [../4-mcp-tools-list-test.md](../4-mcp-tools-list-test.md)

Copy this file to `../runs/<UTC-timestamp>_4-mcp-tools-list-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [ ] Bruno CLI present (`bru --version` returns a version)
- [ ] AscendMemory `/health` returns HTTP 200 with `{"status":"ok"}`

### Reset state

- [ ] None required

### Run

- [ ] Step 1: `curl.exe -fsS -i -X POST http://localhost:7020/mcp ... initialize ...` returns HTTP 200 with an `Mcp-Session-Id` header; capture the UUID
- [ ] Send `mcp-list-tools.yml` via `bru run` with `--env-var "mcp_session_id=<captured UUID>"` and wait for HTTP 200

### Expected

- [ ] `mcp-list-tools.yml`: `result.tools` is a non-empty array
- [ ] At least one entry's `name` contains `"insert"` (case-insensitive)
- [ ] At least one entry's `name` contains `"search"` (case-insensitive)
- [ ] Each entry has a non-empty `inputSchema.properties`; `memory_insert`/`memory_search`/`memory_wipe` advertise `user_id`, `memory_delete` advertises `memory_id`

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
