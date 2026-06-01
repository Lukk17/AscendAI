# Invalid input rejection: run tasks template

Spec: [../1-invalid-input-test.md](../1-invalid-input-test.md)

Copy this file to `../runs/<UTC-timestamp>_1-invalid-input-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [ ] Bruno CLI present (`bru --version` returns a version)
- [ ] AscendMemory `/health` returns HTTP 200 with `{"status":"ok"}`

### Reset state

- [ ] None required

### Run

- [ ] Send `invalid-missing-user.yml` via `bru run` and wait for HTTP 422

### Expected

- [ ] Response status is HTTP 422
- [ ] Response body is a JSON object with a `detail` array
- [ ] At least one `detail` entry references `"user_id"` in its `loc` array
- [ ] That entry's `type` equals `"missing"`
- [ ] Request latency < 200 ms (proxy for "validator short-circuited; mem0 / Qdrant never touched")

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
