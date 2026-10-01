# The queue refusing work past its bound: run tasks template

Spec: [../16-queue-full-test.md](../16-queue-full-test.md)

Copy this file to `../runs/<UTC-timestamp>_16-queue-full-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [ ] Bruno CLI present (`bru --version` returns a version)
- [ ] ascend-ocr `/health` returns HTTP 200 with `"status":"ok"`
- [ ] `halcyon-ledger-25-pages.pdf` and `argent-saga-chronicles-page1.png` exist under `apps/ascend-ocr/e2e/fixtures/`
- [ ] `OCR_JOB_QUEUE_MAX_DOCUMENTS` is unset (default 8), or the value is recorded here:
- [ ] `OCR_JOB_QUEUE_MAX_PAGES` is unset (default 200) or at least 34
- [ ] `OCR_PAGE_ALLOWANCE_HEADROOM` is unset (default 4.5) or at least 1.5
- [ ] `RATE_LIMIT_OCR` allows at least 10 submissions a minute (`compose.yaml` sets `20/minute`)
- [ ] `OCR_JOB_MAX_PAGES` is unset (default 100) or at least 25

### Reset state

- [ ] Job records dropped from the container's jobs directory
- [ ] `ocr-results` bucket emptied
- [ ] `/ready` reports `status="ready"`, `jobs_queued=0` and `jobs_running=0`

### Run

- [ ] Step 1: long document submitted, `job_id` recorded
- [ ] Step 2: polled until `running`
- [ ] Step 3: single page image submitted eight times, each `job_id` recorded in order
- [ ] Step 4: listing and `/ready` read with the queue full
- [ ] Step 5: ninth single page submission sent
- [ ] Step 6: listing and `/ready` read again
- [ ] Step 7: all nine deleted, waiting ones first, then read once more
- [ ] Step 8: all nine deleted again, then each read with `ocr/testing/ocr-job-not-found.yml`

### Expected

- [ ] Step 1: HTTP 202, `page_count=25`
- [ ] Step 2: `state="running"`
- [ ] Step 3: eight HTTP 202 answers, `state="waiting"`, `page_count=1`, positions 1 to 8
- [ ] Step 4: nine listing entries, the long document first and `running`, then the eight `waiting` in submission order
- [ ] Step 4: `/ready` reads `status="ready"`, `jobs_running=1`, `jobs_queued=8`
- [ ] Step 5: HTTP 503, `code="QUEUE_FULL"`
- [ ] Step 5: `Retry-After` present, a whole number, equal to `30`
- [ ] Step 5: no `job_id` and no `Location` header
- [ ] Step 6: the same nine entries, same order, no tenth
- [ ] Step 6: `/ready` still reads `jobs_running=1`, `jobs_queued=8`
- [ ] Step 7: HTTP 204 for all nine, each then reads `cancelled`
- [ ] Step 8: HTTP 204 for all nine, each then answers 404 `JOB_NOT_FOUND`, no object for any of them in `ocr-results`

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
