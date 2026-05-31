# Readiness endpoint: run tasks template

Spec: [../7-ready-endpoint-test.md](../7-ready-endpoint-test.md)

Copy this file to `../runs/<UTC-timestamp>_7-ready-endpoint-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [ ] Bruno CLI present (`bru --version` returns a version)
- [ ] PaddleOCR `/health` returns HTTP 200 with `"status":"ok"`

### Reset state

- [ ] None required

### Run

- [ ] `bru run "paddle-ocr/testing/ready.yml" --env ascend-local` returns HTTP 200

### Expected

- [ ] HTTP 200
- [ ] Body `status` equals `"ready"`
- [ ] Body `engine_warm` equals `true`
- [ ] Body `version` is a non-empty string

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
