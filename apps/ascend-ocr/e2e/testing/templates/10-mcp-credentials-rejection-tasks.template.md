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

- [ ] `initialize` handshake returns an `mcp-session-id` header
- [ ] `notifications/initialized` sent with `ocr/testing/mcp-initialized.yml` and that session id, HTTP 202 with an empty body
- [ ] Send `ocr/testing/mcp-credentials-in-uri.yml` with that session id

### Expected

- [ ] HTTP 200 at the transport, with a JSON-RPC error frame or an `isError` result
- [ ] The answer carries `UNSAFE_URI`
- [ ] The answer contains no `pass@`
- [ ] `docker logs ascend-ocr --since 1m` contains no `pass@` (the suite's one sanctioned log assertion, see the spec)
- [ ] No `job_id` is issued

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
