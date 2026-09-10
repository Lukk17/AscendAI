# Invalid input rejection: run tasks template

Spec: [../1-invalid-input-test.md](../1-invalid-input-test.md)

Copy this file to `../runs/<UTC-timestamp>_1-invalid-input-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [ ] Bruno CLI present (`bru --version` returns a version)
- [ ] ascend-ocr `/health` returns HTTP 200 with `"status":"ok"`

### Reset state

- [ ] None required

### Run

- [ ] Send `ocr-invalid-no-file.yml` via `bru run` and wait for the response

### Expected

- [ ] HTTP status equals `422`
- [ ] Response body is JSON with a top-level `detail` array
- [ ] At least one `detail` entry has `loc` containing `"file"`

Diagnostic, not a checkbox: note the per-call duration if it looks unusually high, but it is not a verdict input
(Bruno's own startup/encoding overhead dominates the figure — see spec).

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
