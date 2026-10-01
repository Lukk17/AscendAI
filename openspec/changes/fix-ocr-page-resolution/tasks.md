Every command runs from `apps/ascend-ocr/` through the module's own virtual environment, as `python -m <tool>`. On
Windows the interpreter is `.venv/Scripts/python.exe`, on Linux and macOS `.venv/bin/python`. The gate is
`--cov-fail-under=100` with `--cov-branch`, already in `pyproject.toml`'s `addopts`. Tests are written and seen to
fail before the code that makes them pass.

## 1. Tests first

- [x] 1.1 `tests/config/test_config.py`: the two shipped pairs, a pair parsed from the environment, a malformed pair,
      a pair beyond the ratio ceiling, the source pixel ceiling default and override, `quality_profile()` for both
      modes, and the deleted settings neither present nor read anywhere under `src/`. Seen failing at collection
      (`ImportError: cannot import name 'DEFAULT_QUALITY'`) before the code existed.
- [x] 1.2 `tests/api/test_limits.py`: the source pixel ceiling at and above the setting, per frame of a multi-frame
      TIFF, Pillow's own raise above twice its limit mapped to the same refusal, Pillow's global set from the setting,
      a PDF page never refused on pixels, a 300 dpi A4 scan accepted, and a TIFF's frame count as its page count.
- [x] 1.3 `tests/service/test_page_renderer.py`: a PDF page rendered at the mode's scale, a physically large page
      rendered at the reduced scale, an image read at its own size, an oversized PNG and JPEG shrunk with the aspect
      kept, EXIF orientation applied, every TIFF frame yielded and only the first frame of anything else, BGR order
      and contiguity on both paths, and forms initialised and the document closed when the consumer stops early.
- [x] 1.4 `tests/service/test_ocr_service.py`: the engine constructed without a detector bound, both modes sharing
      one engine, every predict call carrying the mode's bound, `quality` carried from `dispatch_ocr_request` through
      `run_ocr_in_worker` to `process_file`, pages read from the renderer, a real PDF and a real PNG reaching the
      engine at the expected size, nothing written to disk, and the deadline checked before each page is rendered.
      The scratch file and sweep tests are removed with the code.
- [x] 1.5 Surfaces and plumbing: `quality` accepted, defaulted and refused on REST and MCP, advertised as an enum
      with `high` as default on the tool, persisted on the record with old records reading as `high`, passed by the
      runner, reported in the result reference, and the cross-surface guard table moved to the source pixel ceiling.
- [x] 1.6 Per-engine allowance (Decision 8): the measured table, the allowance per engine, the unmeasured-detector
      fallback, the worst allowance over reachable languages, grace, reading ceiling and lifetime following every
      input, the runner charging each document its own engine's allowance, allowed seconds ahead and `Retry-After`
      summed per entry, and the dispatch grace taken from the request's own engine.

## 2. Code

- [x] 2.1 `src/config/config.py`: `QualityMode`, `DEFAULT_QUALITY`, `QualityProfile`, `OCR_QUALITY_NORMAL`,
      `OCR_QUALITY_HIGH`, `OCR_MAX_SOURCE_PIXELS`, `Settings.quality_profile()`. `OCR_MAX_INFERENCE_PIXELS`,
      `OCR_DETECTOR_MAX_SIDE`, `OCR_SCRATCH_DIR`, and the `OptionalInt` helper only the detector bound used, deleted.
- [x] 2.2 `src/api/limits.py`: the source pixel ceiling per frame, TIFF frame counting, and `PDF_RENDER_SCALE` and
      the inference ceiling deleted. Pillow's global is set by the renderer module, which both processes import.
- [x] 2.3 `src/service/page_renderer.py`: new, per Decisions 1 and 4.
- [x] 2.4 `src/service/ocr_service.py`: pages from the renderer, the bound per call, `quality` threaded through, the
      scratch file, `_safe_suffix` and `sweep_scratch_dir` removed.
- [x] 2.5 `quality` on `JobRecord` and `JobResultReference`, in `JobService.submit`, in the runner's dispatch, on
      `POST /v1/ocr/jobs` and on `ocr_submit`. The startup sweep call removed from `src/main.py`.
- [x] 2.6 `numpy` declared in `pyproject.toml` at the installed 2.3.5, inside every installed dependent's range
      (`paddlex` requires `numpy<2.4,>=1.24`).
- [x] 2.7 `OCR_PAGE_TIMEOUT_SECONDS` replaced by `OCR_PAGE_ALLOWANCE_HEADROOM` and `MEASURED_WORST_PAGE_SECONDS`, with
      `model_pair()`, `page_allowance_seconds()`, `reclamation_grace_seconds()` and `OCR_WORST_PAGE_ALLOWANCE_SECONDS`
      on `Settings`, and the runner, the service layer and the dispatch path moved onto them.

## 3. Documentation

- [x] 3.1 ADR-005 marked superseded by ADR-010, with the fitted-model price of a 300 dpi page corrected by the
      measurement.
- [x] 3.2 ADR-006 amended: the bound is per mode, the unset option is gone, the pixel ceiling it was deployed with is
      gone, the claim that a lower bound never affects recognition is corrected by the 6.85x measurement, and the
      claim that the fitted model is exact for `ru` and `korean` is corrected by the 3.7.0 measurements.
- [x] 3.3 `apps/ascend-ocr/AGENTS.md`: the two modes, the source pixel ceiling, the `FILE_TOO_LARGE` row, the per-engine
      allowance and every quantity derived from it, the deleted settings, `DEFAULT_LANGUAGE` as `^[a-z]{2,6}$`, the
      memory paragraph that called the fitted model exact for `ru` and `korean`, and every command given for Windows
      and for Linux or macOS through `python -m`.
- [x] 3.4 `docs/CONFIGURATION.md`, `README.md`, arc42 chapters 04, 06, 07, 08, 09, 11 and 12, and the end-to-end specs
      2, 3, 4, 13 and 16, the spec 16 template and `e2e/README.md` where they quote the allowance.
- [x] 3.5 ADR-010 written, ADR-008 amended where it settles 45 s, and the ADR index updated.

## 4. Verification

- [x] 4.1 `python -m ruff check .` and `python -m ruff format --check .` clean. `python -m mypy src` clean on every
      file this change owns, and reports one error, in `src/config/startup_banner.py`, which task 5.1 closes.
- [x] 4.2 `python -m pytest` with the 100 percent line and branch gate. Everything this change owns passes. The 22
      failures left are all `AttributeError: 'Settings' object has no attribute 'OCR_PAGE_TIMEOUT_SECONDS'` from
      `startup_banner.py` line 265 and `tests/config/test_startup_banner.py` line 63, and the only lines short of
      coverage are in `startup_banner.py` and `main.py` line 62, which the failing lifespan tests stop short of.
      Closes with task 5.1.
      Done 2026-09-24: gate re-run through the module venv, ruff check and format clean, mypy clean on 33 files, pytest 719 passed and 7 skipped at 100 percent line and branch coverage.
- [x] 4.3 `openspec validate fix-ocr-page-resolution --strict` and `openspec validate --all --strict`, both clean.
- [x] 4.4 Linux compatibility: no Windows path literal, separator or Windows-only call in the new code or tests, the
      renderer works on bytes in memory and writes no file, the only temporary path is the existing
      `tempfile.gettempdir()` joined through `pathlib`, and no new test depends on file locking or line endings.
      Checked by grep over every changed file and by reading each. The container is Linux, and `numpy` 2.3.5,
      `pypdfium2` 5.8.0 and `Pillow` 12.2.0 all publish manylinux wheels for Python 3.11.

## 5. Owner-gated and cross-owner work

- [x] 5.1 `src/config/startup_banner.py` line 265 prints `settings.OCR_PAGE_TIMEOUT_SECONDS`, deleted here, and
      `tests/config/test_startup_banner.py` line 63 sets it. The banner's owner replaces the line with one allowance
      per reachable engine, `settings.page_allowance_seconds(pair)` for each pair the banner already lists, and drops
      the monkeypatch. Not edited here, because the file belongs to `upgrade-ocr-to-ppocrv6` task 4.6 in flight.
      Done 2026-09-24: no reference to `OCR_PAGE_TIMEOUT_SECONDS` remains in `src/` or in `tests/config/test_startup_banner.py`, and `startup_banner.py` line 203 prints `settings.page_allowance_seconds(pair)` per pair. Gate green at 719 passed.
- [x] 5.2 Measure one call's peak at the `high` limit on a square 4200 x 4200 page. Done by the coordinator on
      2026-09-24 and recorded in design.md Decision 4: 501 MiB and 16.3 s on the small pair, 510 MiB and 138.3 s on
      the server detector.
- [ ] 5.3 Measure `normal` mode's per-page time on the same synthetic A4 densities and on the 2100 x 2100 page, and
      answer Open Question 1. Needs an inference run the owner starts.
      Partly done 2026-09-24: the 2100 x 2100 px page, the largest `normal` supports, is measured at 150 dpi with detection bounded to 1024 and recorded in design.md under Non-Goals. The `PP-OCRv6_small` pair took 394 MiB peak and 11.3 s with 50 of 50 lines exact, and `PP-OCRv5_server_det` with `eslav_PP-OCRv5_mobile_rec` took 517 MiB and 46.6 s with 42 of 50 exact. Still open: the three A4 densities in `normal` mode, real scans, and Open Question 1.
- [x] 5.4 Reconcile the three overturned requirements named in design.md, "Requirements this change overturns
      elsewhere", in whichever of `stop-ocr-getting-stuck-on-large-jobs` and `read-long-documents` archives first, and
      rerun `openspec validate --all --strict`.
      Done 2026-09-24 in both older changes: the pixel requirement removed from `ocr-input-limits`, the detector bound requirement narrowed in `ocr-memory-bounds`, "Oversized page submitted" replaced in `ocr-job-admission`, and the vacuous scratch-file requirements removed or rewritten.
- [ ] 5.5 Run the ascend-ocr end-to-end specs after a rebuild, in the run scenario the owner chooses from
      `docs/E2E_RUN_SCENARIOS.md`. Not run here: the owner approves every end-to-end run.
- [x] 5.6 Reconcile `read-long-documents` with Decision 8, per the list at the end of design.md's "Requirements this
      change overturns elsewhere". Not edited here, because that change's files belong to other work in flight.
      Done 2026-09-24 in `read-long-documents`: every listed place now names this change as owner of the per-engine allowance and the figures derived from it.

## 6. Preprocessing and `straighten` (Decision 9, owner decisions of 2026-09-25)

- [x] 6.1 Tests first. `tests/service/test_ocr_service.py`: the constructor names all three preprocessing flags and
      `textline_orientation_batch_size=1`, every `predict_iter` call passes all three with unwarping set to the
      request's `straighten`, a straightened and a plain request share one engine, `straighten` reaches the worker
      through `dispatch_ocr_request` and `run_ocr_in_worker`, and `preload_models()` builds every reachable pair exactly
      as the service does. `tests/config/test_config.py`: `reachable_model_pairs()`. `tests/model/test_ocr_models.py`:
      the record round trip, the default for an older record, a non-boolean refused, the result reference field.
      `tests/service/test_job_service.py` and `tests/service/test_job_runner.py`: recorded, echoed in the status
      result, carried to the dispatch. `tests/api/rest/test_rest_endpoints.py`, `tests/api/mcp/test_mcp_server.py`
      and `tests/api/test_cross_surface_limits.py`: accepted, defaulted to `false`, refused when not a boolean,
      advertised on the tool, and recorded identically by both surfaces.
- [x] 6.2 Code. `src/service/ocr_service.py` (`build_engine`, `preload_models`, `TEXTLINE_ORIENTATION_BATCH_SIZE`,
      `straighten` threaded from `dispatch_ocr_request` to `_predict_page`), `src/config/config.py`
      (`reachable_model_pairs`, now also the source of `OCR_WORST_PAGE_ALLOWANCE_SECONDS`), `src/model/ocr_models.py`,
      `src/service/job_service.py`, `src/service/job_runner.py`, `src/api/rest/rest_endpoints.py`,
      `src/api/mcp/mcp_server.py`.
- [x] 6.3 `Dockerfile`: the model download step calls `preload_models()`, so the image carries the default pair, both
      PP-OCRv5 pairs and the three preprocessing models. Checked against the installed library with the models
      already cached: every pair built, no error. The image itself is not rebuilt here.
- [x] 6.4 The line orientation batch checked on a page mixing 31 upright lines, 19 upside-down lines and three labels
      turned 90 degrees, read the way the service reads it, with PaddleOCR's own 10 compute threads because the
      4 that `PADDLE_PDX_CPU_NUM_THREADS` asked for never reached paddlex: 31 of 53 exact at the library's batch of 6
      (19 of 31, 10 of 19, 2 of 3) and 53 of 53 at a batch of 1.
- [x] 6.5 Documentation. ADR-011 written and indexed, `apps/ascend-ocr/AGENTS.md`, `README.md`,
      `docs/CONFIGURATION.md`, `docs/README.md`, `docs/architecture/README.md`, arc42 chapters 06, 09 and 12, and the
      Bruno submit request `docs/api/request/AscendAI/ocr/ocr.yml` (a disabled `straighten` form field, no assertion
      changed).
- [ ] 6.6 Re-measure every timing and memory figure that describes the old preprocessing:
      `MEASURED_WORST_PAGE_SECONDS`, the startup banner's per-call peaks, the per-page time and memory tables in
      ADR-010, AGENTS.md and README.md, and the page allowances derived from them, for a plain request and for a
      straightened one. Owner-gated: the owner is measuring and sends the figures.
      Done 2026-09-25: the owner's container measurement (Linux, 4 CPUs, cgroup `memory.peak`, 3 runs each, image `7b2cb25e7360`) is applied. `MEASURED_WORST_PAGE_SECONDS` holds 28.4 s for `PP-OCRv6_small_det` and 96.0 s for `PP-OCRv5_server_det`, the banner prices plain and straightened calls, the idle engine and the API process from it, and ADR-006, ADR-010, ADR-011, AGENTS.md, README.md, docs/CONFIGURATION.md, the deployment view, `docs/architecture/memory-budget.md` and `docs/DEFECT_REGISTER.md` carry the figures. See section 7.
- [x] 6.7 Gate: `python -m ruff check .`, `python -m ruff format --check .`, `python -m mypy src` and `python -m pytest`
      with the 100 percent line and branch gate, all clean. `openspec validate --all --strict` clean.
- [ ] 6.8 Run the end-to-end specs that submit a straightened photo and a turned page after a rebuild, in the run
      scenario the owner chooses from `docs/E2E_RUN_SCENARIOS.md`. Not run here: the owner approves every end-to-end
      run.

## 7. Container measurement, `ru` and `korean` off, and the language refused at submission (Decision 10, owner decisions of 2026-09-25)

- [x] 7.1 Tests first. `tests/config/test_config.py`: the shipped allowlist without `ru` and `korean`, no language
      override, the measured table at 28.4 s and 96.0 s, every derived duration pinned (127.8 s, 132.8 s, 12,780 s,
      38,340 s), and only the small pair reachable. `tests/service/test_ocr_service.py`: `ru` and `korean` refused
      before any engine is built, and the preload building only the small pair. `tests/config/test_startup_banner.py`:
      the container figures, a straightened call priced with the 1623 MiB overhead, the 209 MiB idle engine, the
      259 MiB API process counted in the service peak, and no warning against a 4 GiB limit. Seen failing (32 and 21
      failures) before the code changed.
- [x] 7.2 Code. `src/config/config.py` (`SUPPORTED_LANGUAGES`, `LANGUAGE_MODEL_OVERRIDES`, `MEASURED_WORST_PAGE_SECONDS`)
      and `src/config/startup_banner.py` (the measurements, the straighten overhead, the idle engine, the API process).
      Tests that exercised the override mechanism install an override through a `tests/conftest.py` fixture.
- [x] 7.3 `compose.yaml`: the `ascend-ocr` memory limit from 12G to 4G.
- [x] 7.4 Tests first, then code: a language outside `SUPPORTED_LANGUAGES` is refused at submission on both surfaces
      with `UNSUPPORTED_LANGUAGE`, REST 400 with the supported languages in the detail, MCP before the URI is fetched,
      no identifier, nothing stored or queued. `ensure_language_supported` in `src/service/job_service.py`,
      `UnsupportedLanguageError` and its handler in `src/api/exception_handlers.py`, the MCP mapping in
      `src/api/mcp/mcp_server.py`. The REST test was seen answering 202 before the change. The worker's check stays.
- [x] 7.5 Documentation: ADR-002 second amendment, ADR-005, ADR-006 third amendment, ADR-007 amendment, ADR-008,
      ADR-010 amendment, ADR-011 amendment and its known reading limits, `apps/ascend-ocr/AGENTS.md`, `README.md` with
      a Known reading limits section, `docs/CONFIGURATION.md`, arc42 chapters 04, 06, 07, 08, 11 and 12,
      `e2e/README.md` where it quotes the allowance, `docs/architecture/memory-budget.md`, `docs/DEFECT_REGISTER.md`
      rows A25 and F24, and this change's design.md and spec.
- [x] 7.6 `ENGINE_CACHE_MAX_SIZE` checked against one reachable pair: the default of 2 stays, because the banner
      prices only reachable engines, so the empty slot costs nothing, and it is the slot a language opted back in would
      use.
- [x] 7.7 Gate: `python -m ruff check .`, `python -m ruff format --check .`, `python -m mypy src` and `python -m pytest`
      with the 100 percent line and branch gate, all clean. `openspec validate --all --strict` clean.
- [ ] 7.8 Bring `ru` and `korean` back: measure `PP-OCRv6_small_det` paired with `korean_PP-OCRv5_mobile_rec` and with
      `eslav_PP-OCRv5_mobile_rec`, with and without `straighten`, for memory, time and exact lines, and restore each
      language through `LANGUAGE_MODEL_OVERRIDES` and `SUPPORTED_LANGUAGES` only if its accuracy holds. Owner-gated:
      needs an inference run the owner starts.
- [ ] 7.9 Rebuild the image and run the ascend-ocr end-to-end specs, spec 1's unsupported-language step included, in
      the run scenario the owner chooses from `docs/E2E_RUN_SCENARIOS.md`. Not run here: the owner approves every
      rebuild and every end-to-end run.
- [x] 7.10 Four defects found during 7.1 to 7.7, fixed. `ascendocr_ocr_requests_total` labels a request with its
      language only when it is supported, and with the fixed value `unsupported` otherwise, so a caller cannot mint
      label values (`request_language_label` in `src/observability/metrics.py`, tests on both surfaces). The startup
      banner takes its engines from `Settings.reachable_model_pairs()`, so it counts the default language's engine and
      prices the same set the image preloads. `docs/architecture/memory-budget.md` counts docling-serve at its 10 GiB
      limit, not 8 GiB, and its limits sum and ratios follow. `read-long-documents` and `upgrade-ocr-to-ppocrv6` mark
      their old OCR figures superseded and point at Decision 10.
- [ ] 7.11 Improve crumpled-photo accuracy (owner decision of 2026-09-25). The baseline is the owner's crumpled phone
      photo read with `straighten=true`: 17 of 21 exact phrases with all 21 lines found, against 14 of 21 and two lines
      lost without straightening, and end-to-end spec 18 passes at 15 of 21. Candidates are a stronger recognition
      model, a better unwarping model, or image cleanup before recognition. Each is measured against that baseline, and
      spec 18's threshold is raised only when the new figure holds. Owner-gated: needs an inference run the owner starts.

## 8. Recognition batch, warm-up read, and the dense page allowance (Decision 11, owner-approved 2026-09-25)

- [x] 8.1 Tests first: the engine is built with `text_recognition_batch_size=1`, the warm-up reads one generated page
      exactly once with unwarping off, and a failed warm-up read fails the warm-up. Seen failing (3 failures) before
      the code changed.
- [x] 8.2 Code: `TEXT_RECOGNITION_BATCH_SIZE` in `build_engine`, and `_warm_up_page` read by
      `OcrService.warm_up_engine` after the engine is built. The Dockerfile's preload goes through the same
      `build_engine`, so it needs no change.
- [x] 8.3 Dense A4 prose pages in English and Polish measured in throwaway 4-CPU containers on image `385d160c20a0`,
      plain, straightened and `normal`, beside the English scan fixture and the sparse 4200 x 4200 page, three runs
      each. Worst minimum 50.4 s, straightened dense English. Worst peak 1972 MiB, below every banner figure.
- [x] 8.4 `MEASURED_WORST_PAGE_SECONDS` for `PP-OCRv6_small_det` to 50.4 s, the pinned derived values in
      `tests/config/test_config.py`, `tests/config/test_startup_banner.py` and `tests/service/test_job_runner.py`
      (226.8 s, 231.8 s, 22,680 s, 68,040 s), and every document quoting the page time or allowance.
- [x] 8.5 Gate: `python -m ruff check .`, `python -m ruff format --check .`, `python -m mypy src` and `python -m pytest`
      with the 100 percent line and branch gate, all clean.

## 9. Service defects found by the 2026-09-25 end-to-end run

- [x] 9.1 Paddle's thread cap. Tests first: `TestEngineConstruction::test_an_engine_runs_as_many_cpu_threads_as_the_container_may_use`
      in `tests/service/test_ocr_service.py` and `TestApplyCpuThreadLimit` in `tests/config/test_cpu_limits.py`, seen
      failing before the code changed. Code: `build_engine` passes `cpu_threads=detect_cpu_limit()`, because PaddleOCR
      always passes its own `DEFAULT_CPU_THREADS` of 10 and paddlex reads `PADDLE_PDX_CPU_NUM_THREADS` only when no
      value is passed. `apply_cpu_thread_limit` no longer writes that variable, caps OpenCV only, and its docstring no
      longer claims the variable reaches Paddle. Documented in the deployment view and in ADR-011's measurement note.
- [x] 9.2 A cancel no longer holds its answer for the worker replacement. Tests first: the REST cancel answers within
      2 s while a replacement is still running, reads `cancelled`, reports `accepting_work` false meanwhile and true
      after, the replacement is counted as in progress before it first runs, a failed replacement is logged, and
      shutdown waits for a replacement before stopping the pool. Code: `request_worker_replacement_for_cancel` and
      `wait_for_worker_replacements` in `src/service/ocr_service.py`, `JobRunner.cancel` made synchronous, the
      lifespan in `src/main.py`. The event loop was not held before either: the replacement already ran in the
      default executor, and Uvicorn stamps `Date` when a request arrives. ADR-004 amendment of 2026-09-25.
- [x] 9.3 An expected refusal is one WARNING line naming its code, with no traceback. Tests first, with records
      captured from the root logger and the non-propagating `fastmcp` logger: `TestRefusalLogging` in
      `tests/api/test_exception_handlers.py` and `tests/api/mcp/test_mcp_server.py`. Code: `log_refusal` in
      `src/api/exception_handlers.py` for both surfaces, and `_mcp_error_codes` raising FastMCP's `ToolError` at
      DEBUG, chained to the service's exception. An unexpected exception keeps ERROR with its traceback. ADR-002
      third amendment.
- [x] 9.4 `/ready` drops `queue_depth`, which counted waiters on an admission gate whose only client is the job
      runner and so read 0 beside `jobs_queued` 2 and 8. `jobs_queued` and `jobs_running` report the waiting work.
      Test first: `TestReadyEndpoint::test_ready_reports_the_queue_only_through_the_job_counters`. README, module
      AGENTS.md, the runtime view, the glossary and ADR-004 updated.
- [x] 9.5 Gate: `python -m ruff check .`, `python -m ruff format --check .`, `python -m mypy src` and `python -m pytest`
      with the 100 percent line and branch gate, all clean, then `openspec validate --all --strict`.
- [x] 9.6 A dispatch releases the admission permit to the gate it acquired. `start_worker_pool` replaces the gate on
      every rebuild and the dispatch released whichever gate was current, so a document read across a rebuild added
      a permit to the new gate. Test first:
      `TestDispatchOcrRequest::test_a_dispatch_across_a_pool_rebuild_releases_the_gate_it_acquired` in
      `tests/service/test_ocr_service.py`, seen failing with the old gate left at 0. Code: `_await_admission` returns
      the gate it acquired and `dispatch_ocr_request` releases that one.
- [x] 9.7 The `ascendocr_ocr_queue_depth` gauge is removed. It counted waiters on the admission gate and read 0
      whatever was queued, and `ascendocr_job_queue_documents` and `ascendocr_job_queue_pages` already report the
      waiting work, so it was not redefined as a copy. No dashboard under `infra/observability` queried it. Test
      first: `TestJobMetrics::test_waiting_work_is_reported_only_by_the_job_queue_gauges` in
      `tests/observability/test_metrics.py`. The `_queue_depth` counter in `src/service/ocr_service.py` went with it.
- [x] 9.8 A cancelled document that finishes before the kill lands no longer hands the next document to the worker
      being killed. Tests first: `TestCancellation::test_the_next_document_waits_for_the_worker_a_cancel_is_replacing`
      in `tests/service/test_job_runner.py`, seen failing with the next document dispatched before the replacement
      finished, and `TestCancellationReplacesTheWorker::test_a_waiter_that_is_cancelled_leaves_the_replacement_running`
      in `tests/service/test_ocr_service.py`. Code: `JobRunner._take_one_turn` starts with
      `wait_for_worker_replacements`, which now uses `asyncio.wait` so a stopped runner never cancels a replacement.
      The `DELETE` still answers at once. README, module AGENTS.md, the runtime view and ADR-004 updated.
- [x] 9.9 ADR-011's two measurement lines, the Context and Decision 9 in `design.md`, and task 6.4 no longer claim
      4 threads: `PADDLE_PDX_CPU_NUM_THREADS=4` never reached paddlex, so those runs used PaddleOCR's own 10 compute
      threads, capped by the host's cores.
- [x] 9.10 The `ascendocr_ocr_queue_wait_seconds` histogram is removed. It timed the wait on the admission gate, which
      the runner never waits on, and `ascendocr_job_queue_wait_seconds` already times the real wait. No query or
      dashboard in the repository named it. Test first: `TestJobMetrics::test_the_wait_is_measured_only_in_the_job_queue`.
      `test_budget_expired_between_acquire_and_dispatch_never_dispatches` now counts three clock reads, not four.
- [x] 9.11 A cancel that lands while the runner reads a document's submitted bytes is kept. Proven first by
      `TestCancellation::test_a_cancel_while_the_submitted_bytes_are_read_is_kept` in `tests/service/test_job_runner.py`,
      which failed both ways: the cancelled document was read to `succeeded` when its bytes were already read, and
      failed as `INTERNAL_ERROR` when the cancel had removed them first. Store tests first too: the three
      `test_starting_*` tests in `tests/service/test_job_store.py`. Code: `JobStore.start` moves a record to `running`
      only while it reads `waiting`, a compare-and-set with no await between check and write. The runner skips a
      document `start` refuses, writes a missing input only over an unfinished record, and asks for a worker
      replacement only when the cancelled document was dispatched (`_dispatched_job_id`). The REST cancel tests and
      `test_cancelling_dispatched_work_replaces_the_worker_once` seat the document as dispatched.
- [x] 9.12 `openspec/changes/stop-ocr-getting-stuck-on-large-jobs/tasks.md` task 2.4 names the renamed
      `test_start_worker_pool_resets_gate`.
- [x] 9.13 Gate: `python -m ruff check .`, `python -m ruff format --check .`, `python -m mypy src` and `python -m pytest`
      with the 100 percent line and branch gate, all clean, then `openspec validate --all --strict`.
- [ ] 9.14 Rebuild the image, measure the page times again with the thread cap in force, and run the ascend-ocr
      end-to-end specs in the run scenario the owner chooses from `docs/E2E_RUN_SCENARIOS.md`. The rebuild and the
      measurement are done (9.15 to 9.18). The end-to-end run is still open.
- [x] 9.15 The page times measured again with the thread cap in force, on image `9c100951f59b`, in throwaway 4-CPU
      containers with the same probe as 8.3: the six cases of 8.3 plus the flat phone photo read with `straighten`,
      three runs each, host CPU sampled every 2 s and averaging 54 to 92 percent across the runs. Worst minimum 25.1 s,
      the dense Polish page, with the straightened dense English page at 24.9 s. Worst peak 2636 MiB (the photo), below
      every banner figure.
- [x] 9.16 `MEASURED_WORST_PAGE_SECONDS` for `PP-OCRv6_small_det` to 25.1 s, tests first: the pinned derived values in
      `tests/config/test_config.py`, `tests/config/test_startup_banner.py` and `tests/service/test_job_runner.py`
      (112.95 s, 117.95 s, 11,295 s, 33,885 s), seen failing (19 failures) before the constant changed. Every document
      quoting 50.4 s, 226.8 s, their derived values or the dense-page times updated, recording that the earlier figures
      were measured with PaddleOCR's 10 threads throttled under 4 CPUs, ADR-011 third amendment.
- [x] 9.17 `/openapi.json` reports the package version `/health` reports. Test first:
      `TestOpenApiDocument::test_openapi_reports_the_same_version_as_health` in `tests/api/rest/test_rest_endpoints.py`,
      seen failing with `0.1.0` against `0.2.1`. Code: `create_app` passes `version=SERVICE_VERSION` to `FastAPI`. The
      agent's `src/test/resources/ascend-ocr/openapi-contract.json` re-captured from the rebuilt container, and the
      agent's `*AscendOcr*` tests pass. Note 2026-09-25: that file no longer exists. It was deleted and replaced by the
      Pact contract `contracts/pacts/ascend-agent-ascend-ocr.json`, written by the agent's `AscendOcrClientPactTest`.
- [x] 9.18 Gate: `python -m ruff check .`, `python -m ruff format --check .`, `python -m mypy src` and `python -m pytest`
      with the 100 percent line and branch gate, all clean, then `openspec validate --all --strict`. Image rebuilt and
      only `ascend-ocr` recreated, healthy, banner page allowance 113.0 s (112.95 s at one decimal), job list and
      result bucket empty.
