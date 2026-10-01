# A document longer than a single request could ever have carried: run tasks template

Spec: [../13-long-document-test.md](../13-long-document-test.md)

Copy this file to `../runs/<UTC-timestamp>_13-long-document-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [ ] Bruno CLI present (`bru --version` returns a version)
- [ ] ascend-ocr `/health` returns HTTP 200 with `"status":"ok"`
- [ ] `apps/ascend-ocr/e2e/fixtures/halcyon-ledger-25-pages.pdf` exists
- [ ] `OCR_JOB_MAX_PAGES` is unset (default 100) or at least 25
- [ ] Object store answers on `http://localhost:9070/_floci/health`

### Reset state

- [ ] Job records dropped from the container's jobs directory
- [ ] `ocr-results` bucket emptied

### Run

- [ ] Step 1: submit with `lang=en` and no `quality` part, HTTP 202, wall time recorded
- [ ] Step 2: first status read taken while the reading is under way
- [ ] Step 3: polled to a terminal state, `pages_done` recorded on each read
- [ ] Step 4: result fetched
- [ ] Step 5: job deleted
- [ ] Step 6: deleted identifier read with `ocr/testing/ocr-job-not-found.yml`

### Expected

- [ ] Step 1: `page_count=25`, `state="waiting"`, answered in upload time not reading time
- [ ] Step 1: no page content in the answer
- [ ] Steps 2 and 3: `pages_done` never goes backwards and never exceeds 25
- [ ] Steps 2 and 3: the later hint is no longer than the earlier one
- [ ] Step 3: terminal state is `succeeded`, carrying no hint, with `result.page_count=25`
- [ ] Step 4: twenty five `## Page N` headings, in ascending order
- [ ] Step 4: the canary `Halcyon Ledger Canary` from page 24 is present
- [ ] Step 5: HTTP 204
- [ ] Step 6: HTTP 404 with `code="JOB_NOT_FOUND"`

### Measurements to record

For comparison, the run of 2026-09-25 on image `7605748a6afa` with a 4 GiB memory limit measured 172.1 s of
`result.processing_time_seconds` and 177.2 s from submission to the terminal state, about 7 s a page. These figures
are not a pass criterion.

- Wall time from submission to the terminal state:
- `result.processing_time_seconds` the service reported:
- Per-page average (wall time divided by 25):

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
