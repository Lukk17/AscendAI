# Cancelling a document while it is being read: run tasks template

Spec: [../15-cancel-running-job-test.md](../15-cancel-running-job-test.md)

Copy this file to `../runs/<UTC-timestamp>_15-cancel-running-job-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [ ] Bruno CLI present (`bru --version` returns a version)
- [ ] ascend-ocr `/health` returns HTTP 200 with `"status":"ok"`
- [ ] `halcyon-ledger-25-pages.pdf` and `argent-saga-chronicles-page1.png` exist under `apps/ascend-ocr/e2e/fixtures/`
- [ ] `OCR_JOB_MAX_PAGES` is unset (default 100) or at least 25
- [ ] Object store answers on `http://localhost:9070/_floci/health`

### Reset state

- [ ] Job records dropped from the container's jobs directory
- [ ] `ocr-results` bucket emptied
- [ ] `/ready` reports `status="ready"`, `jobs_queued=0` and `jobs_running=0`

### Run

- [ ] Step 1: long document submitted, `job_id` recorded
- [ ] Step 2: polled until `running` with `pages_done` of at least 1
- [ ] Step 3: cancelled, UTC time of the answer recorded
- [ ] Step 4: cancelled record read immediately
- [ ] Step 5: cancelled record read again fifteen seconds later
- [ ] Step 6: bucket checked for an object under the cancelled identifier
- [ ] Step 7: `/ready` read until `ready`, within 60 seconds
- [ ] Step 8: next document submitted only after step 7 read `ready`
- [ ] Step 9: next document polled to a terminal state
- [ ] Step 10: next document's result fetched
- [ ] Step 11: both jobs deleted and read once more with `ocr/testing/ocr-job-not-found.yml`

### Expected

- [ ] Step 1: HTTP 202, `page_count=25`, `state="waiting"`
- [ ] Step 2: last read is `running` with `pages_done` between 1 and 24
- [ ] Step 3: HTTP 204
- [ ] Steps 4 and 5: `state="cancelled"`, `error_code` null, `result` null, no `poll_after_seconds` key, a `finished_at`
- [ ] Steps 4 and 5: `pages_done` identical on both reads, never above 25
- [ ] Step 6: HTTP 404, no `<cancelled job_id>.md` in `ocr-results`
- [ ] Step 7: `status="ready"`, `jobs_queued=0`, `jobs_running=0` within 60 seconds of the cancel
- [ ] Step 8: HTTP 202 with `queue_position=0` and `pages_ahead=0`
- [ ] Step 9: terminal state `succeeded`, queue wait (`started_at` minus `submitted_at`) less than 5 seconds
- [ ] Step 10: HTTP 200, a canary under `## Page 1`
- [ ] Step 11: HTTP 204 for both deletes, then 404 `JOB_NOT_FOUND` for both

### Measurements to record

- `pages_done` on the last live read (step 2):
- `pages_done` on the cancelled record (steps 4 and 5):
- Seconds from the cancelled record's `finished_at` to the next document's `started_at` (diagnosis only):
- The next document's queue wait, `started_at` minus `submitted_at`:

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
