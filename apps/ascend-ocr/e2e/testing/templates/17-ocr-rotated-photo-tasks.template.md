# A phone photo turned 90 degrees, read without straightening: run tasks template

Spec: [../17-ocr-rotated-photo-test.md](../17-ocr-rotated-photo-test.md)

Copy this file to `../runs/<UTC-timestamp>_17-ocr-rotated-photo-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [ ] Bruno CLI present (`bru --version` returns a version)
- [ ] ascend-ocr `/health` returns HTTP 200 with `"status":"ok"`
- [ ] `straightening-photo-rotated-90.jpg` and `straightening-test-page.txt` exist
- [ ] The object store answers on `http://localhost:9070/_floci/health`
- [ ] The startup banner reports the result store as `[answered]`

### Reset state

- [ ] Job records dropped from the container's jobs directory
- [ ] `ocr-results` bucket emptied
- [ ] `/ready` reports `jobs_queued=0` and `jobs_running=0`, and the bucket is confirmed empty

### Run

- [ ] Step 1: submit with `ocr/testing/ocr-rotated-photo.yml`, HTTP 202, `job_id` recorded
- [ ] Step 2: poll the state until terminal, waiting `poll_after_seconds` between reads
- [ ] Step 3: terminal state read with `ocr/testing/ocr-rotated-photo-status.yml`
- [ ] Step 4: result fetched with `ocr/testing/ocr-straightening-page-result.yml`
- [ ] Step 5: delete the job
- [ ] Step 6: read the deleted identifier with `ocr/testing/ocr-job-not-found.yml`

### Expected

- [ ] Step 1: HTTP 202, `state="waiting"`, 22 character `job_id`, `page_count=1`
- [ ] Step 1: `status_url` and the `Location` header both `/v1/ocr/jobs/<job_id>`, no page content
- [ ] Step 2: non-terminal reads carry `poll_after_seconds` between 1 and 30, the terminal read carries none
- [ ] Step 3: `state="succeeded"`, `result.language="pl"`, `result.quality="high"`, `result.straighten=false`
- [ ] Step 3: `result.page_count=1`, `result.key=<job_id>.md`
- [ ] Step 4: HTTP 200, `## Page 1` is the first line and the only page heading
- [ ] Step 4: all 21 canaries the spec lists are present
- [ ] Step 4: all 21 lines of `straightening-test-page.txt` are present, each at a best similarity of at least 0.8
- [ ] Step 4: no front matter and no `schema_version`
- [ ] Step 5: HTTP 204 with an empty body
- [ ] Step 6: HTTP 404 with `code="JOB_NOT_FOUND"`

### Measurements to record

- Wall time from submission to the terminal state:
- `result.processing_time_seconds` the service reported:

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
