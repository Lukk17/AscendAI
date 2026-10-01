# MCP file:// jail: run tasks template

Spec: [../11-mcp-file-uri-jail-test.md](../11-mcp-file-uri-jail-test.md)

Copy this file to `../runs/<UTC-timestamp>_11-mcp-file-uri-jail-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [ ] Bruno CLI present (`bru --version` returns a version)
- [ ] ascend-ocr `/health` returns HTTP 200 with `"status":"ok"`
- [ ] `/ready` reports `jobs_queued` 0 and `jobs_running` 0
- [ ] Image `ascend-ai-ascend-ocr:latest` exists
- [ ] No container named `ascend-ocr-jail` exists
- [ ] Nothing answers on port 7023

### Reset state

- [ ] None required

### Run

- [ ] Step 1: `initialize` handshake on port 7022 returns an `mcp-session-id` header
- [ ] Step 1: `notifications/initialized` sent with `ocr/testing/mcp-initialized.yml` and that session id, HTTP 202 with an empty body
- [ ] Step 2: send `ocr/testing/mcp-file-uri-disabled.yml` with that session id
- [ ] Step 3: send `ocr/testing/ocr-jobs-list-empty.yml`
- [ ] Step 4: start `ascend-ocr-jail` with `MCP_FILE_URI_ROOT=/tmp/ocr-jail` on `127.0.0.1:7023` (in Git Bash with `MSYS_NO_PATHCONV=1`)
- [ ] Step 5: `/health` on port 7023 answers, and `/tmp/ocr-jail` is created inside the container (in Git Bash with `MSYS_NO_PATHCONV=1`)
- [ ] Step 6: `initialize` handshake on port 7023 returns an `mcp-session-id` header
- [ ] Step 6: `notifications/initialized` sent with `ocr/testing/mcp-initialized-jail.yml` and the step 6 session id, HTTP 202 with an empty body
- [ ] Step 7: send `ocr/testing/mcp-file-uri-jail-escape.yml` with the step 6 session id
- [ ] Step 8: read `http://localhost:7023/v1/ocr/jobs`
- [ ] Step 9: remove `ascend-ocr-jail` and confirm it is gone

### Expected

- [ ] Step 2: HTTP 200 at the transport, with a JSON-RPC error frame or an `isError` result
- [ ] Step 2: the answer carries `UNSAFE_URI`
- [ ] Step 2: no `job_id` is issued
- [ ] Step 3: HTTP 200 with `{"jobs": []}`
- [ ] Steps 4 to 6: the throwaway container answers `/health` within 120 seconds, opens a session and accepts the notification with 202
- [ ] Step 7: HTTP 200 at the transport, with a JSON-RPC error frame or an `isError` result
- [ ] Step 7: the answer carries `UNSAFE_URI` and `escapes MCP_FILE_URI_ROOT`, not `MCP_FILE_URI_ROOT is unset`
- [ ] Step 7: no line of `/etc/passwd` and no `job_id` in the answer
- [ ] Step 8: `{"jobs":[]}`
- [ ] Step 9: the container is removed and the confirmation prints nothing

### Verdict

- [ ] Verdict: PASS / FAIL (delete the wrong one)

## Result summary



Input tokens:

Output tokens:

Start (UTC):

End (UTC):

Duration:

---

## Additional tasks I did

<!-- Optional. List anything outside the spec, e.g. diagnostic curls, manual log inspection, retries with different inputs. Leave empty if nothing extra. -->
