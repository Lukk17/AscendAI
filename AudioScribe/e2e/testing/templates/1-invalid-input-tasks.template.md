# Invalid input rejection: run tasks template

Spec: [../1-invalid-input-test.md](../1-invalid-input-test.md)

Copy this file to `../runs/<UTC-timestamp>_1-invalid-input-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [ ] Bruno CLI present (`bru --version` returns a version)
- [ ] AudioScribe `/health` returns HTTP 200 with `{"status":"ok","service":"AudioScribe"}`

### Reset state

- [ ] None required

### Run

- [ ] Send `transcribe-invalid-no-file.yml` via `bru run` and wait for the response

### Expected

- [ ] HTTP status code is 422
- [ ] Response `Content-Type` starts with `application/json`
- [ ] Response body parses as JSON
- [ ] Response body has a non-empty `detail` array
- [ ] At least one `detail` entry has `loc` containing `"file"`
- [ ] At least one `detail` entry has `type` containing the substring `"missing"`
- [ ] Run duration < 1 s (proxy for "FastAPI short-circuited; OpenAI was not called")

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
