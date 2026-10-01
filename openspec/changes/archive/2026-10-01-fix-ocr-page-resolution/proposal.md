## Why

Three defects in how ascend-ocr turns a submission into the pixels its engine reads. The owner approved fixing all
three as one bug fix.

**PDF pages are read at a resolution nobody can change.** PaddleOCR rasterizes every PDF page itself at
`PADDLE_PDX_PDF_RENDER_SCALE`, 2.0 on PDF points, which is 144 dots per inch. The value is read once when
`paddlex/utils/flags.py` is imported, so it is fixed for the life of the process and cannot vary per request.
[ADR-005](../../../apps/ascend-ocr/docs/architecture/decisions/ADR-005-fixed-pdf-render-resolution.md) accepted that
on memory grounds, and says itself that 144 dpi puts body text at the edge of what is recognised dependably.

**A normal scan is refused instead of read.** `OCR_MAX_INFERENCE_PIXELS` is 2,500,000, and an A4 page at 300 dpi is
2480 x 3508, about 8.7 megapixels, so the service answers `FILE_TOO_LARGE` for the most ordinary input a scanner
produces. The owner calls that a bug: oversized input must be shrunk to the largest size the service supports and
then read, and only genuinely absurd input refused. `src/api/limits.py` also sets Pillow's process-wide
`Image.MAX_IMAGE_PIXELS` from that same value, so the decompression-bomb guard and the inference ceiling are one
number with two jobs.

**A caller has no say in quality.** There is no parameter. The owner wants a per-request mode with two values,
`normal` and `high`.

**One page allowance cannot cover two engines 8.5 times apart.** Found by the measurement this change's worst case
needed. `OCR_PAGE_TIMEOUT_SECONDS` is 45 s for every page, 4.5 times the 10.0 s the small pair took on an A4 page. On
the 4200 x 4200 px page `high` mode admits, the small pair took 16.3 s and `PP-OCRv5_server_det`, which `ru` and
`korean` load, took 138.3 s. Every such Russian or Korean page would blow its allowance and fail the document.

The ceiling was set against a memory model that no longer describes the engine. Measured on 2026-09-24 against
PaddleOCR 3.7.0 and `PP-OCRv6_small`, one A4 page costs about 440 MB whether it is rendered at 144 or at 300 dpi,
once detection is bounded to a long side of 1536, and takes 4.1 s at six lines to 10.0 s at fifty at 300 dpi. The
research behind this change adds two facts. Recognition crops come from the full-resolution page, because the paddlex
OCR pipeline rescales the detected boxes back onto the original image before cropping. And the ratio between the
rendered page and the detector bound is itself a quality parameter: at a 3.3x downscale 28 of 28 lines read cleanly,
and at 6.85x every line was still found and every line read as garbage.

## What Changes

- **The service renders PDF pages itself**, with pypdfium2, one page at a time, at the resolution the request's mode
  names, and hands each page to PaddleOCR as an in-memory array. The library's own rasterizer and its fixed 144 dpi
  stop being on the path. Raster images are decoded by the service with Pillow the same way. The per-page deadline
  check in `OcrService._predict_pages` stays where it is, before each page is produced.
- **A `quality` parameter on job submission**, as a form field on `POST /v1/ocr/jobs` and an argument on the
  `ocr_submit` tool, with the values `normal` and `high`. Each value names a locked pair of render resolution and
  detector bound: `normal` is 150 dpi with a detector bound of 1024, `high` is 300 dpi with a detector bound of 1536.
  A caller chooses a mode and never a number. The default is `high`, and design.md Decision 2 records why.
- **The pairs are two named settings**, `OCR_QUALITY_NORMAL` and `OCR_QUALITY_HIGH`, each holding one pair written as
  `<dpi>:<detector bound>`. An operator can retune a pair and cannot configure the two halves of it independently.
  A pair whose downscale ratio exceeds the largest one measured to read cleanly is refused at startup.
- **Oversized input is shrunk, then read.** Every page and every image frame is brought down to the largest size its
  mode supports, which is the longest standard page the service targets, US Legal at 14 inches, at the mode's
  resolution: 2100 px on the long side for `normal`, 4200 px for `high`. A PDF page larger than that is rendered at a
  proportionally lower scale, and an image larger than that is downscaled with its aspect ratio kept. Nothing is ever
  scaled up.
- **Only absurd input is refused, on its own setting.** `OCR_MAX_INFERENCE_PIXELS` is deleted. A new
  `OCR_MAX_SOURCE_PIXELS`, defaulting to Pillow's own decompression-bomb threshold of 89,478,485 pixels, refuses a
  raster image that declares more pixels than that in any frame, at submission, from the header, before anything is
  decoded. Pillow's `Image.MAX_IMAGE_PIXELS` is set from this setting and nothing else. A PDF page is never refused
  on pixels, because the service decides how many pixels it renders.
- **`OCR_DETECTOR_MAX_SIDE` is deleted.** The detector bound is no longer one process-wide value fixed at engine
  construction. It is passed on every `predict` call from the request's mode, which PaddleOCR supports per call, so
  both modes share one cached engine and the engine cache key stays the model pair.
- **A multi-page TIFF is counted as the pages it holds.** PaddleOCR used to read every frame of a TIFF while the
  service counted it as one page, so its reading budget, its progress and its place in the page-bounded queue were
  all computed for one page. Rendering in the service makes the frame count the page count.
- **The scratch file is gone.** The worker wrote every submission to `OCR_SCRATCH_DIR` only because PaddleOCR read a
  path. It now reads arrays rendered from the bytes in memory, so `OCR_SCRATCH_DIR`, the scratch sweep, and the
  startup sweep call in `main.py` are removed as orphans of this change.
- **Each engine is allowed its own time.** `OCR_PAGE_TIMEOUT_SECONDS` is replaced by `OCR_PAGE_ALLOWANCE_HEADROOM`,
  default 4.5, the rule the 45 s was derived with. A page is allowed that multiple of the worst page measured on the
  detection model that reads it, 73.35 s on the small pair and 622.35 s on the server detector, from one table of
  measured figures in `config.py`. A document's reading budget, the reclamation grace, the poll hint and
  `Retry-After` use each document's own allowance. The reading ceiling and the maximum lifetime use the slowest
  engine any supported language can load, because they bound every document.
- **Every preprocessing step is named, and straightening is a request option** (owner decisions of 2026-09-25,
  Decision 9). The engine no longer inherits PaddleOCR's defaults, which unwarped every page and read a clean A4 page
  as 9 of 50 lines. Every request gets page orientation and text line orientation, the line classifier sees one line
  at a time, and unwarping runs only when a caller sends the new optional boolean `straighten` on `POST /v1/ocr/jobs`
  or `ocr_submit`, meant for phone photos of bent, curled or crumpled paper. The image pre-downloads every model the
  service can load.
- `FILE_TOO_LARGE` keeps its code and its 400. What raises it changes: the byte cap, the source pixel ceiling, and the
  page ceiling. An oversized page or image no longer raises it at all.

Not breaking on either surface. `quality` and `straighten` are optional with defaults, the result reference gains
two additive fields, `quality` and `straighten`, and a submission that used to succeed still succeeds. Submissions that used to be refused for
exceeding 2.5 megapixels are now read. A deployment that sets `OCR_MAX_INFERENCE_PIXELS`, `OCR_DETECTOR_MAX_SIDE` or
`OCR_SCRATCH_DIR` or `OCR_PAGE_TIMEOUT_SECONDS` in its environment has them ignored rather than refused, because
`Settings` ignores unknown variables. The maximum lifetime of a record in a non-terminal state grows from 13,500 s to
186,705 s at the defaults, because a queue full of Russian or Korean pages can legitimately take that long.

## Capabilities

### New Capabilities

- `ocr-page-resolution`: how a submitted document becomes the pixels one inference reads, the two quality modes and
  the locked pair each carries, what is shrunk and to what size, what is refused as absurd and on which setting, and
  how a multi-page image is counted, which preprocessing every page gets, and when a page is straightened.

### Modified Capabilities

None under `openspec/specs/`. No capability there covers ascend-ocr yet. Three requirements in unarchived changes are
overturned by this one and design.md's "Requirements this change overturns elsewhere" names each, with the edit the
first of them to archive has to carry.

## Impact

Code, under `apps/ascend-ocr/`:

- `src/config/config.py`: `QualityMode`, `DEFAULT_QUALITY`, the `QualityProfile` value object with its pair
  validation, `OCR_QUALITY_NORMAL`, `OCR_QUALITY_HIGH`, `OCR_MAX_SOURCE_PIXELS` and `Settings.quality_profile()`.
  `OCR_MAX_INFERENCE_PIXELS`, `OCR_DETECTOR_MAX_SIDE` and `OCR_SCRATCH_DIR` are deleted. `OCR_PAGE_TIMEOUT_SECONDS`
  is replaced by `OCR_PAGE_ALLOWANCE_HEADROOM`, `MEASURED_WORST_PAGE_SECONDS`, `Settings.model_pair()`,
  `Settings.page_allowance_seconds()`, `Settings.reclamation_grace_seconds()` and
  `OCR_WORST_PAGE_ALLOWANCE_SECONDS`.
- `src/api/limits.py`: the source pixel ceiling replaces the inference ceiling, per frame, and a multi-page TIFF
  reports its frame count. `PDF_RENDER_SCALE` is deleted, because the service no longer predicts the library's
  rasterization.
- `src/service/page_renderer.py`: new. Renders PDF pages and decodes image frames at a mode's size, one page at a
  time, as the BGR arrays PaddleOCR reads.
- `src/service/ocr_service.py`: reads rendered pages instead of a scratch path, passes the mode's detector bound on
  every call, and carries `quality` from dispatch to the worker. The scratch file and its sweep are removed.
- `src/service/job_service.py`, `src/service/job_runner.py`, `src/model/ocr_models.py`,
  `src/api/rest/rest_endpoints.py`, `src/api/mcp/mcp_server.py`, `src/main.py`: the `quality` parameter from both
  surfaces through the record to the worker, and the removed startup sweep. The runner charges each document its own
  engine's allowance and computes the poll hint and `Retry-After` from allowed seconds ahead rather than pages.
- `src/service/ocr_service.py`, `src/config/config.py` and the files above again for `straighten`: every
  preprocessing flag named on the constructor and on every call, `straighten` threaded from both surfaces to the call,
  and `preload_models()` over `Settings.reachable_model_pairs()`. `Dockerfile`: the download step calls it.
- `pyproject.toml`: `numpy` is declared at the version already installed, because the service now builds arrays from
  decoded images itself rather than only through a dependency.

Tests: every file above has its test file updated or created under `apps/ascend-ocr/tests/`, test first. The gate is
100 percent line and branch coverage.

Docs: `apps/ascend-ocr/AGENTS.md`, `apps/ascend-ocr/README.md`, `apps/ascend-ocr/docs/CONFIGURATION.md`, arc42
chapters 04, 06, 07, 08, 09, 11 and 12, the end-to-end specs that quote the allowance, a new
[ADR-010](../../../apps/ascend-ocr/docs/architecture/decisions/ADR-010-quality-modes-and-service-side-rendering.md),
a new [ADR-011](../../../apps/ascend-ocr/docs/architecture/decisions/ADR-011-explicit-preprocessing-and-straighten.md)
for the preprocessing decision, the Bruno submit request, an amendment to ADR-008 where it settles 45 s, and [ADR-005](../../../apps/ascend-ocr/docs/architecture/decisions/ADR-005-fixed-pdf-render-resolution.md)
and [ADR-006](../../../apps/ascend-ocr/docs/architecture/decisions/ADR-006-detector-input-bound.md), both amended as
superseded where this overturns them. `AGENTS.md` also has `DEFAULT_LANGUAGE` corrected to `^[a-z]{2,6}$`, which is
what the code has always accepted.

One consumer outside this change's files: `src/config/startup_banner.py`, which is being reworked concurrently by
`upgrade-ocr-to-ppocrv6` task 4.6 and is not edited here. It has moved to the quality profiles, and still prints
`OCR_PAGE_TIMEOUT_SECONDS`. Task 5.1 names the replacement it needs.

## Relevant Skills

Load before implementing:

- `/python-patterns`, `/tdd-workflow`, `/ai-regression-testing`
- `/coding-standards`, `/code-formatter`, `/review-duplication`
- `/api-design` for the new form field and tool argument
- `/security-review` for the decompression-bomb guard
- `/performance-optimization` for the measure-before-claiming discipline behind the mode pairs
- `/build-dependency-management` for the `numpy` declaration
- `/architecture-decision-records` for the two amendments
