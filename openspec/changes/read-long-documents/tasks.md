Every command runs from `PaddleOCR/` through that module's own virtual environment (`.venv/Scripts/python.exe` on
Windows, `.venv/bin/python` on Linux and macOS), never the system Python. The gate is `--cov-fail-under=100` with
`--cov-branch`, so every branch added below needs a test before the suite goes green.

Section 1 confirms two numbers that are already derived in [design.md](design.md). The mechanism is correct whatever
they turn out to be, so implementation does not wait on section 1, but the change is not done until it has reported
and the number table says either "confirmed" or what it moved to.

## 1. Confirm the two derived numbers

- [ ] 1.1 Re-read the deployed values before touching anything: `OCR_REQUEST_TIMEOUT` in `docker-compose.yaml`,
      `OCR_PAGE_TIMEOUT_SECONDS`, `OCR_DETECTOR_MAX_SIDE` and `OCR_MAX_INFERENCE_PIXELS` in `src/config/config.py`.
      Verify by recording the four values in design.md's number table and confirming the derived `OCR_MAX_PAGES` is
      still 2, so the change starts from the state it claims to.
- [ ] 1.2 Measure the container's peak resident memory and wall time reading a forty page A4 document with the
      deployed detector bound and pixel ceiling. Verify by comparing the observed peak against the model's
      prediction of `10,583 + 11.5 x 40` MiB and recording both in design.md's job page ceiling section, and by
      recording the per-page time so `OCR_PAGE_TIMEOUT_SECONDS` is either confirmed at 120 s or moved with the
      reading ceiling that follows it.
- [ ] 1.3 Measure the serialised size of a twenty five page result. Verify by recording it beside
      `OCR_JOB_MAX_RETAINED` in design.md's number table and confirming that the cap times the measured size is the
      storage figure the table claims, adjusting the cap if it is not.

## 2. Configuration

- [ ] 2.1 Add `OCR_JOB_MAX_PAGES`, `OCR_JOBS_DIR`, `OCR_JOB_RETENTION_SECONDS`, `OCR_JOB_MAX_RETAINED`,
      `OCR_JOB_QUEUE_MAX_PAGES` and `OCR_JOB_QUEUE_MAX_DOCUMENTS` to `src/config/config.py` with `Field`
      constraints on each. Verify with a case per setting in `tests/config/test_config.py` covering the default, a
      valid override and a rejected out-of-range value.
- [ ] 2.2 Add the job reading ceiling as a derived property, `OCR_JOB_MAX_PAGES x OCR_PAGE_TIMEOUT_SECONDS`, beside
      the existing `OCR_MAX_PAGES` and `OCR_RECLAMATION_GRACE_SECONDS`. Verify with a test asserting it recomputes
      when either input changes and that it cannot be set from the environment.
- [ ] 2.3 Lower `OCR_REQUEST_TIMEOUT` to 240 in `docker-compose.yaml`. Verify that the derived `OCR_MAX_PAGES` is
      still 2 and that a two page document's effective budget is unchanged at 240 s, with a test that computes the
      effective budget from the settings rather than asserting a literal.
- [ ] 2.4 Reject a configuration whose queue page bound is below the job page ceiling, since a single maximal
      document could then never be queued. Verify with a test asserting settings construction fails and the message
      names both fields.

## 3. The job store

- [ ] 3.1 Create `src/service/job_store.py` with the record model, the identifier generator and the strict
      identifier validator. Verify with tests that the identifier is URL-safe, at least 128 bits of randomness, and
      that every traversal-shaped or over-long candidate is rejected by the validator before any path is built.
- [ ] 3.2 Implement create, read, update and delete over the record, the submitted bytes and the progress file,
      each write by temporary file plus atomic replace. Verify with tests that a reader never observes a partial
      record, that deleting removes all three files, and that reading an unknown identifier raises the not-found
      error rather than touching the filesystem.
- [ ] 3.3 Implement the retention sweep: remove finished records past `OCR_JOB_RETENTION_SECONDS` from their finish
      time, then evict oldest-first while more than `OCR_JOB_MAX_RETAINED` finished records remain. Verify with
      tests covering an expired record, a record inside its window, eviction by count, and that neither pass ever
      removes a waiting or running record.
- [ ] 3.4 Implement startup recovery: every record found waiting or running becomes failed with the
      `SERVICE_RESTARTED` reason and has its submitted bytes removed, finished records keep their original expiry.
      Verify with a test that seeds a store with one of each state, runs recovery, and asserts the resulting states
      and that no record is left waiting or running.
- [ ] 3.5 Move the file I/O that can be large, the submitted bytes and the result, off the event loop. Verify with
      a test asserting the request handler stays responsive while a submission of `MAX_FILE_SIZE_MB` is written.

## 4. The runner and the queue

- [ ] 4.1 Create `src/service/job_runner.py` with the pending queue, its two bounds and the admission decision.
      Verify with tests that a submission beyond the page bound and one beyond the document bound both raise the
      queue-full error, that the bounds count the running job's remaining pages correctly, and that the queue drains
      in submission order.
- [ ] 4.2 Implement the runner loop: take the next job, acquire the existing admission gate, start the job's
      reading budget at that moment, dispatch through `dispatch_ocr_request`, write the outcome. Verify with tests
      that a job's budget is its full reading ceiling regardless of how long it waited, that only one job runs at a
      time, and that a synchronous request and a job never hold the gate together.
- [ ] 4.3 Sweep on the runner's idle tick as well as at startup, so expiry never waits for a caller. Verify with a
      test that an expired record is removed while no request is served.
- [ ] 4.4 Map every dispatch outcome onto a terminal record: success, deadline expiry, a worker that would not stop,
      a broken pool and an unexpected failure. Verify with a test per outcome asserting the recorded state, the
      recorded code, and that no partial page content is stored for any failure.
- [ ] 4.5 Start and stop the runner from the FastAPI lifespan in `src/main.py`, with startup recovery running before
      it starts. Verify with a test that a job submitted before shutdown leaves no record in a non-terminal state
      after the next startup.

## 5. Cancellation and the worker

- [ ] 5.1 Cancel a waiting job by removing it from the queue and marking the record cancelled. Verify with a test
      that no dispatch occurs for it and that the job behind it moves up.
- [ ] 5.2 Cancel a running job by calling the existing pool replacement path with a new `cancel` reason, and record
      the job as cancelled rather than failed. Verify with tests asserting the replacement is triggered once, the
      rebuild metric carries the new reason, the consecutive-failure counter is not incremented by a cancel, and the
      next queued job is served after the replacement.
- [ ] 5.3 Record per-page progress from inside the worker, written between pages by the same seam the deadline
      check uses. Verify with a test that the progress file advances page by page and never exceeds the document's
      page count, and with a test that a job with no progress yet reports zero rather than omitting the field.
- [ ] 5.4 Move the scratch sweep horizon from `OCR_REQUEST_TIMEOUT + OCR_DISPATCH_MARGIN_SECONDS` to the job
      reading ceiling plus the same margin. Verify with a test that a file younger than the longest legitimate job
      survives a sweep and an older one does not.

## 6. The two surfaces

- [ ] 6.1 Add `POST /v1/ocr/jobs`, `GET /v1/ocr/jobs/{job_id}` and `DELETE /v1/ocr/jobs/{job_id}` to
      `src/api/rest/rest_endpoints.py`, sharing one service layer with the MCP tools. Verify with tests asserting
      202 plus a `Location` header on submission, 200 with the record on status, 204 on delete, 404 on an unknown
      or expired identifier, and 503 with `Retry-After` when the queue is full.
- [ ] 6.2 Add `ocr_submit`, `ocr_job_status` and `ocr_cancel_job` to `src/api/mcp/mcp_server.py`, taking a URI the
      way `ocr_process` does and applying the same fetch guards. Verify with tests that each tool returns the same
      record content as its REST counterpart and raises the same codes with the surface's existing prefix
      convention.
- [ ] 6.3 Apply every existing input guard at submission on both surfaces, with the job page ceiling in place of the
      synchronous one. Verify by extending `tests/api/test_cross_surface_limits.py` so the pixel ceiling, the bomb
      guard, the byte cap, the type check and the page ceiling are each asserted identical across the two surfaces
      and across the synchronous and job paths.
- [ ] 6.4 Parameterise `enforce_page_limit` with the applicable ceiling instead of reading the synchronous setting,
      and make the synchronous refusal name the job path. Verify with tests covering both ceilings and asserting the
      synchronous message mentions where a longer document can be sent.
- [ ] 6.5 Add `QUEUE_FULL` at 503 and `JOB_NOT_FOUND` at 404 to `src/api/exception_handlers.py` with their
      handlers, leaving every existing code and status untouched. Verify with tests in
      `tests/api/test_exception_handlers.py` for both new handlers and a test asserting the existing catalogue is
      unchanged.
- [ ] 6.6 Add `jobs_queued` and `jobs_running` to `ReadinessResponse` and to `/ready`. Verify with tests that both
      fields report correctly while a job runs with others waiting, and that `status` still reads `ready` in that
      state.

## 7. Observability

- [ ] 7.1 Add the job metrics to `src/observability/metrics.py`: outcomes by terminal state, queue depth in
      documents and in pages, queue wait, job duration and retained record count. Verify with tests that each is
      exported and that the queue gauges return to zero when the queue drains.
- [ ] 7.2 Emit one log line per job state transition, carrying the identifier, the page count and the reason for a
      terminal state. Verify with a test asserting a full lifecycle produces exactly one line per transition and
      that no line carries document text.

## 8. Documentation

- [ ] 8.1 Update the environment variable list in `PaddleOCR/AGENTS.md`, `PaddleOCR/README.md` and
      `PaddleOCR/docs/CONFIGURATION.md` with the six new settings, the derived reading ceiling and the changed
      `OCR_REQUEST_TIMEOUT`, each with the derivation from design.md's number table. Verify by diffing the settings
      in `config.py` against the three documents and confirming none is missing from any of them.
- [ ] 8.2 Document the job path end to end for a caller: submit, poll, collect, delete, the five states, the two new
      codes, the recommended poll interval, and the worst-case wait the queue bounds promise. Verify that a reader
      can drive the whole path from the document alone against a running container.
- [ ] 8.3 Write the ADR recording why a long document became a job rather than a larger timeout, with the three
      rejected shapes and their reasons, the derivation of the job page ceiling, and the durability and retention
      trades. Verify it follows the existing format under `PaddleOCR/docs/architecture/decisions/` and is listed in
      that directory's README and in the arc42 decisions page.
- [ ] 8.4 Amend ADR-002 with the two new codes and the record-level `SERVICE_RESTARTED` reason, and ADR-004 with the
      two new readiness fields. Verify both amendments follow the dated-amendment style ADR-004 already uses.
- [ ] 8.5 Update the arc42 pages for the new building block, the job runtime view, and the deployment note about the
      jobs directory and its optional volume. Verify each page's diagram and text mention the store and the runner.
- [ ] 8.6 Correct `PaddleOCR/e2e/README.md`, which states the service holds no persisted state, and give it the
      reset step for a suite run that leaves job records behind. Verify by running the reset step against a
      container with records present and confirming the store is empty afterwards.

## 9. Test surfaces beyond the unit suite

- [ ] 9.1 Add Bruno requests for submit, status and delete under `docs/api/request/AscendAI/paddle-ocr/`, following
      the existing `ocr.yml` shape. Verify each asserts its status code, the record shape and, for status, that a
      completed job carries the same result fields the synchronous request returns.
- [ ] 9.2 Add one e2e capability spec and its run template under `PaddleOCR/e2e/testing/` for reading a document
      longer than the synchronous page limit through the job path. Verify it asserts observable behaviour only, uses
      a fixture with a canary string on a late page, and states its own reset step.
- [ ] 9.3 Confirm the behaviour Decision 12 derives but does not observe: four concurrent single-page synchronous
      requests against one worker. Verify by recording which of the four succeed and which fail with `OCR_FAILED`,
      and record the result in design.md's Decision 12 as observed rather than derived.
- [ ] 9.4 Run the full suite with the coverage gate and the linters: `pytest --cov=src --cov-branch
      --cov-report=term-missing --cov-fail-under=100`, `ruff check .` and `mypy src`. Verify all three pass with no
      suppressions added anywhere in the diff.
