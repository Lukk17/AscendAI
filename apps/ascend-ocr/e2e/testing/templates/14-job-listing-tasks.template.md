# Listing the work in flight: run tasks template

Spec: [../14-job-listing-test.md](../14-job-listing-test.md)

Copy this file to `../runs/<UTC-timestamp>_14-job-listing-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

The listing this spec reads hands out a job identifier for every piece of work in flight, and on a service with no
authentication that identifier is the credential for the result. Treat the run record as carrying credentials.

## Tasks

### Prerequisites

- [ ] Bruno CLI present (`bru --version` returns a version)
- [ ] ascend-ocr `/health` returns HTTP 200 with `"status":"ok"`
- [ ] `halcyon-ledger-25-pages.pdf`, `argent-saga-chronicles-page1-polish.png` and `argent-saga-chronicles-page1.png` exist under `apps/ascend-ocr/e2e/fixtures/`
- [ ] `OCR_JOB_MAX_PAGES` is unset (default 100) or at least 25

### Reset state

- [ ] Job records dropped from the container's jobs directory
- [ ] `ocr-results` bucket emptied
- [ ] `/ready` reports `jobs_queued=0` and `jobs_running=0`

### Run

- [ ] Step 1: listing read while idle
- [ ] Step 2: three documents submitted in quick succession, the twenty five page `ocr/testing/ocr-long-document.yml` first, then `ocr/testing/ocr-polish.yml`, then `ocr/testing/ocr-default-lang.yml`
- [ ] Step 3: listing read while the first is being read
- [ ] Step 4: `/ready` read in the same window
- [ ] Step 5: second document's own state read
- [ ] Step 6: `initialize` returns an `mcp-session-id` header, `ocr/testing/mcp-initialized.yml` answers HTTP 202, MCP listing read
- [ ] Step 7: all three polled to a terminal state, waiting `poll_after_seconds` between reads, then the listing read
- [ ] Step 8: a finished identifier read directly
- [ ] Step 9: all three deleted
- [ ] Step 10: each deleted identifier read with `ocr/testing/ocr-job-not-found.yml`

### Expected

- [ ] Step 1: HTTP 200 with an empty listing, not an error
- [ ] Step 2: positions 0, 1 and 2 on the three answers
- [ ] Step 2: `page_count` 25 on the first answer and 1 on the other two
- [ ] Step 3: three entries, in submission order, positions null, 1, 2 (or 0, 1, 2 if the first is still waiting)
- [ ] Step 3: the first is `running` (or `waiting` if not yet picked up), the rest `waiting` with `pages_done=0`
- [ ] Step 3: the running entry's `pages_done` is between 0 and 25
- [ ] Step 3: every entry carries a non-negative `elapsed_seconds`
- [ ] Step 4: `jobs_running=1`, `jobs_queued=2`, `status="ready"`
- [ ] Step 5: the document's own `queue_position` matches the listing's
- [ ] Step 6: the MCP listing matches the REST listing exactly
- [ ] Step 7: the listing is empty again
- [ ] Step 8: the finished record is still readable by its own identifier
- [ ] Step 9: HTTP 204 for each
- [ ] Step 10: HTTP 404 with `code="JOB_NOT_FOUND"` for each

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
