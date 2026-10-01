# Unsupported MIME rejection: run tasks template

Spec: [../12-ocr-unsupported-mime-test.md](../12-ocr-unsupported-mime-test.md)

Copy this file to `../runs/<UTC-timestamp>_12-ocr-unsupported-mime-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [ ] Bruno CLI present (`bru --version` returns a version)
- [ ] ascend-ocr `/health` returns HTTP 200 with `"status":"ok"`
- [ ] `apps/ascend-ocr/e2e/fixtures/not-an-image.txt` exists
- [ ] `/ready` reports `jobs_queued` 0 and `jobs_running` 0

### Reset state

- [ ] None required

### Run

- [ ] Send `ocr/testing/ocr-unsupported-mime.yml` via `bru run`
- [ ] Send `ocr/testing/ocr-jobs-list-empty.yml` via `bru run`

### Expected

- [ ] HTTP 400
- [ ] `code="UNSUPPORTED_FILE_TYPE"`
- [ ] No `job_id` in the body
- [ ] The listing answers HTTP 200 with `{"jobs": []}`

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
