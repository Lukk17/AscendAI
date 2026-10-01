# MCP tools list: run tasks template

Spec: [../5-mcp-tools-list-test.md](../5-mcp-tools-list-test.md)

Copy this file to `../runs/<UTC-timestamp>_5-mcp-tools-list-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [ ] Bruno CLI present (`bru --version` returns a version)
- [ ] ascend-ocr `/health` returns HTTP 200 with `"status":"ok"`

### Reset state

- [ ] None required

### Run

- [ ] `initialize` handshake returns an `mcp-session-id` header
- [ ] Send `ocr/testing/mcp-initialized.yml` with that session id, HTTP 202 with an empty body
- [ ] Send `ocr/testing/mcp-list-tools.yml` with that session id

### Expected

- [ ] HTTP 200
- [ ] Exactly four tools advertised, no other name
- [ ] `ocr_submit` advertised, with `file_uri` and `lang`
- [ ] `ocr_submit` advertises `quality` as a string, `enum` exactly `normal` and `high`, `default` `high`
- [ ] `ocr_submit` advertises `straighten` as a boolean, `default` `false`
- [ ] `ocr_job_status` advertised, with `job_id`
- [ ] `ocr_list_jobs` advertised
- [ ] `ocr_cancel_job` advertised, with `job_id`
- [ ] `ocr_process` is not advertised under any name
- [ ] No advertised tool name contains `process`

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
