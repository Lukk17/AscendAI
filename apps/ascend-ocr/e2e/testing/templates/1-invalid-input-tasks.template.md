# Invalid input: run tasks template

Spec: [../1-invalid-input-test.md](../1-invalid-input-test.md)

Copy this file to `../runs/<UTC-timestamp>_1-invalid-input-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [ ] Bruno CLI present (`bru --version` returns a version)
- [ ] ascend-ocr `/health` returns HTTP 200 with `"status":"ok"`
- [ ] `/ready` reports `jobs_queued` 0 and `jobs_running` 0

### Reset state

- [ ] None required

### Run

- [ ] Step 1: send `ocr/testing/ocr-invalid-no-file.yml` via `bru run`
- [ ] Step 2: send `ocr/testing/ocr-unsupported-language.yml` via `bru run`
- [ ] Step 3: send `ocr/testing/ocr-jobs-list-empty.yml` via `bru run`

### Expected

- [ ] Step 1: HTTP 422
- [ ] Step 1: the body carries FastAPI's validation detail, not a job record
- [ ] Step 1: no `job_id` in the body
- [ ] Step 2: HTTP 400 with `code="UNSUPPORTED_LANGUAGE"`
- [ ] Step 2: `detail` contains `Supported languages:` and not `korean`
- [ ] Step 2: no `job_id`, no `state` and no `Location` header
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
