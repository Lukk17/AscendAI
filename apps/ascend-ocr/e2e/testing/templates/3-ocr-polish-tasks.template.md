# OCR Polish canary through the job surface: run tasks template

Spec: [../3-ocr-polish-test.md](../3-ocr-polish-test.md)

Copy this file to `../runs/<UTC-timestamp>_3-ocr-polish-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [ ] Bruno CLI present (`bru --version` returns a version)
- [ ] ascend-ocr `/health` returns HTTP 200 with `"status":"ok"`
- [ ] The fixture the spec names exists
- [ ] The object store answers on `http://localhost:9070/_floci/health`
- [ ] The startup banner reports the result store as `[answered]`

### Reset state

- [ ] Job records dropped from the container's jobs directory
- [ ] `ocr-results` bucket emptied and confirmed empty

### Run

- [ ] Step 1: submit, HTTP 202, `job_id` recorded
- [ ] Step 2: first status read taken right away after step 1, before waiting for the hint, with `ocrExpectedLanguage=pl`
- [ ] Step 2: poll the state until terminal, waiting `poll_after_seconds` between reads, with `ocrExpectedLanguage=pl`
- [ ] Step 3: fetch the result URL
- [ ] Step 4: delete the job
- [ ] Step 5: read the deleted identifier with `ocr/testing/ocr-job-not-found.yml`

### Expected

- [ ] Step 1: HTTP 202, `state="waiting"`, 22 character `job_id`, `page_count=1`
- [ ] Step 1: `status_url` and the `Location` header both `/v1/ocr/jobs/<job_id>`
- [ ] Step 1: no page content in the answer
- [ ] Step 2: the first read is `waiting`, `running` or `succeeded` (write which)
- [ ] Step 2: if the first read is `waiting` or `running`, it carries `poll_after_seconds` between 1 and 30 and `pages_done` not above `page_count`. If it is already `succeeded`, write "not observed" beside this box and the next one instead of ticking or failing them
- [ ] Step 2: every non-terminal read carries `poll_after_seconds` between 1 and 30
- [ ] Step 2: `pages_done` never exceeds `page_count`
- [ ] Step 2: terminal state is `succeeded` and carries no hint
- [ ] Step 2: `result.key` equals `<job_id>.md`, with a bucket and a URL beside it
- [ ] Step 2: the terminal read's `result.language` equals `"pl"`
- [ ] Step 2: no read carries page text
- [ ] Step 3: HTTP 200, first line `## Page 1`
- [ ] Step 3: the Markdown carries `Saga Świetlna`, `Aenaria` or `Eklipsą`
- [ ] Step 3: the Markdown carries a Polish-specific accented character
- [ ] Step 3: no front matter
- [ ] Step 4: HTTP 204 with an empty body
- [ ] Step 5: HTTP 404 with `code="JOB_NOT_FOUND"`

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
