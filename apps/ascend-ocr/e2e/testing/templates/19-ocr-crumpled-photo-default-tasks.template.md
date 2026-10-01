# A crumpled page read in normal mode, not straightened by default: run tasks template

Spec: [../19-ocr-crumpled-photo-default-test.md](../19-ocr-crumpled-photo-default-test.md)

Copy this file to `../runs/<UTC-timestamp>_19-ocr-crumpled-photo-default-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [ ] Bruno CLI present (`bru --version` returns a version)
- [ ] ascend-ocr `/health` returns HTTP 200 with `"status":"ok"`
- [ ] `straightening-photo-crumpled-1.jpg` exists
- [ ] The object store answers on `http://localhost:9070/_floci/health`
- [ ] The startup banner reports the result store as `[answered]`

### Reset state

- [ ] Job records dropped from the container's jobs directory
- [ ] `ocr-results` bucket emptied
- [ ] `/ready` reports `jobs_queued=0` and `jobs_running=0`, and the bucket is confirmed empty

### Run

- [ ] Step 1: submit with `ocr/testing/ocr-crumpled-normal.yml`, HTTP 202, `job_id` recorded
- [ ] Step 2: poll the state until terminal, waiting `poll_after_seconds` between reads
- [ ] Step 3: terminal state read with `ocr/testing/ocr-crumpled-normal-status.yml`
- [ ] Step 4: result fetched with `ocr/testing/ocr-crumpled-normal-result.yml`
- [ ] Step 5: delete the job
- [ ] Step 6: read the deleted identifier with `ocr/testing/ocr-job-not-found.yml`

### Expected

- [ ] Step 1: HTTP 202, `state="waiting"`, 22 character `job_id`, `page_count=1`
- [ ] Step 1: `status_url` and the `Location` header both `/v1/ocr/jobs/<job_id>`, no page content
- [ ] Step 2: non-terminal reads carry `poll_after_seconds` between 1 and 30, the terminal read carries none
- [ ] Step 3: `state="succeeded"`, `result.straighten=false`, `result.quality="normal"`, `result.language="pl"`
- [ ] Step 3: `result.page_count=1`, `result.key=<job_id>.md`
- [ ] Step 4: HTTP 200, `## Page 1` is the first line and the only page heading
- [ ] Step 4: at least one non-empty line of text under the heading
- [ ] Step 4: no front matter
- [ ] Step 5: HTTP 204 with an empty body
- [ ] Step 6: HTTP 404 with `code="JOB_NOT_FOUND"`

### Measurements to record

- Wall time from submission to the terminal state:
- `result.processing_time_seconds` the service reported:
- How many of the 21 canaries spec 18 lists the Markdown carries (recorded, not asserted):

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
