# MCP unsupported language rejection: run tasks template

Spec: [../20-mcp-unsupported-language-test.md](../20-mcp-unsupported-language-test.md)

Copy this file to `../runs/<UTC-timestamp>_20-mcp-unsupported-language-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [ ] Bruno CLI present (`bru --version` returns a version)
- [ ] ascend-ocr `/health` returns HTTP 200 with `"status":"ok"`
- [ ] `/ready` reports `jobs_queued` 0 and `jobs_running` 0

### Reset state

- [ ] None required

### Run

- [ ] Step 1: `initialize` handshake returns an `mcp-session-id` header
- [ ] Step 1: `notifications/initialized` sent with `ocr/testing/mcp-initialized.yml` and that session id, HTTP 202 with an empty body
- [ ] Step 2: send `ocr/testing/mcp-unsupported-language.yml` with that session id
- [ ] Step 3: send `ocr/testing/ocr-jobs-list-empty.yml`

### Expected

- [ ] Step 2: HTTP 200 at the transport, with a JSON-RPC error frame or an `isError` result
- [ ] Step 2: the answer carries `UNSUPPORTED_LANGUAGE` and `Supported languages:`
- [ ] Step 2: no `DOWNLOAD_FAILED`, no `korean` and no `job_id` in the answer
- [ ] Step 3: HTTP 200 with `{"jobs": []}`

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
