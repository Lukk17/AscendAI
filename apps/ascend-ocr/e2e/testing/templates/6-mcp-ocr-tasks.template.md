# MCP reading through the job surface: run tasks template

Spec: [../6-mcp-ocr-test.md](../6-mcp-ocr-test.md)

Copy this file to `../runs/<UTC-timestamp>_6-mcp-ocr-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [ ] Bruno CLI present (`bru --version` returns a version)
- [ ] ascend-ocr `/health` returns HTTP 200 with `"status":"ok"`
- [ ] Object store answers on `http://localhost:9070/_floci/health`
- [ ] `MCP_ALLOWED_HOSTS` contains `host.docker.internal`

### Reset state

- [ ] `e2e-fixtures` bucket created (idempotent)
- [ ] Previous fixture object deleted
- [ ] Fixture uploaded, HTTP 200
- [ ] Job records dropped from the container's jobs directory
- [ ] `ocr-results` bucket emptied

### Run

- [ ] `initialize` handshake returns an `mcp-session-id` header
- [ ] `notifications/initialized` sent with `ocr/testing/mcp-initialized.yml` and that session id, HTTP 202 with an empty body
- [ ] Step 1: `ocr_submit` answers with a job record
- [ ] Step 2: first `ocr_job_status` read taken right away after step 1, before waiting for a hint
- [ ] Step 2: `ocr_job_status` polled until terminal
- [ ] Step 3: result URL fetched
- [ ] Step 4: `ocr_cancel_job` forgets the finished job
- [ ] Step 5: `ocr/testing/mcp-job-not-found.yml` reads the forgotten identifier

### Expected

- [ ] Step 1: 22 character `job_id`, `state="waiting"`, `page_count=1`
- [ ] Step 1: no page content in the tool payload
- [ ] Step 2: the first read is `waiting`, `running` or `succeeded` (write which)
- [ ] Step 2: if the first read is `waiting` or `running`, it carries `poll_after_seconds` between 1 and 30. If it is already `succeeded`, write "not observed" beside this box instead of ticking or failing it
- [ ] Step 2: non-terminal reads carry `poll_after_seconds`, the terminal read does not
- [ ] Step 2: terminal state is `succeeded` with `result.key = <job_id>.md`
- [ ] Step 3: HTTP 200, first line `## Page 1`, canary substring present
- [ ] Step 4: the same `job_id` and `cancelled: true`
- [ ] Step 5: the answer carries `JOB_NOT_FOUND` and no record

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
