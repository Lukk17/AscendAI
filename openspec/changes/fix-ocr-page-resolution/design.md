## Context

Every figure below says where it came from. Five sources are used and nothing else.

1. **The owner's measurements of 2026-09-24**, on this host, PaddleOCR 3.7.0, `PP-OCRv6_small_det` and
   `PP-OCRv6_small_rec`, one synthetic A4 page. Peak memory 439, 439 and 441 MB for 6, 20 and 50 lines at 300 dpi
   with detection bounded to a long side of 1536, and the same flat figure at 144 dpi. Wall time 4.1 s, 6.0 s and
   10.0 s at 300 dpi. These are the numbers `read-long-documents` design.md already derives the per-page allowance
   from, and this change reuses them rather than restating a second account.
2. **The research findings supplied with the bug report.** Recognition crops come from the full-resolution image:
   the paddlex OCR pipeline (`paddlex/inference/pipelines/ocr/pipeline.py`) detects on the resized image and rescales
   the boxes back onto the original before cropping. At a detector bound of 512, a page rendered at 144 dpi (A4 long
   side 1684 px, a 3.3x downscale) read 28 of 28 lines cleanly, and the same page at 300 dpi (long side 3508 px, a
   6.85x downscale) had every line found and every line read as garbage.
3. **The coordinator's measurement of 2026-09-24** on the largest page `high` supports, recorded in Decision 4, and
   the measurement of the same day on the largest page `normal` supports, recorded under Non-Goals.
4. **The installed tree**, `apps/ascend-ocr/.venv`, read directly. `paddlex/utils/flags.py` reads
   `PADDLE_PDX_PDF_RENDER_SCALE` once at import with a default of 2.0. `ImageBatchSampler` renders PDFs through
   `PDFReaderBackend`, which calls `page.render(scale=...).to_numpy()` on a pypdfium2 page after `init_forms()`, and
   reads multi-frame TIFFs frame by frame. `PaddleOCR.predict_iter` accepts `text_det_limit_type` and
   `text_det_limit_side_len` per call (`paddleocr/_pipelines/ocr.py`). pypdfium2 5.8.0 returns a three-channel BGR
   array from `to_numpy()` on a default render, checked with a red test page, which is the channel order PaddleOCR
   reads.
5. **The preprocessing measurements of 2026-09-25**, PaddleOCR 3.7.0 with `PADDLE_PDX_CPU_NUM_THREADS=4` set, which
   paddlex never read, so the engine ran PaddleOCR's own 10 compute threads, capped by the host's cores, on synthetic pages,
   on the argent-saga fixture turned 90 and 180 degrees, and on the phone photos in
   `apps/ascend-ocr/e2e/fixtures/straightening-photo-*.jpg`, recorded in Decision 9 and ADR-011.
6. **The container measurement of 2026-09-25**, a Linux container with 4 CPUs, image `7b2cb25e7360`, PaddleOCR 3.7.0,
   the cgroup's `memory.peak`, worst of three runs for memory and fastest of three for time, recorded in Decision 10.
   It supersedes every memory and time figure from sources 1, 3 and 5: the probe behind those sampled memory at
   intervals and missed the peak.

The ratio this design uses throughout is the rendered page's long side in pixels divided by the detector bound. It is
the factor detection downscales the page by before it looks at it.

## Goals / Non-Goals

**Goals:**

- A page's rendering resolution is chosen per request, from a small set of named modes.
- The two numbers a mode carries cannot be mismatched by a caller, and cannot be configured by an operator into a
  pair the evidence says reads garbage.
- An oversized page or image is read at the largest size its mode supports rather than refused.
- The only pixel refusal left is a decompression-bomb guard, on its own setting.

**Non-Goals:**

- Measuring `normal` mode on A4 pages or on real scans. Its worst case was measured on 2026-09-24: a synthetic
  2100 x 2100 px page, the largest `normal` supports, carrying 50 lines, rendered at 150 dpi with detection bounded to
  1024. The `PP-OCRv6_small_det` / `PP-OCRv6_small_rec` pair peaked at 394 MiB in 11.3 s with 50 of 50 lines exact,
  and `PP-OCRv5_server_det` with `eslav_PP-OCRv5_mobile_rec` peaked at 517 MiB in 46.6 s with 42 of 50 exact. A4
  pages at the three densities have not been timed in `normal` mode yet, and real scans are still unmeasured. Task 5.3
  carries both. The startup banner prices `normal` from this exact measurement, so one call at the defaults is the
  worst engine plus the one idle engine a cache of two holds, 517 + 143 = 660 MiB. Superseded by Decision 10: in the
  container the small pair peaks at 858 MiB in 18.3 s on this page, and the banner prices the service at 3118 MiB.
- Re-deriving the startup banner's memory estimate. That is `upgrade-ocr-to-ppocrv6` task 4.6, owned elsewhere.
- Changing the page ceiling, the queue bounds or the worker count. The per-page allowance does change, and only
  because the measurement this change needed showed one number could not cover two engines (Decision 8).
- Letting a caller choose a resolution or a detector bound as a number.

## Decisions

### Decision 1: Render in the service, one page at a time

The service renders PDF pages with pypdfium2 and decodes raster images with Pillow, and passes each page to
`PaddleOCR.predict_iter` as an array. This is the one change that makes resolution a per-request value at all:
`PADDLE_PDX_PDF_RENDER_SCALE` is read once per process, so no amount of configuration on the library side could make
it vary between two requests served by the same worker.

It keeps the deadline seam. `_predict_pages` already checks the budget before it pulls each page, and the page it
pulls is now rendered at that moment, so the check still precedes both the rendering and the inference of the next
page. Memory stays one page at a time: the renderer is a generator and each page's array is released before the next
is produced.

It also removes the scratch file. The worker wrote every submission to disk only because the library read a path.
The bytes are already in the worker's memory as the pickled argument, pypdfium2 opens bytes directly, and Pillow
reads from a buffer, so `OCR_SCRATCH_DIR`, `sweep_scratch_dir` and the startup sweep in `main.py` have nothing left to
do and are removed with the helper that chose the file's suffix.

Parity with what the library did, kept deliberately: `init_forms()` before rendering so form fields are drawn, BGR
channel order, EXIF orientation applied to images (which `cv2.imread` did by default), and every frame of a TIFF read
as a page (which `ImageBatchSampler` did through its TIFF reader). Every other raster format is read at its first
frame, which is what `cv2.imread` did.

Rejected: setting `PADDLE_PDX_PDF_RENDER_SCALE` in the environment. It moves the fixed value rather than removing the
fixity, and every request pays for the higher resolution whether it asked or not.

Rejected: one engine per mode, each constructed with its own `text_det_limit_side_len`. It doubles the engine cache
for a value the library already accepts per call, and the cache is sized in engines.

### Decision 2: Two modes, locked pairs, `high` by default

| Mode | Render resolution | Detector bound | A4 long side and ratio | US Legal long side and ratio |
|---|---|---|---|---|
| `normal` | 150 dpi | 1024 | 1754 px, 1.71x | 2100 px, 2.05x |
| `high` (default) | 300 dpi | 1536 | 3508 px, 2.28x | 4200 px, 2.73x |

The research proposed these two pairs and described both as a ratio near 2.3. That holds for `high` on A4 and not
for `normal`, which is 1.71x on A4. The difference does not matter to the choice: both pairs sit below the 3.3x the
research measured as reading cleanly on every page size the service targets, with `normal` further below it than
`high`. A lower ratio means detection sees the page closer to its rendered size, which costs detection time and buys
box precision.

`high` is the default, for four reasons taken from the evidence rather than from preference.

1. It is the configuration that was measured. 300 dpi with a bound of 1536 is exactly the setup behind the 440 MB and
   the 4.1 s to 10.0 s, and its largest page is the 4200 x 4200 px one measured for Decision 4, from which every page
   allowance in Decision 8 is derived. `normal` is measured only on its own largest page, the 2100 x 2100 px square
   under Non-Goals, and not on A4 or on real scans.
2. It costs nothing in memory. Detection sees at most 1536 px on its long side in both 144 dpi and 300 dpi runs, and
   the measured peak is flat across the two.
3. It keeps the detector bound the owner already settled on real documents in ADR-006, 1536, so the default changes
   what recognition reads and not what detection finds.
4. The defect being fixed is that 144 dpi is at the edge for body text. `normal` at 150 dpi is that same edge, four
   percent higher. Making it the default would ship the defect again under a new name.

Decision 10 supersedes the figures in reasons 1 and 2. `high` does cost memory: its largest page peaks at 1236 MiB
against 858 MiB for `normal`'s. It stays the default for reasons 3 and 4.

`normal` exists for the caller who knows its text is large and wants the cheaper read. Its detector input is 1024 on
the long side against 1536, which is under half the pixels, and its recognition crops come from a page with a
quarter of `high`'s pixels, so it is faster by construction. On each mode's largest page it took 11.3 s against
16.3 s on the small pair and 46.6 s against 138.3 s on the server detector, and in the container 18.3 s against
24.6 s on the small pair (Decision 10). How much faster it is on A4 and on real scans is task 5.3.

Rejected: a numeric `dpi` parameter. It is the lever ADR-005 rejected for good reason, a caller multiplying the cost
of a shared single worker, and it gives the caller half of a pair it cannot see the other half of.

### Decision 3: A pair is one setting, and a pair that reads garbage is refused at startup

`OCR_QUALITY_NORMAL` and `OCR_QUALITY_HIGH` each hold one pair, `<dpi>:<detector bound>`, parsed into a frozen
`QualityProfile`. There is no setting for either number on its own, so an operator retuning `high` states both halves
in one value and cannot change one while forgetting the other.

`QualityProfile` refuses a pair whose worst ratio exceeds 3.3, the largest downscale measured to read cleanly. The
worst ratio is taken at the largest page the mode supports (Decision 4), so it holds for every page the mode will
ever read. `300:1024`, for example, would be 4.1x at US Legal and is refused with a message naming both numbers.
The ceiling is `MAX_DETECTOR_DOWNSCALE_RATIO` in `config.py`, a named constant rather than a setting, because it is a
measured fact about the model and not an operating preference. Anything between 3.3x and 6.85x is unmeasured, and
the guard refuses it rather than guessing which side of the line it falls on.

### Decision 4: Oversized input is shrunk to the largest page the mode supports

The largest size a mode supports is the longest standard page this service targets, US Legal at 14 inches, at the
mode's resolution: 2100 px for `normal` and 4200 px for `high`. It is `LARGEST_PAGE_LONG_SIDE_INCHES` in `config.py`
and `QualityProfile.max_long_side_pixels`.

- A PDF page is rendered at the mode's resolution, or at the lower scale that brings its long side down to that size
  if the page is physically larger than US Legal. An A0 poster in `high` mode renders at 4200 px on its long side
  instead of 14043.
- An image frame whose long side exceeds that size is downscaled to it, keeping its aspect ratio, with Pillow's
  `thumbnail`, which also uses JPEG draft decoding so a large JPEG is decoded at a reduced scale in the first place.
- Nothing is scaled up. A 150 dpi scan read in `high` mode is read at its own pixels.

Rejected: an area cap, the shape `OCR_MAX_INFERENCE_PIXELS` had. The ratio evidence is about the long side, because
the detector bound is a long-side bound, so the size a mode supports is stated in the same unit.

Rejected: refusing a PDF page above some physical size. The service chooses how many pixels it renders, so a large
page costs no more than a US Legal one after this change.

Measured by the coordinator of this change on 2026-09-24, PaddleOCR 3.7.0, a synthetic 4200 x 4200 px page
(17.64 megapixels, the largest `high` supports), 50 lines, detection bounded to 1536:

| Engine | Peak | Wall time | Lines exact |
|---|---|---|---|
| `PP-OCRv6_small` pair | 501 MiB | 16.3 s | 50 of 50 |
| `PP-OCRv5_server_det` + `eslav_PP-OCRv5_mobile_rec` | 510 MiB | 138.3 s | 42 of 50 |

Memory barely moves from the A4 page's 440 MB at twice the pixels, which is what a bounded detector predicts. Time
does move, and the server detector's figure exposed the defect Decision 8 fixes.

Superseded by Decision 10. Measured in the container, the small pair peaks at 1236 MiB in 24.6 s on this page and at
1016 MiB on the A4 page, and `PP-OCRv5_server_det` at 12754 MiB in 96.0 s. The 440 MB figure missed the peak.

### Decision 5: One pixel refusal, for absurd input, on its own setting

`OCR_MAX_SOURCE_PIXELS` defaults to 89,478,485, which is Pillow's own `MAX_IMAGE_PIXELS` default and the scale Pillow
itself treats as a decompression bomb. It sits above A3 at 600 dpi, 7016 x 9921 or 69.6 megapixels, the largest
legitimate scan this design imagines anyone sending. It is enforced at submission, from the header, on every frame of
a multi-frame image, before any pixel buffer exists, and it raises `FILE_TOO_LARGE` with a detail naming the frame's
pixel count and the setting.

Pillow's process-wide `Image.MAX_IMAGE_PIXELS` is set from this setting and from nothing else, in both the API process
and the worker. So the explicit check and Pillow's own guard agree on one number. Pillow still raises on its own above
twice that value during `Image.open`, and that is mapped to the same refusal.

The worst image the ceiling admits costs its full decode in the worker before it is shrunk: about 358 MB for an
RGBA frame at the ceiling and about 268 MB more for its RGB conversion. That is arithmetic, not measurement, and it
is the reason the ceiling stays at Pillow's own threshold rather than higher.

PDFs are not subject to it, for the reason Decision 4 gives.

### Decision 6: The detector bound travels with the request, not with the engine

`_get_engine` no longer passes `text_det_limit_type` or `text_det_limit_side_len` to the constructor. `_predict_page`
passes `text_det_limit_type="max"` and the mode's bound to every `predict_iter` call. The engine cache is still keyed
by the model pair, now because the bound is not a construction argument at all rather than because every engine in a
process happens to share one.

Unset is no longer possible. ADR-006 allowed `OCR_DETECTOR_MAX_SIDE` to be unset to restore the library's own
behaviour, which is a minimum-side limit that only ever scales an image up. Every mode now names a bound, and the
startup guard in Decision 3 would refuse an unbounded one anyway.

### Decision 7: `quality` is carried end to end and recorded

`quality` is a required argument from `dispatch_ocr_request` down to `OcrService.process_file`, never defaulted inside
the plumbing, so a caller's choice cannot be silently dropped on the way to the worker. It is defaulted exactly once
per surface, at the edge, from `DEFAULT_QUALITY`. `JobRecord` persists it, with the same default so a record written
before this change still reads, and `JobResultReference` reports it beside `language`, because a caller that took the
default should be able to see which mode read its document.

### Decision 8: A page is allowed its own engine's time

`OCR_PAGE_TIMEOUT_SECONDS` was one allowance, 45 s, for every page. It was 4.5 times the 10.0 s the small pair took on
the fifty line A4 page, and it was never measured against the server detector. On the largest page `high` supports
the small pair took 16.3 s and the server detector 138.3 s, so every Russian or Korean page in `high` mode would blow
the allowance and fail its document, and even the small pair's worst page used 2.8 of the 4.5 headroom.

The allowance becomes `OCR_PAGE_ALLOWANCE_HEADROOM` times the worst page measured on the detection model that reads
the page. The headroom is 4.5, the rule the 45 s was derived with, and the measured figures live in one table,
`MEASURED_WORST_PAGE_SECONDS` in `config.py`: 16.3 s for `PP-OCRv6_small_det` and 138.3 s for `PP-OCRv5_server_det`.
That gives 73.35 s and 622.35 s. The table is keyed by the detection model because detection is the cost that
separates the two engines, and `korean`'s recognition model, which nobody measured, sits beside the same detector as
`ru`'s. A detection model nobody measured, such as an operator's switch to the medium family, is given the slowest
measured figure until someone measures it. The measured page is the largest `high` admits, and `normal` reads
strictly smaller inputs, so one figure per engine bounds both modes and the mode is not a key.

There is still one source of truth. The headroom is the only configured time input and the table is the only
measured one, and every duration derives from them:

| Quantity | Derivation | At the defaults |
|---|---|---|
| Reading budget of a document | its pages x its engine's allowance | 73.35 s or 622.35 s a page |
| Reclamation grace | its engine's allowance + `OCR_DISPATCH_MARGIN_SECONDS` | 78.35 s or 627.35 s |
| `OCR_WORST_PAGE_ALLOWANCE_SECONDS` | the slowest engine any language in `SUPPORTED_LANGUAGES` or `DEFAULT_LANGUAGE` loads | 622.35 s |
| `OCR_JOB_READING_CEILING_SECONDS` | `OCR_JOB_MAX_PAGES` x the worst allowance | 62,235 s |
| `OCR_JOB_MAX_LIFETIME_SECONDS` | (`OCR_JOB_QUEUE_MAX_PAGES` + `OCR_JOB_MAX_PAGES`) x the worst allowance | 186,705 s |
| Poll hint | a tenth of the allowed seconds ahead, each page at its own engine's allowance, clamped to 1 to 30 s | |
| `Retry-After` on `QUEUE_FULL` | the same rule over everything in flight | |

Decision 10 moves the table to 28.4 s for `PP-OCRv6_small_det` and 96.0 s for `PP-OCRv5_server_det`, and no supported
language loads the second. At the defaults a page is allowed 127.8 s, the grace is 132.8 s, the worst allowance is
127.8 s, the reading ceiling 12,780 s and the maximum lifetime 38,340 s. Decision 11 moves the small detector to
50.4 s: at the defaults a page is allowed 226.8 s, the grace is 231.8 s, the worst allowance is 226.8 s, the reading
ceiling 22,680 s and the maximum lifetime 68,040 s. Measured again with the engine's threads capped to the container's
CPUs (Decision 11), the small detector moves to 25.1 s: at the defaults a page is allowed 112.95 s, the grace is
117.95 s, the worst allowance is 112.95 s, the reading ceiling 11,295 s and the maximum lifetime 33,885 s.

The ceiling and the lifetime take the worst engine because they bound every document, whatever its language. The
budget, the grace and the hints take the document's own, so an English page is not waited on for ten minutes because
Russian is supported. The runner records each queued document's allowance in its queue entry, so the promise it
reports is the sum of what each document ahead is actually allowed.

Rejected: one allowance of 4.5 x 138.3 s for every page. It keeps one number, and it multiplies every budget, grace,
hint and promise by 8.5 for the ten languages that read in seconds. A worker hung on an English page would then be
waited on for ten minutes before it is replaced.

Rejected: keying by quality mode as well. `normal` is measured only on its largest page, where it was faster than
`high` on both engines (11.3 s against 16.3 s, 46.6 s against 138.3 s), so each engine's `high` figure already bounds
it. A second axis would shorten `normal`'s allowance on one synthetic page while A4 densities and real scans are
unmeasured. Task 5.3 can add it once those are measured.

Consequence, stated rather than buried: with `ru` and `korean` supported, the maximum lifetime a record may spend in a
non-terminal state is about 52 hours, against 3 h 45 min before. That is how long a full queue of Russian pages can
legitimately take at the allowance. Without those two languages it is 22,005 s. With both switched off and the
container figures of Decision 10 it is 38,340 s, 68,040 s since Decision 11, and 33,885 s since the thread cap.

### Decision 9: Every preprocessing step is named, unwarping runs only on request, and each text line is classified on its own

Owner decisions of 2026-09-25, recorded in ADR-011 with the full evidence. The engine was built from the two model
names and `enable_mkldnn=False` alone, and PaddleOCR 3.7.0 fills every flag left as `None` from the paddlex `OCR`
pipeline configuration (`paddlex/configs/pipelines/OCR.yaml` lines 6, 7, 12, 13 and 39), which turns on page
orientation, UVDoc unwarping and text line orientation at a batch of 6. Measured on PaddleOCR 3.7.0 with
`PADDLE_PDX_CPU_NUM_THREADS=4` set, which paddlex never read, so the engine ran PaddleOCR's own 10 compute threads,
capped by the host's cores:

- Unwarping read a clean synthetic A4 page at 300 dpi as 9 of 50 lines with a peak of 1038 and 1084 MiB. Without it
  the same page read 50 of 50 at 486 and 488 MiB.
- On phone photos of one 21 line test page, unwarping took `crumpled-1` from 9 of 21 exact with 18 lines found to 13
  of 21 with all 21 found, and `bent` from 20 lines found to 21 with character accuracy from 0.951 to 0.997. On the
  flat, angled, turned and second crumpled photo it cost one line each.
- Without page orientation a scan turned 90 or 180 degrees read 0 of 34 lines. With it, 31 of 34.
- At a line orientation batch of 6 a page mixing 31 upright lines, 19 upside-down lines and three labels turned 90
  degrees read 31 of 53, with upright lines turned upside down in blocks of 6. At a batch of 1 it read 53 of 53.

The decision, on both surfaces:

| Step | Every request | With `straighten=true` |
|---|---|---|
| Page orientation | on | on |
| Unwarping (UVDoc) | off | on |
| Text line orientation, batch of 1 | on | on |

`straighten` is an optional boolean, default `false`, on `POST /v1/ocr/jobs` as a form field and on `ocr_submit` as an
argument. It is meant for phone photos of bent, curled or crumpled paper, recommended with `quality=high`, and harmful
on clean scans and PDFs. Like `quality` it is recorded in `JobRecord`, with a default so an older record still reads,
and echoed in `JobResultReference`.

The engine loads UVDoc once and the request switches it per call, because the installed library supports exactly
that. `PaddleOCR.predict_iter` forwards `use_doc_unwarping` per call (`paddleocr/_pipelines/ocr.py:179-198`). The OCR
pipeline builds its document preprocessor when the constructor enabled it (`paddlex/inference/pipelines/ocr/pipeline.py:77-87`)
and runs it per call when either explicit flag is true (`:231-237`, `:351-357`). The document preprocessor creates UVDoc
when enabled (`paddlex/inference/pipelines/doc_preprocessor/pipeline.py:80-86`), prefers an explicit per-call value
(`:132-135`) and enters UVDoc only when that value is true (`:183`). So `build_engine` constructs every engine with all
three steps on and `textline_orientation_batch_size=1` (`paddleocr/_pipelines/ocr.py:77`, mapped at `:273-275`), and
`_predict_page` passes all three flags on every call, unwarping set to the request's `straighten`. The engine cache
stays keyed by the model pair, because every engine is built the same way.

The Dockerfile's download step calls `preload_models()`, which builds every pair in `Settings.reachable_model_pairs()`
through `build_engine`, so the image carries every model the service can load, `ru` and `korean` included, and no
model is downloaded at request time. Decision 10 switches `ru` and `korean` off, so the image carries the default pair
and the three preprocessing models only.

Resident memory does not change, because the library defaults already loaded all three preprocessing models. A plain
request's per-call peak drops, a straightened one pays UVDoc again, and the line classifier now runs once per line.
Every timing and memory figure measured before this decision, `MEASURED_WORST_PAGE_SECONDS` and the startup banner's
figures included, is left unchanged here and is being re-measured separately (task 6.6). Re-measured in Decision 10.

Rejected: keeping the library defaults (9 of 50 on a clean page), unwarping nowhere (loses the crumpled-paper lines), a
second engine per pair for straightened requests (the library switches UVDoc per call, so it only costs memory and a
cache slot), line orientation off (upside-down lines read as garbage), and the batch left at 6 (31 of 53).

### Decision 10: The container measurement, `ru` and `korean` switched off, and a language refused at submission

Owner decisions of 2026-09-25, second round, recorded in ADR-011's amendment and ADR-002's second amendment.

**The container measurement.** Every figure below is a Linux container's cgroup `memory.peak`, 4 CPUs, image
`7b2cb25e7360`, PaddleOCR 3.7.0, worst of three runs, with time the fastest of three:

| Engine | Page | Mode | Peak | Time |
|---|---|---|---|---|
| `PP-OCRv6_small` pair | A4, 300 dpi, 50 lines | `high` | 1016 MiB | 20.5 s |
| `PP-OCRv6_small` pair | 4200 x 4200 px, 50 lines | `high` | 1236 MiB | 24.6 s |
| `PP-OCRv6_small` pair | 3162 x 4200 px photos, straightened, worst of six | `high` | 2771 MiB | 28.4 s |
| `PP-OCRv6_small` pair | 2100 x 2100 px, 50 lines | `normal` | 858 MiB | 18.3 s |
| `PP-OCRv5_server_det`, `korean` page | A4, 300 dpi | `high` | 9297 MiB | 71.2 s |
| `PP-OCRv5_server_det`, `korean` page | 4200 x 4200 px | `high` | 12754 MiB | 96.0 s |
| `PP-OCRv5_server_det`, `korean` page | 2100 x 2100 px | `normal` | 5958 MiB | 51.4 s |

A loaded engine holds about 333 MiB, of which about 124 MiB is the Python and Paddle runtime, and the API process at
rest holds 259 MiB. A direct run of the service on the 4200 x 4200 English page peaked at 1367 MiB for the container.
The earlier figures, 394, 441, 501 and 808 MiB on the small pair and 510, 517, 539, 720 and 807 on the server
detector, came from a probe that sampled memory at intervals and missed the peak.

`MEASURED_WORST_PAGE_SECONDS` holds 28.4 s for `PP-OCRv6_small_det`, the straightened photo (50.4 s since Decision 11, and 25.1 s since the thread cap), and 96.0 s for
`PP-OCRv5_server_det`, whose figure now only prices a detector nobody measured. Every duration in Decision 8 follows.
The startup banner prices each mode's worst input plain from the table, prices a straightened call as that plus the
largest straighten overhead measured on one photo, 1623 MiB, prices an idle engine at 333 - 124 = 209 MiB, and adds the
API process once. At the defaults that is 259 + 1236 + 1623 = 3118 MiB, so the `ascend-ocr` limit in `compose.yaml`
went from 12G to 4G.

**`ru` and `korean` switched off.** The server detector's peaks, the worst above the 12 GiB limit the container then
had, are the reason. `SUPPORTED_LANGUAGES` drops both, `LANGUAGE_MODEL_OVERRIDES` is empty, and `preload_models()`,
which builds `Settings.reachable_model_pairs()`, no longer bakes `PP-OCRv5_server_det`, `korean_PP-OCRv5_mobile_rec`
or `eslav_PP-OCRv5_mobile_rec`. The override mechanism stays, because bringing them back is expected to use it (task
7.8). `ENGINE_CACHE_MAX_SIZE` stays at 2: with one reachable pair the second slot is empty and costs nothing, because
the banner prices only engines a supported language can reach, and it is the slot a language opted back in would use.

**A language refused at submission.** A language outside `SUPPORTED_LANGUAGES` used to be accepted with 202 and
queued, and fail inside the worker as `OCR_FAILED`. `JobService.submit` and `ocr_submit` now call one check,
`ensure_language_supported`, first, so `POST /v1/ocr/jobs` answers 400 with
`{"code": "UNSUPPORTED_LANGUAGE", "detail": "Language is not supported. Supported languages: en, pl, de, fr, es, it, pt, nl, ch, japan"}` at the defaults, and `ocr_submit` raises
`UNSUPPORTED_LANGUAGE: ` followed by the same detail before it fetches the URI. No identifier is issued and nothing is
stored or queued. The detail is built from configuration and never echoes the caller's language. The worker's own
check stays as a defence.

**Known reading limits**, measured on the same image: the Spanish inverted exclamation mark is never output, because it
is not in the `PP-OCRv6_small_rec` alphabet, Polish `ź` and `ż` are sometimes swapped, and a 640 px low-resolution photo
reads about 98 percent of its characters but only 10 of 21 lines exactly.

### Decision 11: Recognition batch of 1, a warm-up read, and a dense page sets the allowance

Owner-approved 2026-09-25, recorded in ADR-011's second amendment.

`build_engine` passes `text_recognition_batch_size=1`, a named constant beside the line orientation batch, instead of
the library's padded batch of 6. On the host the English scan fixture went from 23.1, 23.1 and 21.1 s to 18.2, 17.0
and 15.8 s, with the same text except one space the padded batch dropped. Each worker's warm-up now also reads one
small generated image after building its engine, so the first job pays no first-inference setup, and a failed read
fails the warm-up the way a failed build already did.

Every page behind Decision 10's allowance was sparse. Dense A4 prose at 300 dpi, 11 pt, full-width lines, measured in
the same container set-up on image `385d160c20a0`, fastest of three runs and worst peak:

| Page | Mode | Time | Peak | Exact lines | Character accuracy |
|---|---|---|---|---|---|
| Dense English A4, 50 lines, 4162 characters | `high` | 47.4 s | 1115 MiB | 50 of 50 | 1.0000 |
| The same, straightened | `high` | 50.4 s | 1972 MiB | 50 of 50 | 1.0000 |
| Dense Polish A4, 48 lines, 4000 characters | `high` | 42.0 s | 1074 MiB | 45 of 48 | 0.9821 |
| Dense English A4 | `normal` | 41.8 s | 822 MiB | 49 of 50 | 0.9995 |
| English scan fixture, 778 x 932 px, 34 lines | `high` | 28.2 s | 752 MiB | 32 of 34 | 0.9993 |
| Sparse 4200 x 4200 px, 50 lines | `high` | 22.3 s | 1220 MiB | 50 of 50 | 1.0000 |

`MEASURED_WORST_PAGE_SECONDS` for `PP-OCRv6_small_det` becomes 50.4 s, the slowest minimum of every case measured on
that detector. At the defaults a page is allowed 226.8 s, the grace is 231.8 s, the worst allowance is 226.8 s, the
reading ceiling 22,680 s and the maximum lifetime 68,040 s. No peak exceeds a figure the banner already prices, so the
banner and the 4 GiB limit are unchanged.

Those times were measured while PaddleOCR ran its own 10 compute threads throttled under the 4-CPU quota (task 9.1).
With `build_engine` passing `cpu_threads` equal to the container's CPU limit, the same cases plus the flat phone photo
read with `straighten` were measured again with the same probe on image `9c100951f59b`, on a host 54 to 92 percent
busy, which only lengthens a run, so each fastest time is an upper bound (ADR-011, third amendment):

| Page | Mode | Time | Peak | Exact lines | Character accuracy |
|---|---|---|---|---|---|
| Dense English A4, 50 lines, 4162 characters | `high` | 22.1 s | 1132 MiB | 50 of 50 | 1.0000 |
| The same, straightened | `high` | 24.9 s | 1958 MiB | 50 of 50 | 1.0000 |
| Dense Polish A4, 48 lines, 4000 characters | `high` | 25.1 s | 1070 MiB | 45 of 48 | 0.9821 |
| Dense English A4 | `normal` | 22.7 s | 827 MiB | 49 of 50 | 0.9995 |
| English scan fixture, 778 x 932 px, 34 lines | `high` | 15.6 s | 807 MiB | 32 of 34 | 0.9993 |
| Sparse 4200 x 4200 px, 50 lines | `high` | 15.8 s | 1213 MiB | 50 of 50 | 1.0000 |
| Flat phone photo, 3162 x 4200 px, straightened | `high` | 19.5 s | 2636 MiB | 19 of 21 | 0.9975 |

`MEASURED_WORST_PAGE_SECONDS` for `PP-OCRv6_small_det` becomes 25.1 s, the dense Polish page. At the defaults a page is
allowed 112.95 s, the grace is 117.95 s, the worst allowance is 112.95 s, the reading ceiling 11,295 s and the maximum
lifetime 33,885 s. `PP-OCRv5_server_det` keeps 96.0 s, measured before the cap, since no supported language loads it.
No peak exceeds a figure the banner already prices, so the banner and the 4 GiB limit are unchanged again.

## Requirements this change overturns elsewhere

Three requirements in changes that are implemented and not archived say something this change makes false. This
change does not edit those files, which belong to other work in flight. Whichever change archives first carries the
reconciliation, and task 5.4 is the checklist.

- `stop-ocr-getting-stuck-on-large-jobs`, `ocr-input-limits`, "One inference receives no more than a configured
  number of pixels". Superseded. A page above the size a mode supports is shrunk, not refused, and a document page is
  never refused on pixels. The header-time guard and the reuse of the existing error code survive, now attached to
  `OCR_MAX_SOURCE_PIXELS` in `ocr-page-resolution`.
- `stop-ocr-getting-stuck-on-large-jobs`, `ocr-memory-bounds`, "The input to one inference is bounded by
  configuration, not by the caller". Narrowed. The bound is now chosen by a caller's mode from two operator-set pairs,
  it can no longer be unset, and the scenario "Text is read at full resolution whatever the bound" is false as a
  quality claim: at 6.85x every line was found and none read correctly.
- `read-long-documents`, `ocr-job-admission`, "Every existing input guard applies at submission", scenario "Oversized
  page submitted". An oversized page is now read. The requirement itself still holds for the source pixel ceiling,
  the byte cap and the type check.

`stop-ocr-getting-stuck-on-large-jobs`, `ocr-request-deadlines`, "Reclaiming a worker reclaims the files it was
using" becomes vacuous rather than false: a worker holds no file to reclaim.

`read-long-documents` states the 45 s allowance as settled in several places, and this change does not edit its
files. What needs changing there, which task 5.6 tracks: its proposal's "settled at 45 s" bullet, design.md's number
table rows for the per-page allowance, the reading budget, the reading ceiling (4500 s), the maximum lifetime
(13,500 s) and the poll hint, the "2 h 30 min at the bound and about 33 minutes" wait in its queue and risks
sections, Open Question 1's "confirms the 45 s allowance", tasks 1.4 and 10.6, and in `ocr-job-admission` the
requirement "The per-page allowance is a deadline sized above the measured cost", whose "only configured time input"
is now the headroom.

## Risks / Trade-offs

- `high` by default means the average page is recognised from four times the pixels it was. Memory is measured flat.
  Recognition time on a real scan is not measured, and each engine's allowance is 4.5 times its worst measured clean
  page for exactly this unknown. Task 10.6 of `read-long-documents`, its run against real scans, is where
  a wrong allowance would show.
- The service now owns rasterization, which ADR-005 rejected as a maintenance cost. The code that does it is one
  module of a few dozen lines against pypdfium2 and Pillow, both already pinned dependencies, and it follows the
  library's own renderer call for call. A library upgrade that changes what the pipeline expects of an array input is
  the risk, and the unit tests pin the channel order and the shape.
- A deployment that tuned `OCR_DETECTOR_MAX_SIDE` or `OCR_PAGE_TIMEOUT_SECONDS` loses that tuning silently, because
  an unknown variable is ignored. The replacements are `OCR_QUALITY_HIGH` and `OCR_PAGE_ALLOWANCE_HEADROOM`, and
  `docs/CONFIGURATION.md` says so.
- The maximum lifetime of a wedged record grows to about 52 hours while `ru` and `korean` are supported (Decision 8).
  A wedged record is a defect, so the cost is how long a defect stays visible as `running` before it is failed. With
  both switched off (Decision 10) it is 38,340 s, about 10 h 39 min, 68,040 s, about 18 h 54 min, since Decision 11,
  and 33,885 s, about 9 h 25 min, since the thread cap.
- Russian and Korean callers lose the service until task 7.8 brings them back. They get a 400 with the supported list
  rather than a job that fails later.

## Migration Plan

Rebuild the image and restart the container. No data migrates: a job record written before the change has no
`quality` field and reads as `high`, and no `straighten` field and reads as `false`. Leftover files in the old scratch directory sit in the container's temporary
path and are gone with the container. Rolling back is the previous image. A record written with a `quality` field
still reads there, because `JobRecord` is a pydantic model with the default `extra="ignore"`, and a record that was
waiting or running is failed as `SERVICE_RESTARTED` by the restart either way.

## Open Questions

1. Is `normal` worth keeping once it is measured? If it is not meaningfully faster than `high` on real scans, one mode
   would do. Task 5.3 answers it.
2. Should the ratio ceiling move? Everything between 3.3x and 6.85x is unmeasured. A measurement at 4x and 5x would
   either widen what an operator may configure or confirm the ceiling.
