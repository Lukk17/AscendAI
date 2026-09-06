Every command runs from `PaddleOCR/` through that module's own virtual environment (`.venv/Scripts/python.exe` on
Windows, `.venv/bin/python` on Linux and macOS), never the system Python. The gate is `--cov-fail-under=100` with
`--cov-branch`, so every branch added below needs a test before the suite goes green.

Section 1 gates the numbers only. The mechanism in sections 2 to 7 is correct whatever those numbers turn out to
be, so implementation does not wait on section 1, but no provisional default is frozen and nothing is called done
until section 1 has reported. Two of its items, 1.4 and 1.5, are a single owner decision expressed as two settings
and they gate the deploy rather than the implementation, because there is no pair of defaults that is both safe and
useful.

## 1. Measure before freezing any number

- [x] 1.1 Take the running memory investigation's result and answer one question: does peak resident memory stay
      flat across page count, or rise with it? Reported. It is flat: a page adds 11.5 MiB of retained result, and
      peak is set by the largest single page. The fitted model, its validation against the killed job and the
      correction to the cause of that kill are recorded in design.md under "The measured memory model", and
      Decision 9 records which branch of its own rule applies. Open Question 2 is closed. The answer is not the
      reassuring one, because one page's cost is itself most of the container limit, which is what tasks 1.4 and
      1.5 now address.
- [ ] 1.2 Measure p95 per-page inference time on the deployment's 4.0 CPU allocation, and the round-trip cost of a
      trivial job through the process pool. Verify by recording both figures and setting `OCR_PAGE_TIMEOUT_SECONDS`
      and `OCR_DISPATCH_MARGIN_SECONDS` from them, replacing the provisional 120 s and 5 s in design.md with the
      measured values in the same table. This resolves the first half of Open Question 1.
- [ ] 1.3 Decide the deployed absolute ceiling with the owner, from the p95 in 1.2 and the largest document the
      service must accept. Verify the chosen pair is recorded in design.md's number table, that the derived page
      limit is stated alongside it, and that `OCR_REQUEST_TIMEOUT` in `docker-compose.yaml` matches. State to the
      owner that memory does not constrain this trade: a page retains 11.5 MiB, so the page limit is a deadline
      artifact and the only thing a larger ceiling costs is how long a caller holds a connection. This resolves the
      second half of Open Question 1.
- [ ] 1.4 Set the deployed pixel ceiling from the fitted model rather than from the evidence bracket. The
      derivation, the formula and the table of ceilings per detector bound are already in design.md under "The
      pixel ceiling, recomputed". What is left is choosing the resident budget the ceiling assumes, which is an
      owner decision because the host measurement shows the container limit is not what the host can actually give.
      Verify the chosen budget and the resulting ceiling are recorded in design.md's number table, that the ceiling
      is stated together with the detector bound from 1.5 it depends on, and that the standard page sizes are
      re-checked against it.
- [ ] 1.5 Choose the deployed detector long-side bound with the owner, by measuring 960, 1280 and 1536 against his
      own documents rather than against the one sample already measured. Verify by recording, for each candidate
      and for no bound, the peak memory and the detected line count and mean confidence on a set of his real pages,
      including the densest and smallest-print ones he cares about. State plainly in the record that a lower bound
      reads less small text, that the loss is lines that stop being detected rather than text that is misread, and
      that the fallback if no candidate is acceptable is no bound together with the lower pixel ceiling that
      implies. This resolves Open Question 3, and it gates the deploy because there is no safe default pair.
- [ ] 1.6 Confirm the 318 MiB per megapixel residual at the top of the intended ceiling before deploying any ceiling
      much above the standard page sizes. It was fitted between 0.016 and 0.901 megapixels and the larger ceilings
      extrapolate it roughly twenty times beyond that. Verify by measuring peak memory with the chosen detector
      bound applied at two points near the intended ceiling and checking the model's prediction against them,
      recording the result in design.md. This resolves Open Question 4.

## 2. Configuration and the single worker cap

- [ ] 2.1 Add `OCR_WORKER_COUNT`, `OCR_PAGE_TIMEOUT_SECONDS`, `OCR_DISPATCH_MARGIN_SECONDS`,
      `OCR_MAX_INFERENCE_PIXELS`, `OCR_DETECTOR_MAX_SIDE`, `OCR_POOL_REBUILD_MAX_CONSECUTIVE` and
      `OCR_SCRATCH_DIR` to `src/config/config.py` with `Field` constraints on each. `OCR_DETECTOR_MAX_SIDE`
      defaults to unset, which is today's detection behaviour, and `OCR_MAX_INFERENCE_PIXELS` defaults to
      1,720,000, which is what that behaviour survives with headroom. Verify with a `tests/config/test_config.py`
      case per setting covering the default, a valid override and a rejected out-of-range value.
- [ ] 2.2 Add the two derived values as properties on `Settings` rather than as settings: the maximum page count
      `floor(OCR_REQUEST_TIMEOUT / OCR_PAGE_TIMEOUT_SECONDS)` and the reclamation grace
      `OCR_PAGE_TIMEOUT_SECONDS + OCR_DISPATCH_MARGIN_SECONDS`. Verify with tests asserting each recomputes when its
      inputs change, and that neither is settable from the environment.
- [ ] 2.3 Reject a configuration whose per-page allowance exceeds the absolute ceiling, since the derived page limit
      would then be zero and every document would be refused. Verify with a test asserting settings construction
      fails and the message names both fields.
- [ ] 2.4 Replace `_WORKER_POOL_SIZE` with `settings.OCR_WORKER_COUNT` in `start_worker_pool`, and use the same
      value for the admission gate built in task 4.1. Verify with a test asserting the pool's `max_workers` and the
      gate's permit count are both equal to the setting, so the two cannot drift.
- [ ] 2.5 Record the memory ceiling the configuration implies in the existing startup banner
      (`src/config/startup_banner.py`), as one call's predicted peak multiplied by `OCR_WORKER_COUNT`, naming the
      detector bound and the pixel ceiling it was computed from. Verify with a test asserting the line appears, that
      it changes when the bound or the ceiling changes, and that it names the worker count as the multiplier.

## 3. Deadlines inside the worker

- [ ] 3.1 Switch `OcrService.process_file` from `engine.predict(path)` to consuming `engine.predict_iter(path)` page
      by page, building pages incrementally. Verify with a test using a mocked engine asserting the generator is
      consumed lazily and that the assembled result is identical to what the list form produced for the same input.
- [ ] 3.2 Extend `run_ocr_in_worker` and `process_file` to carry the remaining budget as a duration, keeping every
      argument picklable for the spawn-context pool. Verify with a test that submits through a real
      `ProcessPoolExecutor` and asserts the duration survives the round trip.
- [ ] 3.3 Compute the worker's own deadline inside the worker, from its own `time.monotonic()` on entry plus the
      duration it was given, and check it before consuming each page. Verify with a test asserting no absolute
      timestamp crosses the process boundary, and a test with a slow mocked engine asserting the worker stops early
      and does not call the engine for the remaining pages.
- [ ] 3.4 Subtract the dispatch margin so the worker's budget expires before the parent's. Verify with a test
      asserting the worker's computed budget equals the effective budget minus the margin, for a budget that is
      larger than the margin and for one that is smaller.
- [ ] 3.5 Raise from the worker on an exhausted budget and map it to `OcrProcessingError`, so it surfaces as
      `OCR_FAILED` with HTTP 422 on both surfaces, with no partial page content in the response. Verify with a test
      per surface asserting the status, the error code, and the absence of any text or page in the body.

- [ ] 3.6 Pass the detector bound to the engine constructor: `text_det_limit_type="max"` and
      `text_det_limit_side_len=settings.OCR_DETECTOR_MAX_SIDE` on the `PaddleOCR(...)` call in `_get_engine`, and
      omit both when the setting is unset so the library keeps its own defaults. Verify with a test asserting the
      constructor receives both arguments when the setting is set and neither when it is not, and a test asserting
      the engine cache key is unaffected because the bound is fixed for the lifetime of the process.

## 4. The admission gate, worker reclamation and pool recovery

- [ ] 4.1 Add a shared admission gate in the API process with `OCR_WORKER_COUNT` permits, and route both surfaces
      through it instead of submitting directly to the pool. Verify with a test asserting a second request does not
      reach the pool while a first holds the permit, and that it is dispatched once the permit is released.
- [ ] 4.2 Compute each request's effective budget as `min(pages x per-page allowance, absolute ceiling)`, and its
      remaining budget at the moment of dispatch rather than at admission. Verify with tests over a one page image,
      a multi-page document under the ceiling, and a document whose page sum exceeds the ceiling.
- [ ] 4.3 Fail a request whose budget expires while it is still waiting at the gate, without dispatching it. Verify
      with a test asserting the pool is never given the job, the caller gets `OCR_FAILED`, and the permit is left
      free for the next waiter.
- [ ] 4.4 Replace the worker pool when the in-flight job has not returned within the reclamation grace after its
      budget expired. Verify with a test using a worker that ignores its deadline, asserting the pool is rebuilt,
      the next queued request is served by the replacement, and no queued job is lost.
- [ ] 4.5 Assert the pool queue is always empty by construction, since waiting happens at the gate. Verify with a
      test submitting more concurrent requests than there are workers and asserting the executor's pending work
      never exceeds the worker count.
- [ ] 4.6 Release the permit on every path, including a failure inside the worker, a reclamation, a pool rebuild and
      a cancelled client connection. Verify with a test per path asserting the permit count returns to its starting
      value.
- [ ] 4.7 Rebuild the pool when it is found broken, reusing the replacement path from 4.4 with a second trigger.
      Verify with a test that kills the worker mid-request, asserting that request fails with `OCR_FAILED`, that the
      pool is rebuilt, that the next request is served, and that the killed request is never resubmitted.
- [ ] 4.8 Allow at most one rebuild in flight, and cap consecutive failed rebuilds at
      `OCR_POOL_REBUILD_MAX_CONSECUTIVE`, resetting the counter on the first request that completes. Verify with a
      test asserting concurrent triggers produce one rebuild, a test asserting the service stops rebuilding at the
      cap and answers definitively instead, and a test asserting a successful request resets the counter.
- [ ] 4.9 Sweep the scratch directory from the pool initializer and at startup, deleting files older than
      `OCR_REQUEST_TIMEOUT + OCR_DISPATCH_MARGIN_SECONDS`, and move the worker's temporary file into
      `OCR_SCRATCH_DIR`. Verify with a test asserting a file left by a killed worker is gone once a fresh worker is
      available, a test asserting a file belonging to a live request is not swept, and a test asserting startup
      removes files from a previous run.

## 5. Readiness

- [ ] 5.1 Expose an accepting-work signal covering the four not-accepting conditions from design.md Decision 6:
      engine never warmed, pool unusable, replacement or rebuild in progress, in-flight job past its budget and not
      yet reclaimed. Verify with a test per condition, plus a test asserting readiness returns to ready after a
      rebuild without the container being restarted, and one asserting it stays not-ready once rebuilding has hit
      the consecutive-failure cap.
- [ ] 5.2 Add `accepting_work` and `queue_depth` to `ReadinessResponse` in `src/model/ocr_models.py` as additive
      fields, and have `readiness_check` in `src/main.py` report `ready` only when the engine is warm and the
      service is accepting work. Verify with tests asserting every pre-existing field is unchanged, that the
      endpoint still answers 200 in both states, and that a healthy busy job leaves the status `ready`.
- [ ] 5.3 Assert `/health` is unaffected by every state in 5.1. Verify with a test polling liveness while a job is
      stuck, while a replacement is running, and while the pool is broken, asserting 200 and an unchanged body each
      time.
- [ ] 5.4 Amend ADR-004 with the readiness condition this change adds, keeping its existing decisions intact.
      Verify the amendment names the four not-accepting conditions and states why liveness was deliberately left
      alone.

## 6. Input limits

- [ ] 6.1 Create `src/api/limits.py` with a header-only inspection returning the page count and the pixels one
      inference will receive: decoded dimensions for a raw image, and the page box at the library's fixed 144 dpi
      for a PDF. Verify with tests over a small image, an A4 PDF, a multi-page PDF, a corrupt header and an empty
      file, asserting no full-size pixel buffer is allocated in any case.
- [ ] 6.2 Declare `pypdfium2` as a direct dependency in `pyproject.toml`, pinned to the version already resolved
      through paddlex. Verify with `.venv/Scripts/pip.exe check` and by asserting the installed version is unchanged
      by the declaration.
- [ ] 6.3 Enforce the pixel ceiling at both request boundaries, beside the existing `sniff_mime` call, raising
      `FileSizeExceededError` with a detail naming the measured pixel count and the ceiling. Verify with a test per
      surface for an image over the ceiling, an image at the ceiling, and a PDF whose rendered page exceeds it.
- [ ] 6.4 Set Pillow's `Image.MAX_IMAGE_PIXELS` to `OCR_MAX_INFERENCE_PIXELS` as a backstop, and enforce the
      service's own ceiling explicitly on the size read from the header, because Pillow only warns until twice that
      value. Verify with a test using a crafted header declaring more pixels than the ceiling but fewer than twice
      it, asserting the service refuses it rather than merely warning.
- [ ] 6.5 Refuse a document whose page count exceeds the derived limit, before any inference, with the same
      `FILE_TOO_LARGE` code and a detail naming the page count and the limit. Verify with tests for a document over
      the limit, one exactly at it, and one under it.
- [ ] 6.6 Assert the worker is never occupied by a refused request. Verify with a test asserting the process pool
      receives no submission for each of the refusals in 6.3 and 6.5, and that a normal request succeeds
      immediately afterwards.
- [ ] 6.7 Assert both surfaces refuse identically. Verify with a parametrised test driving one table of oversized
      cases through REST and MCP and asserting the same error code and equivalent detail from both.

## 7. Observability

- [ ] 7.1 Add metrics for queue depth, queue wait time, per-page inference duration, deadline stops, worker
      replacements and pool rebuilds to `src/observability/metrics.py`. Verify with tests asserting each moves under
      the condition it measures, and that the rebuild counter distinguishes a successful rebuild from a failed one.
- [ ] 7.2 Add a span per page nested under the existing request span, carrying the page index and the remaining
      budget at the point the page started. Verify with a test asserting the span count matches the page count and
      that the spans reattach to the submitting request's trace.
- [ ] 7.3 Log a single line when a request is stopped by its deadline, when a worker is replaced, and when the pool
      is rebuilt, each naming the budget, the elapsed time and the pages completed, and the rebuild line naming the
      trigger and the consecutive failure count. Verify with tests asserting the fields are present and that no
      per-page logging is emitted at INFO.

## 8. Gates and documentation

- [ ] 8.1 Run `.venv/Scripts/pytest.exe --cov=src --cov-branch --cov-report=term-missing --cov-fail-under=100` and
      verify it passes with no lowered threshold, no `pragma: no cover` added to reach it, and no weakened
      assertion.
- [ ] 8.2 Run `.venv/Scripts/ruff.exe check .` and `.venv/Scripts/mypy.exe src` and verify both pass with no new
      suppressions.
- [ ] 8.3 Update the environment variable list in `PaddleOCR/AGENTS.md` with the seven new settings and the two
      derived values, and `PaddleOCR/README.md` with the budget model, the refusal limits, the detector bound and
      its accuracy trade, and what readiness now promises. Both gain the memory model from design.md and the
      sentence that makes `OCR_WORKER_COUNT` a memory constraint rather than a throughput one. Verify every setting
      in `config.py` appears in AGENTS.md and that the README commands are copy-and-paste correct against the
      running service.
- [ ] 8.4 Write the ADR recording the fixed 144 dpi rendering resolution under
      `PaddleOCR/docs/architecture/decisions/`, following the format of the existing four and taking its content
      from design.md Decision 10: the constraint, the memory bound it buys, the quality it costs with the type size
      floor named, and the three rejected alternatives. Verify it is linked from the decisions README and that it
      states plainly that no configuration knob exists by design.
- [ ] 8.5 Write the ADR recording the bound on the detector's input under
      `PaddleOCR/docs/architecture/decisions/`, taking its content from design.md Decision 11: the configuration
      cause, the memory it buys per candidate bound, the accuracy it costs and where that cost lands, and why the
      deployed value is measured against real documents rather than defaulted. Verify it is linked from the
      decisions README and that it names the pixel ceiling it is deployed together with.
- [ ] 8.6 Update the arc42 pages under `PaddleOCR/docs/architecture/arc42/`: the runtime view gains the budget, the
      reclamation path and the pool rebuild, the deployment view gains the memory model and states the single
      worker as a memory constraint rather than a throughput limit, and the risks page loses the memory question,
      which is now answered, and anything else the new guards have closed.
- [ ] 8.7 Update `docker-compose.yaml` with the deployed values from tasks 1.3, 1.4 and 1.5, deploying the detector
      bound and the pixel ceiling together because neither is safe alone, and any other new setting whose default
      the deployment overrides. Verify the compose values match the derivation recorded in design.md.
- [ ] 8.8 End-to-end check against a running stack: submit a document that fits the budget, one that exceeds the
      page limit, an image above the pixel ceiling, a job engineered to overrun its budget, and a run in which the
      worker process is killed outright. Verify the first succeeds, the middle two are refused in milliseconds with
      `FILE_TOO_LARGE`, the fourth fails with `OCR_FAILED` and stops consuming CPU within one page, the fifth fails
      that one request and is followed by a successful request without a container restart, that `/ready` reports
      not-ready only while the service genuinely cannot take work, that no temporary file survives any of the
      failures, and that a normal request succeeds immediately after each case.
- [ ] 8.9 Measure the deployed configuration end to end against the model: run the twenty page A4 document that was
      killed, with the chosen detector bound and ceiling in place, and record peak resident memory. Verify the
      measured peak is within the model's stated accuracy of the prediction in design.md and comfortably under the
      chosen resident budget, and correct the model in design.md if it is not.
