Every command in sections 1 to 10 runs from `apps/ascend-ocr/` through that module's own virtual environment,
and always as `python.exe -m <tool>`: the console-script shims in that environment are broken and exit 1 silently,
so `.venv/Scripts/ruff.exe` and friends prove nothing. On Windows the interpreter is `.venv/Scripts/python.exe`, on
Linux and macOS `.venv/bin/python`. The gate is `--cov-fail-under=100` with `--cov-branch`, already in
`pyproject.toml`'s `addopts`, so a bare `python.exe -m pytest` runs it and every branch added below needs a test
before the suite goes green. Section 11 runs from `apps/ascend-agent/` through `./gradlew`, and section 12 runs
`openspec` from the repository root.

This change depends on [upgrade-ocr-to-ppocrv6](../upgrade-ocr-to-ppocrv6/proposal.md), which is implemented and
gate-green and not yet archived. Every duration and every ceiling in [design.md](design.md)'s number table was
derived from measurements against the `PP-OCRv6_small` pair that change installed, so nothing below is meaningful
against the model it replaced. Do not start section 2 on a checkout where `paddleocr` is still pinned at 3.6.0.

Section 1 confirms numbers that are already derived in design.md. The mechanism is correct whatever they turn out to
be, so implementation does not wait on section 1, but the change is not done until it has reported and the number
table says either "confirmed" or what it moved to. Task 1.4 is the exception: the per-page allowance is the
service's only configured time input after this change, so it has to be settled before section 2 writes the derived
quantities down.

## 1. Confirm the numbers the design rests on

- [ ] 1.1 Re-read the deployed values before touching anything: `OCR_REQUEST_TIMEOUT` and
      `OCR_PAGE_TIMEOUT_SECONDS` in `compose.yaml`, and `OCR_PAGE_TIMEOUT_SECONDS`, `OCR_DETECTOR_MAX_SIDE`,
      `OCR_MAX_INFERENCE_PIXELS`, `OCR_TEXT_DETECTION_MODEL` and `OCR_TEXT_RECOGNITION_MODEL` in
      `src/config/config.py`. Verify by recording the values in design.md's number table, confirming the derived
      `OCR_MAX_PAGES` is 2 at the deployed pair of 300 s and 150 s, and confirming the running container resolves
      the `PP-OCRv6_small` pair rather than `PP-OCRv5_server_det`, so the change starts from the state it claims to
      and against the model its numbers were measured on.
      **2026-09-24, half settled.** Every value in `compose.yaml` and `config.py` is confirmed and recorded in
      design.md's Context section, including the derived `OCR_MAX_PAGES` of 2. The container-side half is not: there
      is no running `ascend-ocr` container, the one on this host exited 137 forty four hours ago, and its image was
      built on 2026-09-18, before `upgrade-ocr-to-ppocrv6`. Its logs show it resolving `PP-OCRv5_server_det` and
      `en_PP-OCRv5_mobile_rec`. **What settles it: rebuild the image from this tree, start it, and read the startup
      banner and the first `Creating model:` log line.**
- [ ] 1.2 Measure the container's peak resident memory and wall time reading a hundred page A4 document with the
      deployed detector bound, pixel ceiling and model pair. Verify by comparing the observed peak against the
      design's prediction of about 440 MB plus 11.5 MiB a page (Superseded 2026-09-25: measured as a Linux container's cgroup `memory.peak`, one A4 page at 300 dpi peaks at 1016 MiB, see `fix-ocr-page-resolution` design.md Decision 10.), recording both in design.md's "What memory no longer
      constrains" section, and by recording the per-page time so the allowance settled in 1.4 is either confirmed or
      moved with every duration derived from it. The 11.5 MiB a page term is carried forward from a fit against the
      detector this service no longer runs, and it is the only memory number the page ceiling still leans on, so
      this task is what turns it from an upper bound into a measurement.
      **Not measured.** It needs a hundred page document read inside the container, with the container's own
      `memory.peak`, and no container is running. **What settles it: run e2e spec 13 against a rebuilt container and
      read `memory.peak` from the cgroup afterwards.** The 11.5 MiB a page term stays an upper bound carried forward
      until it does.
- [ ] 1.3 Measure the serialised size of the Markdown result for a twenty five page and a hundred page document.
      Verify by recording both beside `OCR_JOB_MAX_RETAINED` in design.md's number table and confirming that the cap
      times the measured size is a storage figure the operator of the bucket would accept, adjusting the cap if it
      is not.
      **Not measured.** It needs the Markdown of a real twenty five page and a real hundred page reading, which only
      exists after a run. **What settles it: e2e spec 13 leaves a twenty five page result in the bucket; `curl -sI`
      its presigned URL for the content length, and repeat at a hundred pages.** The cap stays at 1000 until then.
- [x] 1.4 Settle the per-page allowance at the value design.md's number table derives, 45 s, since the code default
      of 120 s and the `compose.yaml` value of 150 s can no longer both stand once every other duration is a
      multiple of it and both were sized against a model that cost nine times as much per page. Verify by setting
      one value in `src/config/config.py`, deleting the override from `compose.yaml`, and recomputing the reading
      ceiling, the reclamation grace, the maximum lifetime, the queue promise, the poll hint and the scratch sweep
      horizon in design.md's number table from the settled value.
      Overtaken on 2026-09-24 by `fix-ocr-page-resolution`, which replaces the single 45 s with one allowance per
      engine, `OCR_PAGE_ALLOWANCE_HEADROOM` times the worst page measured on that engine's detector, and now owns the
      allowance and every duration derived from it. This task stays ticked as the record of what was done.

## 2. Configuration

- [x] 2.1 Add `OCR_JOB_MAX_PAGES`, `OCR_JOBS_DIR`, `OCR_JOB_RETENTION_SECONDS`, `OCR_JOB_MAX_RETAINED`,
      `OCR_JOB_QUEUE_MAX_PAGES` and `OCR_JOB_QUEUE_MAX_DOCUMENTS` to `src/config/config.py` with `Field`
      constraints on each. Verify with a case per setting in `tests/config/test_config.py` covering the default, a
      valid override and a rejected out-of-range value.
- [x] 2.2 Add the two settings-level derived quantities beside the existing `OCR_RECLAMATION_GRACE_SECONDS`: the
      job reading ceiling as `OCR_JOB_MAX_PAGES x OCR_PAGE_TIMEOUT_SECONDS`, and the maximum lifetime in a
      non-terminal state as `(OCR_JOB_QUEUE_MAX_PAGES + OCR_JOB_MAX_PAGES) x OCR_PAGE_TIMEOUT_SECONDS`. Verify with
      tests asserting each recomputes when any of its inputs changes and that neither can be set from the
      environment.
- [x] 2.3 Delete `OCR_REQUEST_TIMEOUT`, the derived `OCR_MAX_PAGES` and the validator that rejects a per-page
      allowance above the request timeout, and repoint every consumer: `src/api/limits.py` reads
      `OCR_JOB_MAX_PAGES`, the `min(pages x allowance, OCR_REQUEST_TIMEOUT)` in `src/api/rest/rest_endpoints.py` and
      `src/api/mcp/mcp_server.py` loses its second term and moves to the runner, `sweep_scratch_dir` in
      `src/service/ocr_service.py` takes the job reading ceiling, and `src/config/startup_banner.py` reports the
      allowance, the page ceiling and the derived reading ceiling in place of a request timeout. Verify with a test
      that constructing settings from an environment that still sets `OCR_REQUEST_TIMEOUT` succeeds and ignores it,
      because `SettingsConfigDict` is `extra="ignore"`, with an updated `tests/config/test_startup_banner.py`, and
      with a grep-backed assertion in the test suite that no module reads either deleted name.
- [x] 2.4 Reject a configuration whose queue page bound is below the page ceiling, since a single maximal document
      could then never be queued. Verify with a test asserting settings construction fails and the message names
      both fields.
- [x] 2.5 Add `OCR_RESULT_S3_ENDPOINT`, `OCR_RESULT_S3_PUBLIC_ENDPOINT`, `OCR_RESULT_S3_BUCKET`,
      `OCR_RESULT_S3_ACCESS_KEY` and `OCR_RESULT_S3_SECRET_KEY`, with the public endpoint defaulting to the
      endpoint, the bucket defaulting to `ocr-results`, and the endpoints constrained to an absolute http or https
      URL. Verify with tests covering each default, the public endpoint following the endpoint when unset and not
      following it when set, a rejected non-URL endpoint, and a rejected bucket name that is not a valid S3 bucket
      name.
- [ ] 2.6 Remove the `OCR_REQUEST_TIMEOUT` and `OCR_PAGE_TIMEOUT_SECONDS` lines from `compose.yaml`, add the result
      store endpoint, public endpoint, bucket and credentials, and add whichever job settings differ from their
      defaults. Verify by starting the container and reading the startup banner, confirming it reports the settled
      allowance, the page ceiling, the derived reading ceiling and the result store it resolved, and no request
      timeout.
      **Edit made, verification pending.** `compose.yaml` no longer sets `OCR_REQUEST_TIMEOUT` or
      `OCR_PAGE_TIMEOUT_SECONDS`, and now sets the result store endpoint, public endpoint, bucket and credentials,
      with the two credentials sourced from `.env` and documented in `.env.example`. No job setting differs from its
      default, so none is set. **What settles it: rebuild and start the container, then read the startup banner for
      the settled allowance, the page ceiling, the derived reading ceiling and the result store line.** Starting a
      container is the owner's call.
- [ ] 2.7 Only after task 10.6 has reported, decide with the owner whether to lower the container memory limit in
      `compose.yaml` from 12 G toward the 3 G design.md recommends, and record the decision and its date beside the
      recommendation. Verify by re-running task 10.6's heaviest spec at whatever limit is chosen and confirming the
      container's own `memory.peak` stays under it with the headroom design.md's arithmetic claims. This task is
      deliberately last and deliberately gated: every figure behind the recommendation comes from a synthetic page,
      and a memory limit set from synthetic evidence is how the incident that started all of this happened.

## 3. The job store

      **Blocked on 10.6, as designed.** No edit made to the 12 G limit.
- [x] 3.1 Create `src/service/job_store.py` with the record model, the identifier generator and the strict
      identifier validator. Verify with tests that the identifier is URL-safe, at least 128 bits of randomness, and
      that every traversal-shaped or over-long candidate is rejected by the validator before any path or any object
      key is built.
- [x] 3.2 Implement create, read, update and delete over the record, the submitted bytes and the progress file,
      each write by temporary file plus atomic replace. Verify with tests that a reader never observes a partial
      record, that deleting removes all three files, and that reading an unknown identifier raises the not-found
      error rather than touching the filesystem.
- [x] 3.3 Implement the retention sweep: remove finished records past `OCR_JOB_RETENTION_SECONDS` from their finish
      time, then evict oldest-first while more than `OCR_JOB_MAX_RETAINED` finished records remain, deleting each
      record's result object before its record in both passes. Verify with tests covering an expired record, a
      record inside its window, eviction by count, that neither pass ever removes a waiting or running record, and
      that a failure deleting the object leaves the record in place rather than orphaning the object.
- [x] 3.4 Implement startup recovery: every record found waiting or running becomes failed with the
      `SERVICE_RESTARTED` reason and has its submitted bytes removed, finished records keep their original expiry.
      Verify with a test that seeds a store with one of each state, runs recovery, and asserts the resulting states
      and that no record is left waiting or running.
- [x] 3.5 Move the file I/O that can be large, the submitted bytes, off the event loop. Verify with a test
      asserting the request handler stays responsive while a submission of `MAX_FILE_SIZE_MB` is written.

## 4. The result store in object storage

- [x] 4.1 Add `boto3` to `pyproject.toml`'s dependencies and `boto3-stubs[s3]` to the dev extra, so mypy types the
      client rather than having it ignored. Verify with `python.exe -m pip install -e ".[dev]"`, then
      `python.exe -m mypy src` clean with no new entry in the mypy ignore list, and by confirming from metadata
      that nothing in the new tree moves `paddlepaddle` or `paddleocr`.
- [x] 4.2 Create `src/service/result_store.py` with the S3-compatible client built from the five settings, path-style
      addressing and the fixed region the ascend-ai-agent's `AppConfig.s3Client()` uses, and a startup pass that
      heads the bucket and creates it when missing. Verify with tests that the client is built from the settings
      rather than from the environment's ambient AWS configuration, that a missing bucket is created, and that a
      failure to reach the store at startup logs a `WARNING` and lets the service boot, matching the module's
      existing warn-do-not-refuse posture for the cgroup memory check.
- [x] 4.3 Render a finished document to Markdown: one level-two heading per page naming the page number, then that
      page's recognised lines in reading order, one per line, and nothing else. Verify with tests covering a
      multi-page document, a page with no recognised lines, and text containing Markdown control characters, and one
      asserting the rendering carries no front matter, because the agent indexes whatever it fetches.
- [x] 4.4 Upload the Markdown as `{job_id}.md` with bounded retries before the terminal record is written, so a
      record never claims success with no object behind it. Verify with tests that a transient failure is retried,
      that exhausting the retries fails the job with the `RESULT_STORE_UNAVAILABLE` record-level reason rather than
      with `OCR_FAILED`, and that the reason is marked retryable in the same way `SERVICE_RESTARTED` is.
- [x] 4.5 Generate the presigned GET URL against `OCR_RESULT_S3_PUBLIC_ENDPOINT` for the record's remaining
      retention, on each status read rather than storing it. Verify with tests that the URL is signed against the
      public endpoint and not the internal one, that its expiry never exceeds the record's remaining retention, and
      that a record one second from expiry still produces a valid URL rather than an error.
- [x] 4.6 Delete the result object when the caller deletes the job and when either sweep removes the record, object
      first and record second. Verify with tests that a delete removes both, that deleting twice is not an error,
      and that a record whose object is already gone still deletes cleanly.
- [x] 4.7 Report the result store in `src/config/startup_banner.py`: the endpoint, the public endpoint when it
      differs, the bucket, and whether the bucket answered at boot. Verify with an updated
      `tests/config/test_startup_banner.py` asserting the line is present, that credentials never appear in it, and
      that an unreachable store is reported as a warning rather than as an error.

## 5. The runner and the queue

- [x] 5.1 Create `src/service/job_runner.py` with the pending queue, its two bounds and the admission decision.
      Verify with tests that a submission beyond the page bound and one beyond the document bound both raise the
      queue-full error, that the bounds count the running document's remaining pages correctly, and that the queue
      drains in submission order with no reordering by size.
- [x] 5.2 Implement the runner loop: take the next document, acquire the existing admission gate, start its reading
      budget at that moment, dispatch through `dispatch_ocr_request`, render and upload the result, write the
      outcome. Verify with tests that a document's budget is its page count multiplied by the allowance regardless
      of how long it waited, that only one document is read at a time, and that the upload happens before the
      terminal record is written.
- [x] 5.3 Sweep on the runner's idle tick as well as at startup, so expiry never waits for a caller. Verify with a
      test that an expired record and its object are removed while no request is served.
- [x] 5.4 Map every dispatch outcome onto a terminal record: success, deadline expiry, a worker that would not stop,
      a broken pool, a result store that would not take the upload, and an unexpected failure. Verify with a test
      per outcome asserting the recorded state, the recorded code, and that no partial page content is stored and no
      object is left behind for any failure.
- [x] 5.5 Start and stop the runner from the FastAPI lifespan in `src/main.py`, with startup recovery and the bucket
      check running before it starts. Verify with a test that a document submitted before shutdown leaves no record
      in a non-terminal state after the next startup.
- [x] 5.6 Assert the single path to the worker: the runner is the only caller of `dispatch_ocr_request` and the
      only holder of the admission gate. Verify with a test that fails if any other module imports or calls the
      dispatch function, so the one-document-at-a-time statement the queue's promise rests on stays true by
      construction.

## 6. Cancellation, the worker, and the lifetime bound

- [x] 6.1 Cancel a waiting document by removing it from the queue and marking the record cancelled. Verify with a
      test that no dispatch occurs for it and that the document behind it moves up.
- [x] 6.2 Cancel a running document by calling the existing pool replacement path with a new `cancel` reason, and
      record it as cancelled rather than failed. Verify with tests asserting the replacement is triggered once, the
      rebuild metric carries the new reason, the consecutive-failure counter is not incremented by a cancel, and the
      next queued document is served after the replacement.
- [x] 6.3 Record per-page progress from inside the worker, written between pages by the same seam the deadline
      check uses. Verify with a test that the progress file advances page by page and never exceeds the document's
      page count, and with a test that work with no progress yet reports zero rather than omitting the field.
- [x] 6.4 Move the scratch sweep horizon from the deleted `OCR_REQUEST_TIMEOUT + OCR_DISPATCH_MARGIN_SECONDS` to the
      job reading ceiling plus the same margin. Verify with a test that a file younger than the longest legitimate
      document survives a sweep and an older one does not.
- [x] 6.5 Add the maximum-lifetime sweep: any record still waiting or running past the derived lifetime is failed
      with `LIFETIME_EXCEEDED` and has its submitted bytes removed. Verify with tests that a wedged record is failed
      on the runner's idle tick, that a document at the page ceiling behind a full queue is never failed by it, and
      that the reason is distinguishable from `OCR_FAILED`, from `SERVICE_RESTARTED` and from
      `RESULT_STORE_UNAVAILABLE`.

## 7. The four operations on both surfaces

- [x] 7.1 Add `POST /v1/ocr/jobs`, `GET /v1/ocr/jobs/{job_id}` and `DELETE /v1/ocr/jobs/{job_id}` to
      `src/api/rest/rest_endpoints.py`, sharing one service layer with the MCP tools, with the poll hint computed as
      `clamp(pages_remaining x allowance / 10, 1 s, 30 s)` on every non-terminal answer and absent on every terminal
      one. Verify with tests asserting 202 plus a relative `Location` header and the identifier in the body on
      submission, 200 with the record on status, 204 on delete, 404 on an unknown or expired identifier, 503 with
      `Retry-After` when the queue is full, and the hint present, bounded and absent in the right states.
- [x] 7.2 Carry the result as an address rather than as content: a successful status answer names the bucket, the
      key, a presigned URL and the bounded metadata (`schema_version`, `filename`, `language`, `page_count`,
      `processing_time_seconds`), and no status answer in any state carries page text. Verify with tests that the
      successful answer's size does not grow with the document's page count, that the presigned URL fetches the same
      Markdown the bucket holds, and that every other state carries neither an address nor text.
- [x] 7.3 Add `GET /v1/ocr/jobs`, listing everything queued and running with the identifier, the state, pages done
      of total, how long it has been waiting or running, and its position in the queue. Verify with tests that a
      finished record never appears, that the running document is reported with its live progress, that positions
      are contiguous and in submission order, that the list is empty rather than an error on an idle service, and
      that its length can never exceed `OCR_JOB_QUEUE_MAX_DOCUMENTS` plus one so no pagination is needed.
- [x] 7.4 Add `ocr_submit`, `ocr_job_status`, `ocr_list_jobs` and `ocr_cancel_job` to `src/api/mcp/mcp_server.py`,
      taking a URI the way the removed tool did and applying the same fetch guards. Verify with tests that each tool
      returns the same record content as its REST counterpart, carries the same hint and the same result address,
      and raises the same codes with the surface's existing prefix convention.
- [x] 7.5 Apply every existing input guard at submission on both surfaces. Verify by extending
      `tests/api/test_cross_surface_limits.py` so the pixel ceiling, the bomb guard, the byte cap, the type check
      and the page ceiling are each asserted identical across the two surfaces.
- [x] 7.6 Point `enforce_page_limit` at `OCR_JOB_MAX_PAGES`, the only page ceiling left, and make its refusal name
      the ceiling and the document's page count. Verify with tests covering a document above, at and below the
      ceiling and asserting the message content.
- [x] 7.7 Add `QUEUE_FULL` at 503, `JOB_NOT_FOUND` at 404 and `ENDPOINT_REMOVED` at 410 to
      `src/api/exception_handlers.py` with their handlers, leaving every existing code and status untouched, and add
      `jobs_queued` and `jobs_running` to `ReadinessResponse` and to `/ready`. Verify with tests in
      `tests/api/test_exception_handlers.py` for the three new handlers, a test asserting the existing catalogue is
      unchanged, and tests that both readiness fields report correctly while a document is read with others waiting
      and that `status` still reads `ready` in that state.
- [x] 7.8 Remove the synchronous surface: `POST /v1/ocr` answers 410 with `ENDPOINT_REMOVED` naming
      `POST /v1/ocr/jobs`, the `ocr_process` tool is deleted rather than stubbed, and the rate limits are placed on
      the new operations with submission on `RATE_LIMIT_OCR` and status, list and delete on `RATE_LIMIT_DEFAULT`.
      Verify with tests that the removed endpoint answers 410 with the replacement named, that `tools/list` offers
      exactly the four new tools and not the removed one, and that a status read and a list read are throttled at
      the default limit rather than the OCR one.

## 8. Observability

- [x] 8.1 Add the job metrics to `src/observability/metrics.py`: outcomes by terminal state, queue depth in
      documents and in pages, queue wait, job duration, retained record count, and result upload attempts and
      failures. Verify with tests that each is exported and that the queue gauges return to zero when the queue
      drains.
- [x] 8.2 Emit one log line per state transition, carrying the identifier, the page count and the reason for a
      terminal state. Verify with a test asserting a full lifecycle produces exactly one line per transition and
      that no line carries document text, an object's presigned URL, or a credential.

## 9. Documentation

- [x] 9.1 Update the environment variable list in `apps/ascend-ocr/AGENTS.md`, `apps/ascend-ocr/README.md` and
      `apps/ascend-ocr/docs/CONFIGURATION.md` with the six job settings and the five result store settings, the
      derived reading ceiling and maximum lifetime, the settled per-page allowance, and the deletion of
      `OCR_REQUEST_TIMEOUT` and `OCR_MAX_PAGES`, each with the derivation from design.md's number table. Verify by
      diffing the settings in `config.py` against the three documents and confirming none is missing from any of
      them and none of the deleted pair survives in any of them.
- [x] 9.2 Correct the memory prose in the same three documents and in
      `docs/architecture/memory-budget.md` at the monorepo level, all of which still state a model fitted against
      `PP-OCRv5_server_det` and the claim that one call's peak is most of the container ceiling. Verify that each
      place states the measured figure, states that it holds for every language but `ru` and `korean`, and no
      longer describes `OCR_WORKER_COUNT` as primarily a memory constraint. This is the same correction
      `upgrade-ocr-to-ppocrv6` task 4.6 owns, so do it once and reference it rather than writing a second account.
- [x] 9.3 Document the path end to end for a caller: submit, poll, collect from object storage, delete, the five
      states, the three new codes, the three record-level reasons, the poll hint, the list operation, and the
      worst-case wait the queue bounds promise. Verify that a reader can drive the whole path from the document
      alone against a running container, including fetching the Markdown from the presigned URL.
- [x] 9.4 Write the ADR recording why every request became a job rather than only the long ones, with the rejected
      shapes and their reasons, the rejected two-path design and why it lost, what now sets the page ceiling, and
      the durability and retention trades. Verify it follows the existing format under
      `apps/ascend-ocr/docs/architecture/decisions/` and is listed in that directory's README and in the arc42
      decisions page.
- [x] 9.5 Write the second ADR recording why the result lives in object storage: the owner's decision, the inline
      alternative it replaced, the external dependency the module now has and how Decision 3 contains it, the
      dedicated bucket and why it is not the agent's `knowledge-base`, the bucket's access requirements, and the
      lifecycle rule for orphans. Verify the same way as 9.4.
- [x] 9.6 Amend ADR-002 with the three new codes and the three record-level reasons, ADR-003 with a breaking change
      on both surfaces and what each surface did in place of a version bump, and ADR-004 with the two new readiness
      fields. Verify all three amendments follow the dated-amendment style ADR-004 already uses.
- [x] 9.7 Update the arc42 pages for the new building blocks, the job runtime view, the result store as an external
      dependency in the context and deployment views, and the deployment notes about the jobs directory and its
      optional volume, the bucket, its access policy and its lifecycle rule. Verify each page's diagram and text
      mention the store, the runner and the bucket, and that no page still describes a synchronous request path or a
      service with no external dependency.
- [ ] 9.8 Rewrite the prose in `apps/ascend-ocr/AGENTS.md` that describes the synchronous path and correct
      `apps/ascend-ocr/e2e/README.md`, which states the service holds no persisted state and is now wrong twice
      over. Give the e2e README the reset step for a suite run that leaves job records and result objects behind.
      Verify by reading both files end to end, confirming no sentence describes an operation the service no longer
      offers, and by running the reset step against a container with records and objects present and confirming
      both are empty afterwards.

      **Written, reset step not executed.** Both files are rewritten: `AGENTS.md` describes the job surface, the
      queue, the two new readiness fields and the eleven new settings, and `e2e/README.md` no longer claims the
      service holds no persisted state, carrying instead a "Resetting between runs" section with the two commands
      that empty the jobs directory and the `ocr-results` bucket. **What settles it: run those two commands against a
      container that has records and objects present, and confirm `GET /v1/ocr/jobs` and the bucket listing are both
      empty afterwards.**
## 10. Test surfaces beyond the unit suite

- [ ] 10.1 Rewrite the fifteen Bruno requests that drive the removed surface onto submit, poll, collect and delete:
      `ocr.yml` and the four `ocr/testing/ocr-*.yml` requests, the six `ocr/testing/mcp-*.yml` requests, the three
      under `mcp/ocr/`, and `3rd-party/ocr/read-text-in-image.yml`, whose multipart part is also named `files` today
      where the service declares `file`. Verify each asserts its status code and the record shape, that a completed
      read fetches the presigned URL and finds the same text the removed synchronous request returned, and that the
      two tools-list requests assert the four new tools and the absence of the removed one.
      **Written, not executed.** Fifteen requests rewritten and eleven added: `ocr.yml` submits and the new
      `ocr-job-status.yml`, `ocr-job-result.yml`, `ocr-jobs-list.yml` and `ocr-job-delete.yml` poll, collect and
      delete beside it; `ocr/testing/` gains `ocr-removed-endpoint.yml`, `ocr-polish-result.yml`,
      `ocr-long-document.yml`, `ocr-long-document-result.yml`, `mcp-job-status.yml`, `mcp-list-jobs.yml` and
      `mcp-cancel-job.yml`; `mcp/ocr/ocr-process-english.yml` and `ocr-process-polish.yml` are renamed to
      `ocr-submit-english.yml` and `ocr-submit-polish.yml` beside a new `ocr-job-status.yml`; and
      `3rd-party/ocr/read-text-in-image.yml` moves to the jobs path with its multipart part renamed from `files` to
      `file`. Every file parses as YAML. **What settles it: `bru run` each against a rebuilt container.**
- [x] 10.2 Rewrite e2e specs 1, 2, 3, 4, 6, 8, 9, 10, 11 and 12 and their run templates under
      `apps/ascend-ocr/e2e/testing/` onto the job surface, and add one new spec plus template for reading a document
      longer than any single request could ever have carried. Verify each asserts observable behaviour only, that
      the new spec uses a fixture with a canary string on a late page, and that every spec states its own reset step
      for both the jobs directory and the bucket.
      **Written, not executed.** Specs 1, 2, 3, 4, 6, 8, 9, 10, 11 and 12 and their templates are rewritten onto
      submit, poll, collect and delete, each with its own reset step for the jobs directory and the bucket, and each
      asserting observable behaviour only. Spec 7 gained the two new readiness fields, which the task list did not
      call for but the readiness contract did. New spec 13 reads a twenty five page document, with the canary on page
      24 of the new `halcyon-ledger-25-pages.pdf` fixture, generated by the committed
      `e2e/fixtures/make_halcyon_ledger.py` and verified readable: the local engine reads `Halcyon Ledger Canary` off
      page 24 at confidence 1.0. **What settles it: run the suite against a rebuilt container.**
- [ ] 10.3 Update e2e spec 5 and its template so the tools list it asserts is `ocr_submit`, `ocr_job_status`,
      `ocr_list_jobs` and `ocr_cancel_job`, and so it fails if the removed tool is advertised under any name. Verify
      by running it against a container built from this change.
      **Written, not executed.** Spec 5, its template and `mcp-list-tools.yml` assert the four job tools, their
      arguments, and that no advertised tool is named `ocr_process` or contains `process` at all. **What settles it:
      run it against a container built from this change.**
- [x] 10.4 Add a spec for the list operation: submit more documents than the worker can serve at once, read the
      list, and assert the running document, the waiting ones, their positions and their progress. Verify it asserts
      observable behaviour only and that it states the disclosure design.md's Decision 18 records, so whoever runs
      it knows the operation hands out identifiers.
      **Written, not executed.** New spec 14 submits three documents, reads the listing while the first is being
      read, compares each position against the document's own state, reads the same listing through `ocr_list_jobs`,
      and asserts the listing is empty again once the work finishes. It states the disclosure Decision 18 records, in
      the spec and again in the template. **What settles it: run it against a rebuilt container.**
- [ ] 10.5 Confirm the queue behaviour that replaces the four-concurrent-request arithmetic Decision 12 used to
      derive: four single-page submissions in quick succession. Verify by recording that all four are accepted, that
      they are read in submission order, and that all four succeed, and record the result in design.md's Decision 12
      as observed rather than derived.
      **Not run.** It needs four submissions against a live service. **What settles it: submit four single page
      documents in quick succession against a rebuilt container, record that all four are accepted, read in
      submission order and all succeed, then write the observation into design.md's Decision 12.**
- [ ] 10.6 Measure real scanned documents, which is the one thing every duration in this change is waiting on. Run
      the e2e suite against scans rather than synthetic pages, at least one dense page and at least one long
      document, after asking the owner which scenario from `docs/E2E_RUN_SCENARIOS.md` to run under. These specs are
      engine-bound, so they run one at a time with no other runner active. Verify by recording per-page wall time
      and the container's own `memory.peak` for each, comparing them against the 2.9 s plus 0.14 s a line model and
      the 440 MB figure design.md derives everything from, and either confirming the 45 s allowance or moving it and
      every duration derived from it. This task also gates task 2.7.
      **Not run.** It needs real scanned documents, a live container and the owner's choice of run scenario, and it
      is the measurement every duration in this change is waiting on. **What settles it: ask the owner which scenario
      from `docs/E2E_RUN_SCENARIOS.md` to run under, run the engine-bound specs against scans one at a time with no
      other runner active, and record per-page wall time and the container's own `memory.peak` against the 2.9 s plus
      0.14 s a line model and the 440 MB figure.** (Superseded 2026-09-25: measured as a Linux container's cgroup `memory.peak`, one A4 page at 300 dpi peaks at 1016 MiB, see `fix-ocr-page-resolution` design.md Decision 10.)
      Reconciled on 2026-09-24: the verification now confirms or moves each engine's allowance rather than one 45 s
      figure, and the allowances, their headroom and the measured worst pages are owned by `fix-ocr-page-resolution`,
      whose own risk list names this task as where a wrong allowance would show.
- [x] 10.7 Run the full suite with the coverage gate and the linters: `python.exe -m pytest`,
      `python.exe -m ruff check .` and `python.exe -m mypy src`. Verify all three pass with no suppressions added
      anywhere in the diff.

## 11. The ascend-ai-agent migration

- [x] 11.1 Rewrite `AscendOcrClient.process(byte[], String, String)` as submit, poll, fetch, delete, keeping its
      signature and its return type so `DocumentRouter` is untouched: post multipart `file` and `lang` to
      `{base-url}/v1/ocr/jobs`, expect 202, read `job_id` from the body with the relative `Location` header as a
      cross-check, poll the status resource, fetch the Markdown object with the existing `S3Client` bean using the
      bucket and key the record carries, build the one `Document` from it, then delete the job. Delete
      `parseResponse`, `extractPagesText` and `extractLinesText` rather than adapting them, since the Markdown
      already is the newline-joined text they used to build. Verify with tests in `AscendOcrClientTest` driving a
      stubbed submit, two polls, a terminal success and a stubbed object fetch, asserting the returned documents
      carry the same text the old synchronous response produced plus the page headings the Markdown adds.
- [x] 11.2 Wait between polls by sleeping the calling worker thread for the record's `poll_after_seconds`, floored
      and capped by configuration. Verify with a test that a hint below the floor and one above the cap are both
      clamped, and that no thread beyond the `pdf-parallel-pages` pool is created.
- [x] 11.3 Move `app.ascend-ocr.api-path` from `/v1/ocr` to `/v1/ocr/jobs` and add `poll-min-interval`,
      `poll-max-interval`, `poll-timeout`, `submit-retry-attempts` and `submit-retry-max-delay` beside it in
      `application.yaml`. Verify with a test that each property binds and has a default, and by confirming
      `application-docker.yaml` needs no change because it overrides `base-url` only.
- [x] 11.4 Handle the terminal states: a `failed` or `cancelled` record throws `IngestionException` carrying the
      record's code and reason, and a `SERVICE_RESTARTED` or `RESULT_STORE_UNAVAILABLE` reason resubmits once, at
      most once per page, while `OCR_FAILED` never resubmits. Verify with a test per terminal state, including one
      asserting a second retryable reason does not trigger a third submission.
- [x] 11.5 Issue the `DELETE` before throwing when the client's own `poll-timeout` expires, so the service stops
      reading a document nobody will collect. Verify with a test that a run which never reaches a terminal state
      sends exactly one delete for the identifier it holds and then throws.
- [x] 11.6 Retry a submission only on a definitive 503 `QUEUE_FULL`, honouring `Retry-After` with bounded attempts
      and jitter, and never on a timeout or a connection error. Verify with tests that a 503 is retried up to the
      configured attempts, that a read timeout is not retried at all, and that the failure carries the queue-full
      code through to the caller.
- [x] 11.7 Update the agent's tests to the new contract: `AscendOcrClientTest`,
      `AscendOcrClientResponseParsingTest`, `AscendOcrClientLiveContractTest`, `DocumentRouterTest`,
      `DocumentRouterFileTypeRoutingTest` and `DocumentRouterPdfExceptionTest`, including one asserting a canary
      string survives the page headings the Markdown adds and the chunking downstream of `DocumentRouter`. Verify
      with `./gradlew test` and `./gradlew integrationTest` from `apps/ascend-agent/`, with the live contract test
      pointed at a container built from this change.
      Note 2026-09-25: `src/test/resources/ascend-ocr/openapi-contract.json` re-captured from `GET /openapi.json` of a
      container built from this change (image `9c100951f59b`). It carries `POST /v1/ocr/jobs` with the multipart
      fields `file`, `lang`, `quality` and `straighten`, no `queue_depth`, and the removed `POST /v1/ocr` answering 410.
      The field names `AscendOcrClientLiveContractTest` pins match it, so its TODO marker is removed.
      Note 2026-09-25, later the same day: the re-captured file was then deleted and replaced by the Pact contract
      `contracts/pacts/ascend-agent-ascend-ocr.json`, written by the agent's `AscendOcrClientPactTest` and verified
      by the ascend-ocr provider test.
      `./gradlew test --tests "*AscendOcr*"` passes (39 tests). Remaining: the full `./gradlew test` and
      `./gradlew integrationTest` runs from `apps/ascend-agent/`.
      Done on 2026-10-01. From `apps/ascend-agent/`, the CI gate `./gradlew --no-daemon build test` passes with 779
      tests in 102 classes, no failures and none skipped, `./gradlew --no-daemon jacocoTestCoverageVerification`
      passes the 80 percent instruction floor, and `./gradlew --no-daemon integrationTest` passes with 24 tests in 8
      classes against Testcontainers (postgres 16, redis 7, qdrant v1.13.0, floci 2.0.1), no failures and none
      skipped. Combined instruction coverage is 96.37 percent. The six classes this task names, plus
      `AscendOcrClientPactTest`, ran inside `test`: 88 tests between them, all passing.
- [x] 11.8 Record the two configuration facts the migration changes the meaning of: `app.ingestion.read-timeout`
      stops bounding an OCR operation and becomes a per-call timeout on short calls, and `pdf-parallel-pages` must
      stay at or under `OCR_JOB_QUEUE_MAX_DOCUMENTS`. Verify with a test asserting the fan-out value is within the
      service's document bound, and by stating both in the agent's own documentation beside the property.

## 12. Spec reconciliation

- [x] 12.1 Reconcile the two superseded requirements in `stop-ocr-getting-stuck-on-large-jobs` before either change
      is archived: "A request budget is derived per page and capped overall" loses its overall cap, and "Requests
      waiting for the worker hold their own deadline" is superseded outright. Confirm at the same time that
      `upgrade-ocr-to-ppocrv6`'s `ocr-model-selection` capability is untouched by this change and that its own
      memory re-measurement task and task 1.2 here do not write two different accounts of the same figure. Verify
      with `openspec validate --all --strict` after the edit, and by confirming that whichever change archives first
      leaves `openspec/specs/` with one statement of each invariant rather than two that disagree.
      Done on 2026-09-24. In `stop-ocr-getting-stuck-on-large-jobs`'s `ocr-request-deadlines`, the budget requirement
      is now "A document's budget is derived per page", with no overall cap, and "Requests waiting for the worker
      hold their own deadline" is removed. Four more statements there contradicted this change and were rewritten in
      the same pass: an expired document's code arrives inside its state, a document waiting during a rebuild keeps
      its full budget, the scratch sweep horizon is the longest accepted work, and in `ocr-input-limits` the pixel
      ceiling's default no longer comes from the fitted model and the page count refusal is dropped, so
      `ocr-job-admission` here is its single statement. That change's proposal and design name every overtaken statement, and its tasks 1.3,
      1.4, 1.6 and 8.7 are struck through and left unticked as superseded. `ocr-model-selection` is untouched by
      this change, and no capability name repeats across the three changes, so either archive order leaves one
      statement of each invariant. "39 to 94 seconds" in proposal.md and design.md is corrected to 51 to 94, the
      only measured record being 51.3 to 93.8 s. The one-page peak and per-page time have one account, this change's design.md,
      which `upgrade-ocr-to-ppocrv6` task 4.6 records against rather than beside, while task 1.2 here owns the
      retained-result term and the hundred page timing. `openspec validate --all --strict`: 46 passed, 0 failed.
