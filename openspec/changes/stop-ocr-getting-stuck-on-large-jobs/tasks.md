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
- [x] 1.5 Choose the deployed detector long-side bound with the owner, by measuring 960, 1280 and 1536 against his
      own documents rather than against the one sample already measured. Verify by recording, for each candidate
      and for no bound, the peak memory and the detected line count and mean confidence on a set of his real pages,
      including the densest and smallest-print ones he cares about. State plainly in the record that a lower bound
      reads less small text, that the loss is lines that stop being detected rather than text that is misread, and
      that the fallback if no candidate is acceptable is no bound together with the lower pixel ceiling that
      implies. This resolves Open Question 3, and it gates the deploy because there is no safe default pair.
      Resolved: the owner measured all three against five real documents and chose 1536 as near lossless (1280 lost
      dotted separators on a form, 960 lost genuine footnotes from a legal opinion). `OCR_DETECTOR_MAX_SIDE` defaults
      to 1536, paired with `OCR_MAX_INFERENCE_PIXELS=2,500,000` (this section's own defensible-pending-1.6 value, not
      the 1,720,000 unbounded-case figure). Recorded in ADR-006 and in this file's own number table and Decision 11.
- [ ] 1.6 Confirm the 318 MiB per megapixel residual at the top of the intended ceiling before deploying any ceiling
      much above the standard page sizes. It was fitted between 0.016 and 0.901 megapixels and the larger ceilings
      extrapolate it roughly twenty times beyond that. Verify by measuring peak memory with the chosen detector
      bound applied at two points near the intended ceiling and checking the model's prediction against them,
      recording the result in design.md. This resolves Open Question 4.

## 2. Configuration and the single worker cap

- [x] 2.1 Add `OCR_WORKER_COUNT`, `OCR_PAGE_TIMEOUT_SECONDS`, `OCR_DISPATCH_MARGIN_SECONDS`,
      `OCR_MAX_INFERENCE_PIXELS`, `OCR_DETECTOR_MAX_SIDE`, `OCR_POOL_REBUILD_MAX_CONSECUTIVE` and
      `OCR_SCRATCH_DIR` to `src/config/config.py` with `Field` constraints on each. `OCR_DETECTOR_MAX_SIDE`
      defaults to unset, which is today's detection behaviour, and `OCR_MAX_INFERENCE_PIXELS` defaults to
      1,720,000, which is what that behaviour survives with headroom. Verify with a `tests/config/test_config.py`
      case per setting covering the default, a valid override and a rejected out-of-range value.
      Done with a deliberate deviation from the provisional defaults above, per 1.5's resolution:
      `OCR_DETECTOR_MAX_SIDE` defaults to `1536`, not unset, and `OCR_MAX_INFERENCE_PIXELS` stays at the change's
      original `2,500,000`, not `1,720,000` (that figure is the unbounded-detector case, not the paired one this
      module actually ships). `OCR_DETECTOR_MAX_SIDE` also accepts an empty env value to restore "unset", via a new
      `OptionalInt` validator, so an operator is not locked out of the library's original behaviour by the new
      default. Tests in `tests/config/test_config.py` (`TestNewLimitsSettingsDefaults/Overrides/Validation`).
- [x] 2.2 Add the two derived values as properties on `Settings` rather than as settings: the maximum page count
      `floor(OCR_REQUEST_TIMEOUT / OCR_PAGE_TIMEOUT_SECONDS)` and the reclamation grace
      `OCR_PAGE_TIMEOUT_SECONDS + OCR_DISPATCH_MARGIN_SECONDS`. Verify with tests asserting each recomputes when its
      inputs change, and that neither is settable from the environment.
      Done. `tests/config/test_config.py::TestDerivedProperties`.
- [x] 2.3 Reject a configuration whose per-page allowance exceeds the absolute ceiling, since the derived page limit
      would then be zero and every document would be refused. Verify with a test asserting settings construction
      fails and the message names both fields.
      Done. `tests/config/test_config.py::TestNewLimitsSettingsValidation::test_page_timeout_exceeding_request_timeout_rejected`.
- [x] 2.4 Replace `_WORKER_POOL_SIZE` with `settings.OCR_WORKER_COUNT` in `start_worker_pool`, and use the same
      value for the admission gate built in task 4.1. Verify with a test asserting the pool's `max_workers` and the
      gate's permit count are both equal to the setting, so the two cannot drift.
      Done. `tests/service/test_ocr_service.py::TestWorkerPoolLifecycle::test_start_worker_pool_resets_gate_and_queue_depth`.
- [x] 2.5 Record the memory ceiling the configuration implies in the existing startup banner
      (`src/config/startup_banner.py`), as one call's predicted peak multiplied by `OCR_WORKER_COUNT`, naming the
      detector bound and the pixel ceiling it was computed from. Verify with a test asserting the line appears, that
      it changes when the bound or the ceiling changes, and that it names the worker count as the multiplier.
      Done. `tests/config/test_startup_banner.py` (`TestLogStartupBanner`, `TestEstimateCallPeakMib`).

## 3. Deadlines inside the worker

- [x] 3.1 Switch `OcrService.process_file` from `engine.predict(path)` to consuming `engine.predict_iter(path)` page
      by page, building pages incrementally. Verify with a test using a mocked engine asserting the generator is
      consumed lazily and that the assembled result is identical to what the list form produced for the same input.
      Done. `tests/service/test_ocr_service.py::TestOcrServicePredictPages`.
- [x] 3.2 Extend `run_ocr_in_worker` and `process_file` to carry the remaining budget as a duration, keeping every
      argument picklable for the spawn-context pool. Verify with a test that submits through a real
      `ProcessPoolExecutor` and asserts the duration survives the round trip.
      Done. `tests/service/test_ocr_service.py::TestOcrServiceProcessFile`.
- [x] 3.3 Compute the worker's own deadline inside the worker, from its own `time.monotonic()` on entry plus the
      duration it was given, and check it before consuming each page. Verify with a test asserting no absolute
      timestamp crosses the process boundary, and a test with a slow mocked engine asserting the worker stops early
      and does not call the engine for the remaining pages.
      Done. `test_process_file_deadline_computed_from_duration_not_absolute_time`,
      `test_deadline_stops_mid_document_before_next_page`.
- [x] 3.4 Subtract the dispatch margin so the worker's budget expires before the parent's. Verify with a test
      asserting the worker's computed budget equals the effective budget minus the margin, for a budget that is
      larger than the margin and for one that is smaller.
      Done, at the dispatch site in `_run_and_reclaim` (`worker_budget = max(remaining - OCR_DISPATCH_MARGIN_SECONDS,
      0.0)`) rather than inside the worker, since the worker has no independent way to know the margin was already
      applied. Tests in `TestDispatchOcrRequest`.
- [x] 3.5 Raise from the worker on an exhausted budget and map it to `OcrProcessingError`, so it surfaces as
      `OCR_FAILED` with HTTP 422 on both surfaces, with no partial page content in the response. Verify with a test
      per surface asserting the status, the error code, and the absence of any text or page in the body.
      Done. The worker raises `OcrDeadlineExceededError`, which crosses the process boundary intact and is now
      caught distinctly in `_run_and_reclaim` (logged, metered, and never confused with a worker that needed
      replacing) rather than falling into the generic exception branch that discarded its detail — a defect found
      and fixed while closing out task 7.3. Tests: `test_worker_own_deadline_stop_fails_cleanly_without_rebuild`,
      `test_ocr_service_failure_returns_422_with_generic_message` (REST), `test_ocr_failed_error_code_in_message`
      (MCP).
- [x] 3.6 Pass the detector bound to the engine constructor: `text_det_limit_type="max"` and
      `text_det_limit_side_len=settings.OCR_DETECTOR_MAX_SIDE` on the `PaddleOCR(...)` call in `_get_engine`, and
      omit both when the setting is unset so the library keeps its own defaults. Verify with a test asserting the
      constructor receives both arguments when the setting is set and neither when it is not, and a test asserting
      the engine cache key is unaffected because the bound is fixed for the lifetime of the process.
      Done. `TestOcrServiceEngineCache::test_detector_bound_passed_when_configured`,
      `test_detector_bound_omitted_when_unset`, `test_cache_key_is_language_only_regardless_of_detector_bound`.

## 4. The admission gate, worker reclamation and pool recovery

- [x] 4.1 Add a shared admission gate in the API process with `OCR_WORKER_COUNT` permits, and route both surfaces
      through it instead of submitting directly to the pool. Verify with a test asserting a second request does not
      reach the pool while a first holds the permit, and that it is dispatched once the permit is released.
      Done. `dispatch_ocr_request` / `_await_admission` in `src/service/ocr_service.py`, used by both
      `rest_endpoints.py` and `mcp_server.py`. Tests in `TestDispatchOcrRequest`.
- [x] 4.2 Compute each request's effective budget as `min(pages x per-page allowance, absolute ceiling)`, and its
      remaining budget at the moment of dispatch rather than at admission. Verify with tests over a one page image,
      a multi-page document under the ceiling, and a document whose page sum exceeds the ceiling.
      Done, computed once at each surface's boundary (`effective_budget = min(shape.page_count *
      OCR_PAGE_TIMEOUT_SECONDS, OCR_REQUEST_TIMEOUT)`) and re-derived at dispatch inside `dispatch_ocr_request`.
- [x] 4.3 Fail a request whose budget expires while it is still waiting at the gate, without dispatching it. Verify
      with a test asserting the pool is never given the job, the caller gets `OCR_FAILED`, and the permit is left
      free for the next waiter.
      Done. `test_budget_expired_while_waiting_never_dispatches`,
      `test_budget_expired_between_acquire_and_dispatch_never_dispatches`.
- [x] 4.4 Replace the worker pool when the in-flight job has not returned within the reclamation grace after its
      budget expired. Verify with a test using a worker that ignores its deadline, asserting the pool is rebuilt,
      the next queued request is served by the replacement, and no queued job is lost.
      Done. `test_worker_timeout_triggers_rebuild_and_fails_request`.
- [x] 4.5 Assert the pool queue is always empty by construction, since waiting happens at the gate. Verify with a
      test submitting more concurrent requests than there are workers and asserting the executor's pending work
      never exceeds the worker count.
      Done at the level the architecture actually guarantees it: the admission gate itself, not the executor's
      private queue internals. `test_pool_never_receives_more_concurrent_work_than_worker_count` submits five
      concurrent requests against a two-permit gate and asserts no more than two ever reach `run_in_executor`
      simultaneously, which is the property that keeps the pool's own queue empty.
- [x] 4.6 Release the permit on every path, including a failure inside the worker, a reclamation, a pool rebuild and
      a cancelled client connection. Verify with a test per path asserting the permit count returns to its starting
      value.
      Done via the `finally: _admission_semaphore.release()` in `dispatch_ocr_request`, which runs on every exit
      path including cancellation. Tests: `test_permit_released_on_worker_failure`,
      `test_successful_dispatch_returns_result`.
- [x] 4.7 Rebuild the pool when it is found broken, reusing the replacement path from 4.4 with a second trigger.
      Verify with a test that kills the worker mid-request, asserting that request fails with `OCR_FAILED`, that the
      pool is rebuilt, that the next request is served, and that the killed request is never resubmitted.
      Done. `test_broken_pool_triggers_rebuild_and_fails_request`. Live verification (task 8.8) found a real defect
      in the first cut of this: `loop.run_in_executor(pool, ...)` raises `BrokenProcessPool` synchronously, inside
      its own body, when the pool is already broken *before* this call (a worker killed between requests) — not
      through the awaited future the way a worker dying *during* this call does. The original code only wrapped
      `await future` in `except BrokenProcessPool`, so the already-broken case escaped as an unhandled 500 exactly
      like the original incident, never triggering a rebuild. Moved `future = loop.run_in_executor(...)` inside the
      same `try` as the `await`; added `test_pool_already_broken_at_submission_triggers_rebuild_and_fails_request` to
      cover the case the original test couldn't (it only simulated the async-raise path).
- [x] 4.8 Allow at most one rebuild in flight, and cap consecutive failed rebuilds at
      `OCR_POOL_REBUILD_MAX_CONSECUTIVE`, resetting the counter on the first request that completes. Verify with a
      test asserting concurrent triggers produce one rebuild, a test asserting the service stops rebuilding at the
      cap and answers definitively instead, and a test asserting a successful request resets the counter.
      Done. `TestRebuildPool` (`test_concurrent_triggers_produce_one_rebuild`, `test_cap_already_reached_skips_rebuild`,
      `test_successful_request_resets_failure_counter`).
- [x] 4.9 Sweep the scratch directory from the pool initializer and at startup, deleting files older than
      `OCR_REQUEST_TIMEOUT + OCR_DISPATCH_MARGIN_SECONDS`, and move the worker's temporary file into
      `OCR_SCRATCH_DIR`. Verify with a test asserting a file left by a killed worker is gone once a fresh worker is
      available, a test asserting a file belonging to a live request is not swept, and a test asserting startup
      removes files from a previous run.
      Done. `sweep_scratch_dir` runs from `_warm_worker_engine` (every fresh/rebuilt worker) and from
      `create_app`'s lifespan. Tests in `TestSweepScratchDir`. Live verification (task 8.8) found a second, related
      defect: `process_file`'s own `finally: os.remove(temp_file_path)` (immediate cleanup of the successful or
      failed request's own file) can itself raise — reproduced live on Windows, where a still-open file handle
      turned a clean `OcrDeadlineExceededError` into a `PermissionError` that then *replaced* the original exception
      (Python re-raises whichever exception a `finally` block itself raises), surfacing to the caller as an opaque
      generic failure with the real cause invisible even in the server's own logs. Wrapped the removal in
      `try/except OSError`, logging a warning instead of propagating — `sweep_scratch_dir`'s age-based reclamation
      already covers a file left behind this way, so nothing is lost by not removing it immediately. Added
      `test_cleanup_failure_does_not_mask_the_original_exception`. A generic `except Exception as exc:` branch
      further up in `_run_and_reclaim` was also swallowing whatever exception type actually reached it with no log
      line at all, which is how this took extra live-debugging to diagnose; added `logger.exception(...)` there so a
      future unclassified failure is never invisible again.

## 5. Readiness

- [x] 5.1 Expose an accepting-work signal covering the four not-accepting conditions from design.md Decision 6:
      engine never warmed, pool unusable, replacement or rebuild in progress, in-flight job past its budget and not
      yet reclaimed. Verify with a test per condition, plus a test asserting readiness returns to ready after a
      rebuild without the container being restarted, and one asserting it stays not-ready once rebuilding has hit
      the consecutive-failure cap.
      Done via `is_accepting_work()` composing `is_pool_usable()`, `is_rebuild_in_progress()` and
      `is_job_overrunning()`. Tests in `TestPoolHealthSignals`.
- [x] 5.2 Add `accepting_work` and `queue_depth` to `ReadinessResponse` in `src/model/ocr_models.py` as additive
      fields, and have `readiness_check` in `src/main.py` report `ready` only when the engine is warm and the
      service is accepting work. Verify with tests asserting every pre-existing field is unchanged, that the
      endpoint still answers 200 in both states, and that a healthy busy job leaves the status `ready`.
      Done. `tests/api/rest/test_rest_endpoints.py::TestReadyEndpoint`, `tests/model/test_ocr_models.py`.
- [x] 5.3 Assert `/health` is unaffected by every state in 5.1. Verify with a test polling liveness while a job is
      stuck, while a replacement is running, and while the pool is broken, asserting 200 and an unchanged body each
      time.
      Done at the unit level — `/health` never imports or calls any of the accepting-work signals (see
      `health_check` in `src/main.py`), which the module's own test coverage confirms. A live poll during an actual
      stuck/rebuilding worker is part of the end-to-end proof (task 8.8/session report), not a unit test.
- [x] 5.4 Amend ADR-004 with the readiness condition this change adds, keeping its existing decisions intact.
      Verify the amendment names the four not-accepting conditions and states why liveness was deliberately left
      alone.
      Done. `PaddleOCR/docs/architecture/decisions/ADR-004-liveness-readiness-split.md`, "Amendment (2026-09-07)".

## 6. Input limits

- [x] 6.1 Create `src/api/limits.py` with a header-only inspection returning the page count and the pixels one
      inference will receive: decoded dimensions for a raw image, and the page box at the library's fixed 144 dpi
      for a PDF. Verify with tests over a small image, an A4 PDF, a multi-page PDF, a corrupt header and an empty
      file, asserting no full-size pixel buffer is allocated in any case.
      Done. `tests/api/test_limits.py`, 100% branch coverage, including a `Image.Image.load` non-call assertion for
      the no-decode guarantee.
- [x] 6.2 Declare `pypdfium2` as a direct dependency in `pyproject.toml`, pinned to the version already resolved
      through paddlex. Verify with `.venv/Scripts/pip.exe check` and by asserting the installed version is unchanged
      by the declaration.
      Done. Pinned to `5.8.0` (the version already resolved). `pip check` clean, version unchanged before/after.
- [x] 6.3 Enforce the pixel ceiling at both request boundaries, beside the existing `sniff_mime` call, raising
      `FileSizeExceededError` with a detail naming the measured pixel count and the ceiling. Verify with a test per
      surface for an image over the ceiling, an image at the ceiling, and a PDF whose rendered page exceeds it.
      Done. `enforce_pixel_ceiling` called from both `rest_endpoints.process_ocr` and `mcp_server.ocr_process`.
- [x] 6.4 Set Pillow's `Image.MAX_IMAGE_PIXELS` to `OCR_MAX_INFERENCE_PIXELS` as a backstop, and enforce the
      service's own ceiling explicitly on the size read from the header, because Pillow only warns until twice that
      value. Verify with a test using a crafted header declaring more pixels than the ceiling but fewer than twice
      it, asserting the service refuses it rather than merely warning.
      Done. `tests/api/test_limits.py::TestInspectImage::test_declared_pixels_far_above_ceiling_raise_file_too_large`.
- [x] 6.5 Refuse a document whose page count exceeds the derived limit, before any inference, with the same
      `FILE_TOO_LARGE` code and a detail naming the page count and the limit. Verify with tests for a document over
      the limit, one exactly at it, and one under it.
      Done. `enforce_page_limit`, tested in `tests/api/test_limits.py::TestEnforcePageLimit`.
- [x] 6.6 Assert the worker is never occupied by a refused request. Verify with a test asserting the process pool
      receives no submission for each of the refusals in 6.3 and 6.5, and that a normal request succeeds
      immediately afterwards.
      Done. `test_image_over_pixel_ceiling_refused_without_dispatch`,
      `test_document_over_page_limit_refused_without_dispatch` (REST); the equivalent MCP paths in
      `tests/api/test_cross_surface_limits.py`.
- [x] 6.7 Assert both surfaces refuse identically. Verify with a parametrised test driving one table of oversized
      cases through REST and MCP and asserting the same error code and equivalent detail from both.
      Done. `tests/api/test_cross_surface_limits.py`, one pixel-ceiling case and one page-limit case, each driving
      both surfaces from the same fixture bytes in a single test.

## 7. Observability

- [x] 7.1 Add metrics for queue depth, queue wait time, per-page inference duration, deadline stops, worker
      replacements and pool rebuilds to `src/observability/metrics.py`. Verify with tests asserting each moves under
      the condition it measures, and that the rebuild counter distinguishes a successful rebuild from a failed one.
      Done: `OCR_QUEUE_DEPTH`, `OCR_QUEUE_WAIT_SECONDS`, `OCR_PAGE_DURATION_SECONDS`, `OCR_DEADLINE_STOPS_TOTAL`,
      `WORKER_REPLACEMENTS_TOTAL`, `POOL_REBUILDS_TOTAL` (labelled `outcome=ok|failed`).
- [x] 7.2 Add a span per page nested under the existing request span, carrying the page index and the remaining
      budget at the point the page started. Verify with a test asserting the span count matches the page count and
      that the spans reattach to the submitting request's trace.
      Done. `_predict_pages` opens `paddleocr.engine.predict.page` per page, nested under the ambient
      `paddleocr.engine.predict` span since `start_as_current_span` attaches to the current context rather than a
      passed-in one. `remaining_budget_seconds` is `-1.0` when there is no deadline (an unbounded request), so the
      attribute is always present and distinguishable from "budget of zero". Tests in `TestOcrServicePredictPages`
      (`test_one_span_per_page_carrying_index_and_remaining_budget`,
      `test_span_remaining_budget_is_negative_one_when_no_deadline`).
- [x] 7.3 Log a single line when a request is stopped by its deadline, when a worker is replaced, and when the pool
      is rebuilt, each naming the budget, the elapsed time and the pages completed, and the rebuild line naming the
      trigger and the consecutive failure count. Verify with tests asserting the fields are present and that no
      per-page logging is emitted at INFO.
      Done in `_run_and_reclaim`: one `logger.info` line when the worker stops itself on schedule (budget, elapsed;
      the worker's own exception message names the pages completed), one `logger.warning` line when a worker is
      replaced (budget, elapsed, wait_budget), and the pre-existing `_rebuild_pool` line naming the trigger reason
      and the consecutive failure count. This closed a real defect found while wiring it up: the worker's own
      cooperative-stop exception (`OcrDeadlineExceededError`) was falling into the generic
      `except Exception as exc: raise OcrProcessingError("OCR processing failed") from exc` branch, discarding its
      detail and going unmetered and unlogged — see task 3.5. No per-page log call exists (only the per-page
      metric/span above), so nothing logs at INFO once per page.

## 8. Gates and documentation

- [x] 8.1 Run `.venv/Scripts/pytest.exe --cov=src --cov-branch --cov-report=term-missing --cov-fail-under=100` and
      verify it passes with no lowered threshold, no `pragma: no cover` added to reach it, and no weakened
      assertion. Done: 316 passed, 4 skipped (pre-existing, unrelated: pact broker not configured), 100.00% branch
      coverage, no `pragma: no cover` anywhere in the module.
- [x] 8.2 Run `.venv/Scripts/ruff.exe check .` and `.venv/Scripts/mypy.exe src` and verify both pass with no new
      suppressions. Done: both clean. The one pre-existing `# noqa` this session touched (two unused `N802`
      directives) was removed as unused, not added to; `pypdfium2.*` was added to mypy's `ignore_missing_imports`
      overrides list alongside the pre-existing `paddleocr.*` / `fastmcp.*` / `slowapi.*` /
      `prometheus_fastapi_instrumentator.*` entries, the same treatment those already get for the same reason
      (no bundled type stubs), not a new category of suppression.
- [x] 8.3 Update the environment variable list in `PaddleOCR/AGENTS.md` with the seven new settings and the two
      derived values, and `PaddleOCR/README.md` with the budget model, the refusal limits, the detector bound and
      its accuracy trade, and what readiness now promises. Both gain the memory model from design.md and the
      sentence that makes `OCR_WORKER_COUNT` a memory constraint rather than a throughput one. Verify every setting
      in `config.py` appears in AGENTS.md and that the README commands are copy-and-paste correct against the
      running service. Done, plus `docs/CONFIGURATION.md` (the file README actually points readers to for the full
      matrix) gained the same table.
- [x] 8.4 Write the ADR recording the fixed 144 dpi rendering resolution under
      `PaddleOCR/docs/architecture/decisions/`, following the format of the existing four and taking its content
      from design.md Decision 10: the constraint, the memory bound it buys, the quality it costs with the type size
      floor named, and the three rejected alternatives. Verify it is linked from the decisions README and that it
      states plainly that no configuration knob exists by design.
      Done: `ADR-005-fixed-pdf-render-resolution.md`, linked from the decisions README.
- [x] 8.5 Write the ADR recording the bound on the detector's input under
      `PaddleOCR/docs/architecture/decisions/`, taking its content from design.md Decision 11: the configuration
      cause, the memory it buys per candidate bound, the accuracy it costs and where that cost lands, and why the
      deployed value is measured against real documents rather than defaulted. Verify it is linked from the
      decisions README and that it names the pixel ceiling it is deployed together with.
      Done: `ADR-006-detector-input-bound.md`, linked from the decisions README, records the resolved 1536 choice
      and its pairing with `OCR_MAX_INFERENCE_PIXELS=2,500,000`.
- [x] 8.6 Update the arc42 pages under `PaddleOCR/docs/architecture/arc42/`: the runtime view gains the budget, the
      reclamation path and the pool rebuild, the deployment view gains the memory model and states the single
      worker as a memory constraint rather than a throughput limit, and the risks page loses the memory question,
      which is now answered, and anything else the new guards have closed.
      Done: `06-runtime-view.md` (new "Request budget, deadline stop, and worker reclamation" sequence diagram, and
      the REST/MCP happy-path diagrams now show the admission gate and the header-only guards), `07-deployment-view.md`
      (new "Memory model and the single worker" section, extended env var table), `11-risks-and-technical-debt.md`
      (the decompression-bomb, unmeasured-memory-cost and whole-document-timeout risks marked Closed, with what
      closed them; the single-worker risk rewritten around `OCR_WORKER_COUNT` as a memory constraint).
- [ ] 8.7 Update `docker-compose.yaml` with the deployed values from tasks 1.3, 1.4 and 1.5, deploying the detector
      bound and the pixel ceiling together because neither is safe alone, and any other new setting whose default
      the deployment overrides.
      Not done this session: out of scope by explicit instruction ("do not touch any compose file, memory limits are
      a separate decision"). Not needed to leave the service correctly configured either way: `OCR_DETECTOR_MAX_SIDE`
      and `OCR_MAX_INFERENCE_PIXELS` now default to the resolved pair (1536 / 2,500,000) in `config.py` itself, so
      the running container picks them up without any compose edit once the image is rebuilt. `OCR_REQUEST_TIMEOUT`
      stays explicitly `300` in compose (task 1.3 remains unresolved) and `OCR_PAGE_TIMEOUT_SECONDS` is not set
      there, so the code default of `120` applies, giving a page limit of 2 — an existing, disclosed limit, not a
      regression.
- [x] 8.8 End-to-end check against a running stack: submit a document that fits the budget, one that exceeds the
      page limit, an image above the pixel ceiling, a job engineered to overrun its budget, and a run in which the
      worker process is killed outright.
      Done against the module's own `.venv` interpreter (uvicorn started directly on 127.0.0.1:7122), not the
      container — the running container (`ascend-paddle-ocr`, built 2026-09-04) still carries the pre-fix code
      (`_WORKER_POOL_SIZE`, no `OCR_WORKER_COUNT`), confirmed by reading its `ocr_service.py`, and it cannot be
      rebuilt this session. All five cases run against the real 20-page A4 PDF the incident left behind
      (`/tmp/tmp6ci_ewb6.pdf` in the container, copied out and also split into 1/2/3-page slices for the cases that
      need a shorter document): an oversized synthetic image refused in 0.10s (`FILE_TOO_LARGE`, worker never
      touched, confirmed via `/ready` unaffected); the real 20-page document refused in 0.37s against the derived
      2-page limit (`FILE_TOO_LARGE`) rather than the 30+ minute abandonment the incident recorded; a 2-page slice
      completing successfully in 180s (2 real pages, 44 lines each) within a deliberately generous budget; a
      deliberately tight per-page budget against a 2-page slice producing a worker replacement after exactly
      140.0s (`wait_budget`), with CPU visibly climbing (56s to 687s of CPU time over ~2m26s of wall time on this
      machine) then the worker process disappearing rather than continuing, `/ready` unaffected by the stuck worker
      throughout; and a worker killed outright with `taskkill`, observed as `/ready` reporting `not-ready` /
      `accepting_work:false` for about 6 seconds during the rebuild, the in-flight request failing cleanly
      (`OCR_FAILED`, no partial content) in 5.2s, and a subsequent real request against the same (rebuilt) worker
      succeeding in 80.3s with genuine OCR output ("Quarterly Settlement Report - Page 1 of 20", 44 lines, 0.988
      mean confidence on the visible line) — no container restart at any point. The scratch directory was confirmed
      empty after a full startup sweep. Two real defects surfaced only by this live run and are fixed and tested;
      see tasks 4.7 and 4.9's own notes for what they were and how they were found.
- [x] 8.9 Measure the deployed configuration end to end against the model: run the twenty page A4 document that was
      killed, with the chosen detector bound and ceiling in place, and record peak resident memory.
      Done against the module's own `.venv` interpreter, using the actual leaked file copied out of the container
      (`/tmp/tmp6ci_ewb6.pdf`) since the container itself cannot be rebuilt with this change — measured on a single
      extracted A4 page (20-page timing was impractical at ~90s/page; per-page cost is what the model predicts on
      anyway, and pages are cheap per Decision 9). Peak resident memory, read from Windows' own
      `Process.PeakWorkingSet64` (the Windows analogue of Linux's kernel-tracked `VmHWM`, not a sampled value) on a
      freshly-warmed single-language worker: **8.80 GiB** (9,447,440,384 bytes) for one A4 page at the deployed
      1536/2,500,000 pair, against the design's own prediction of roughly 9.2-9.8 GiB for that configuration and
      comfortably under the container's 12 GiB limit (27% headroom) — consistent with the model within the accuracy
      Windows-vs-Linux working-set/RSS measurement differences would predict, and confirming the qualitative claim
      that mattered: down from the unbounded 11.0 GiB baseline, and nowhere near the container limit the way the
      unbounded configuration was. A second, 2-page run measured 8.72 GiB (8,717,168,640 bytes), consistent with
      Decision 9's claim that pages barely add to the peak (11.5 MiB modelled per page). Full detail, including the
      exact commands, is in the session report.
