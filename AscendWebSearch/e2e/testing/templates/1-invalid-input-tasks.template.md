# Invalid input rejection: run tasks template

Spec: [../1-invalid-input-test.md](../1-invalid-input-test.md)

Copy this file to `../runs/<UTC-timestamp>_1-invalid-input-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [ ] Bruno CLI present (`bru --version` returns a version)
- [ ] AscendWebSearch `/health` returns HTTP 200 with `{"status":"ok"}`

### Reset state

- [ ] None required

### Run

- [ ] Send `search-blank-query.yml` via `bru run` and wait for HTTP 400
- [ ] Send `search-missing-query.yml` via `bru run` and wait for HTTP 422
- [ ] Send `search-overlong-query.yml` via `bru run` and wait for HTTP 400

### Expected

- [ ] `search-blank-query.yml`: HTTP 400; body `detail` equals `"query must not be empty"`
- [ ] `search-missing-query.yml`: HTTP 422; body `detail` array contains an entry with `type="missing"` and `loc` referencing `"query"`
- [ ] `search-overlong-query.yml`: HTTP 400; body `detail` contains the substring `"query exceeds maximum length"`
- [ ] Per-call duration < 2 s (proxy for "validator short-circuited; no SearXNG call")

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
