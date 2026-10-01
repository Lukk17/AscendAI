# MCP bad scheme rejection: run tasks template

Spec: [../9-mcp-bad-scheme-test.md](../9-mcp-bad-scheme-test.md)

Copy this file to `../runs/<UTC-timestamp>_9-mcp-bad-scheme-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [ ] Bruno CLI present (`bru --version` returns a version)
- [ ] ascend-ocr `/health` returns HTTP 200 with `"status":"ok"`
- [ ] `/ready` reports `jobs_queued` 0 and `jobs_running` 0

### Reset state

- [ ] None required

### Run

- [ ] `initialize` handshake returns an `mcp-session-id` header
- [ ] `notifications/initialized` sent with `ocr/testing/mcp-initialized.yml` and that session id, HTTP 202 with an empty body
- [ ] Step 1: send `ocr/testing/mcp-bad-scheme.yml` with that session id
- [ ] Step 2: send `ocr/testing/mcp-bad-scheme-data.yml` with that session id
- [ ] Step 3: send `ocr/testing/mcp-bad-scheme-windows-path.yml` with that session id
- [ ] Step 4: send `ocr/testing/ocr-jobs-list-empty.yml`

### Expected

- [ ] Steps 1 to 3: HTTP 200 at the transport, each with a JSON-RPC error frame or an `isError` result
- [ ] Steps 1 to 3: each answer carries `UNSAFE_URI`
- [ ] Steps 1 to 3: no `job_id` is issued
- [ ] Step 1: the message carries `Unsupported URI scheme: 'ftp'`
- [ ] Step 2: the message carries `Unsupported URI scheme: 'data'`
- [ ] Step 3: the message carries `Unsupported URI scheme: 'c'`
- [ ] Step 4: HTTP 200 with `{"jobs": []}`

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
