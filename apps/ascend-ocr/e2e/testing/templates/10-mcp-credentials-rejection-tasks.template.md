# MCP credentials-in-URI rejection: run tasks template

Spec: [../10-mcp-credentials-rejection-test.md](../10-mcp-credentials-rejection-test.md)

Copy this file to `../runs/<UTC-timestamp>_10-mcp-credentials-rejection-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [ ] Bruno CLI present (`bru --version` returns a version)
- [ ] ascend-ocr `/health` returns HTTP 200 with `"status":"ok"`

### Reset state

- [ ] None required

### Run

- [ ] Step 1: `curl.exe -fsS -i -X POST http://localhost:7022/mcp ... initialize ...` returns HTTP 200 with an `Mcp-Session-Id` header; capture the UUID
- [ ] Step 2: send `mcp-credentials-in-uri.yml` via `bru run` with `--env-var "mcp_session_id=<captured UUID>"` plus `-o "$env:TEMP\ocr-creds-run.json" -f json`, and wait for HTTP 200
- [ ] Step 3: print the captured response frame with the `Get-Content` / `ConvertFrom-Json` one-liner from the spec

### Expected

- [ ] Step 1 returns HTTP 200 and the `Mcp-Session-Id` header value is non-empty
- [ ] Step 2 returns HTTP 200 carrying a JSON-RPC error envelope referencing `UNSAFE_URI` (credentials in URI rejected before DNS / fetch)
- [ ] The frame printed by step 3 does NOT contain `user:pass`, `pass@`, or the offending URI in any form

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
