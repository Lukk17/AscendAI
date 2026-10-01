# ADR-011: Name every preprocessing step, straighten a page only when the caller asks, and classify each text line on its own

## Status

Accepted, 2026-09-25. Owner decisions of 2026-09-25. Amends [ADR-007](ADR-007-explicit-ocr-model-selection.md), whose
engine constructor it extends, and [ADR-010](ADR-010-quality-modes-and-service-side-rendering.md), whose measured
figures it leaves in place for re-measurement. OpenSpec change `fix-ocr-page-resolution`. Amended the same day with
the re-measurement, `ru` and `korean` switched off, and the known reading limits (see "Amendment" below).

## Context

The engine was built from the two model names and `enable_mkldnn=False` alone. PaddleOCR 3.7.0 fills every flag the
caller leaves as `None` from the paddlex `OCR` pipeline configuration, which turns on all three preprocessing models:

| Step | Model | Library default | Where the default comes from |
|---|---|---|---|
| Page orientation | `PP-LCNet_x1_0_doc_ori` | on | `paddlex/configs/pipelines/OCR.yaml:6` and `:12` |
| Unwarping | `UVDoc` | on | `paddlex/configs/pipelines/OCR.yaml:6` and `:13` |
| Text line orientation | `PP-LCNet_x1_0_textline_ori` | on, batch of 6 | `paddlex/configs/pipelines/OCR.yaml:7` and `:39` |
| Text recognition | the named recogniser | batch of 6 | `paddlex/configs/pipelines/OCR.yaml:44` |

The wrapper builds its overrides with `create_config_from_structure` (`paddleocr/_pipelines/utils.py:16-21`, called at
`paddleocr/_pipelines/ocr.py:316`), which skips every `None`, so the YAML value stands. The Dockerfile's model
download step built the engine the same way, and only for the default pair, so `ru` and `korean` downloaded their
models on the first request that needed them.

Measured on PaddleOCR 3.7.0 with `PADDLE_PDX_CPU_NUM_THREADS=4` set, which never reached paddlex, so the engine ran
PaddleOCR's own 10 compute threads, capped by the host's cores, detection bounded to 1536 unless noted:

| Input | Everything on (library default) | Orientation and line orientation, no unwarping | Nothing |
|---|---|---|---|
| Clean synthetic A4 at 300 dpi, 50 lines | 9 of 50, peak 1038 and 1084 MiB | 50 of 50, peak 486 and 488 MiB | 50 of 50, peak 462 MiB |
| Scan turned 90 degrees, 34 lines | 32 of 34 | 31 of 34 | 0 of 34 |
| Scan turned 180 degrees, 34 lines | 31 of 34 | 31 of 34 | 0 of 34 |
| Synthetic A4 with a simulated curl, 50 lines | 50 of 50 | 50 of 50 | 50 of 50 |

Phone photos of one printed test page, 21 lines, fed at a 2000 px long side, `high` mode, exact lines with character
accuracy in brackets:

| Photo (fixture `e2e/fixtures/straightening-photo-*.jpg`) | Without unwarping | With unwarping |
|---|---|---|
| `flat` | 20 of 21 (0.999) | 19 of 21 (0.998) |
| `rotated-90` | 20 of 21 (0.999) | 19 of 21 (0.998) |
| `angled` | 19 of 21 (0.998) | 18 of 21 (0.997) |
| `bent` | 18 of 21, 20 lines found (0.951) | 18 of 21, 21 lines found (0.997) |
| `crumpled-1` | 9 of 21, 18 lines found (0.844) | 13 of 21, 21 lines found (0.988) |
| `crumpled-2` | 18 of 21 (0.997) | 17 of 21 (0.996) |

In `normal` mode `bent` went from 16 of 21 with 19 lines found to 18 of 21 with 21 found, and `crumpled-1` from 11
of 21 with 18 found to 12 of 21 with 20 found. Unwarping raised the per-call peak on these photos by 94 to 134 MiB across both modes.
(Superseded by the container measurement in the amendment below, which puts the rise at 1490 to 1623 MiB.)

Unwarping destroys a clean flat page and recovers lines that are otherwise lost on bent or crumpled paper. Page
orientation is what reads a page turned 90 or 180 degrees at all.

A second defect showed up on a synthetic A4 page mixing 31 upright lines, 19 upside-down lines and three labels turned
90 degrees. At the library's text line orientation batch of 6, the classifier's decision followed the batch rather
than the line: 10 upside-down lines were turned upright and 12 upright lines were turned upside down, in blocks of 6.
Read the way the service now reads it (orientation and line orientation on, unwarping off, the same 10 compute threads
rather than the 4 the variable asked for):

| Line orientation batch | Exact | Upright | Upside down | Turned 90 degrees |
|---|---|---|---|---|
| 6 (library default) | 31 of 53 | 19 of 31 | 10 of 19 | 2 of 3 |
| 1 | 53 of 53 | 31 of 31 | 19 of 19 | 3 of 3 |

The pipeline reads each classifier result with `np.asarray(textline_angle_info["class_ids"]).ravel()[0]`
(`paddlex/inference/pipelines/ocr/pipeline.py:432-441`). That shape is consistent with every line of a batch taking one
decision, but the mechanism was not traced further than the measurement.

## Decision

Every preprocessing flag is named, on the constructor and on every call. Nothing is left to a library default.

| Step | Default for every request | With `straighten=true` |
|---|---|---|
| Page orientation | on | on |
| Unwarping | off | on |
| Text line orientation, batch of 1 | on | on |

`straighten` is an optional boolean on `POST /v1/ocr/jobs` (form field) and on the MCP `ocr_submit` tool, default
`false`. It is carried in the job record and echoed in the result block of the job status, beside `quality`. It is
meant for phone photos of bent, curled or crumpled paper, recommended with `quality=high`, and harmful on clean scans
and PDFs.

The engine loads UVDoc once and the request switches it per call. This is supported by the installed library:

1. `PaddleOCR.predict_iter` accepts `use_doc_unwarping` per call and forwards it unchanged
   (`paddleocr/_pipelines/ocr.py:179-198`).
2. The OCR pipeline builds the document preprocessor only when the constructor enabled it
   (`paddlex/inference/pipelines/ocr/pipeline.py:77-87`), and per call it runs the preprocessor when either explicit
   flag is `True` (`:231-237`, `:351-357`).
3. The document preprocessor creates the UVDoc model when its configuration enables it
   (`paddlex/inference/pipelines/doc_preprocessor/pipeline.py:80-86`), takes an explicit per-call value over the configured one (`:132-135`), and runs UVDoc only when that value is true
   (`:183`). A call passing `use_doc_unwarping=False` to an engine built with it on never enters UVDoc.

So `build_engine` constructs with `use_doc_orientation_classify=True`, `use_doc_unwarping=True`,
`use_textline_orientation=True`, `textline_orientation_batch_size=1` (`paddleocr/_pipelines/ocr.py:77`, mapped to
`SubModules.TextLineOrientation.batch_size` at `:273-275`), `text_recognition_batch_size=1` (`:80`, mapped to
`SubModules.TextRecognition.batch_size` at `:282-284`, see the second amendment below) and `enable_mkldnn=False`. Every `predict_iter` call passes
`use_doc_orientation_classify=True`, `use_doc_unwarping=straighten` and `use_textline_orientation=True`. The engine
cache stays keyed by the model pair alone, because every engine is built identically and a straightened request and a
plain one read with the same engine.

The Dockerfile's download step calls `preload_models()`, which builds one engine per pair in
`Settings.reachable_model_pairs()` through the same `build_engine`, so the image carries every model the service can
load: the default pair, both PP-OCRv5 pairs for `ru` and `korean`, and the three preprocessing models. Since the
amendment below that is the default pair and the three preprocessing models only.

## Consequences

- A clean page is no longer read through UVDoc. On the synthetic A4 page that is 50 of 50 lines instead of 9 of 50,
  and roughly 550 to 600 MiB less peak memory per call.
- A mixed-orientation page reads every line, at the cost of one classifier call per line instead of one per six. That
  time is not measured yet.
- Resident memory is unchanged: the three preprocessing models were already loaded by the library defaults, and
  keeping UVDoc loaded is what avoids a second engine per pair. A second engine per pair would have doubled the
  resident detection and recognition models for every straightened request's language.
- A straightened request costs more per call than a plain one. The page allowance, the memory banner and the
  `MEASURED_WORST_PAGE_SECONDS` figures were measured before this change and are being re-measured separately. Until
  then they describe a pipeline other than the one the service runs.
- No model is downloaded at request time from an image built with the default `SUPPORTED_LANGUAGES`. An operator who
  adds a language outside that list at runtime still downloads its pair on first use.
- A job record written before this change reads as `straighten=false`.

## Amendment (2026-09-25): the re-measurement, and `ru` and `korean` switched off

**The re-measurement.** The fourth consequence above said the page allowance, the memory banner and
`MEASURED_WORST_PAGE_SECONDS` described a pipeline other than the one the service runs. They were re-measured in a
Linux container with 4 CPUs, image `7b2cb25e7360`, as the cgroup's `memory.peak`, worst of three runs, on six phone
photos of one printed page fed at 3162 x 4200 px in `high` mode, each read plain and straightened:

| Photo | Plain peak | Straightened peak | Straightened time, fastest of three | Exact lines, straightened |
|---|---|---|---|---|
| `flat` | 1161 MiB | 2651 MiB | 28.4 s | 19 of 21 |
| `angled` | 1125 MiB | 2682 MiB | 26.4 s | 19 of 21 |
| `bent` | 1097 MiB | 2666 MiB | 23.4 s | 19 of 21 |
| `crumpled-1` | 1125 MiB | 2655 MiB | 22.9 s | 12 of 21 |
| `crumpled-2` | 1137 MiB | 2735 MiB | 25.5 s | 17 of 21 |
| `rotated-90` | 1148 MiB | 2771 MiB | 24.6 s | 19 of 21 |

Unwarping adds 1490 to 1623 MiB to a call, not the 94 to 134 MiB the Context section quotes, whose probe sampled
memory at intervals and missed the peak. `MEASURED_WORST_PAGE_SECONDS` for `PP-OCRv6_small_det` is now 28.4 s, the
straightened `flat` photo, so the page allowance is 127.8 s (superseded by the second amendment below, 50.4 s and 226.8 s, and by the third, 25.1 s and 112.95 s). The startup banner prices a straightened call as the
plain peak for the mode plus 1623 MiB, 2859 MiB for `high` mode's largest page, and adds the API process at rest,
259 MiB. The container limit in `compose.yaml` went from 12 GiB to 4 GiB: the worst straightened call, 2771 MiB, plus
the API process, plus headroom for one idle engine, is about 3.1 GiB. The full figures are in "Memory model and the
single worker" in [07-deployment-view.md](../arc42/07-deployment-view.md).

**`ru` and `korean` are switched off.** Both loaded `PP-OCRv5_server_det`, measured the same way at 9297 MiB on an A4
page and 12754 MiB on a 4200 x 4200 px page in `high` mode, and 5958 MiB in `normal` mode, the worst of them above
the 12 GiB limit the container then had. Both are out of `SUPPORTED_LANGUAGES`, `LANGUAGE_MODEL_OVERRIDES` is empty,
and `preload_models()` no longer bakes `PP-OCRv5_server_det`, `korean_PP-OCRv5_mobile_rec` or
`eslav_PP-OCRv5_mobile_rec` into the image. A request in either is refused at submission with
`UNSUPPORTED_LANGUAGE` ([ADR-002](ADR-002-mcp-error-catalog.md)), before anything is fetched, stored or queued.
Bringing them back is an open task in `openspec/changes/fix-ocr-page-resolution/tasks.md`: measure
`PP-OCRv6_small_det` with the `korean_` and `eslav_` PP-OCRv5 mobile recognisers, with and without straightening, and
restore them only if accuracy holds.

## Second amendment (2026-09-25): recognition batch of 1, a warm-up read, and a dense page sets the allowance

**Recognition batch of 1.** The recogniser was left at the library's batch of 6 (`paddlex/configs/pipelines/OCR.yaml:44`),
which pads every line of a batch to the widest one. `build_engine` now passes `text_recognition_batch_size=1`
(`paddleocr/_pipelines/ocr.py:80`), the named constant `TEXT_RECOGNITION_BATCH_SIZE` beside
`TEXTLINE_ORIENTATION_BATCH_SIZE`. Measured on the host through the whole pipeline, `argent-saga-chronicles-page1.png`
took 23.1, 23.1 and 21.1 s at a batch of 6 and 18.2, 17.0 and 15.8 s at a batch of 1, and a 1000 px flat photo went
from about 8 s to about 6 s. The text was unchanged except that the batch of 1 kept a space the padded batch dropped,
on the heading line that opens "Part One" and ends "The Old Bright".

**A warm-up read.** Each worker already built its engine before it accepted work. It now also reads one small
generated image of a few words through the same `_predict_page` a job uses, `high` mode, unwarping off, so the first
job does not pay the first-inference setup. A failure of that read fails the pool's initializer exactly as a failed
build does: the pool is reported broken, `/ready` stays not-ready, and the rebuild path takes over.

**A dense page sets the allowance.** Every page behind the first amendment's allowance was sparse: the synthetic pages
carry 50 short lines, 909 characters. Dense A4 prose at 300 dpi, 11 pt Arial, full-width lines, was measured in the
same container set-up (4 CPUs, 14 GiB, `PADDLE_PDX_CPU_NUM_THREADS=4`, which never reached paddlex, so the engine ran
PaddleOCR's own 10 compute threads under the 4-CPU quota, as corrected in the deployment view on 2026-09-25, the
service's own `OcrService.process_file`, a
warm-up call then a timed call, cgroup `memory.peak`), image `385d160c20a0`, three runs each, time the fastest of three
and peak the worst:

| Page | Mode | Runs | Fastest | Peak | Exact lines | Character accuracy |
|---|---|---|---|---|---|---|
| Dense English A4, 50 lines, 4162 characters | `high` | 54.1, 47.4, 50.6 s | 47.4 s | 1115 MiB | 50 of 50 | 1.0000 |
| The same, straightened | `high` | 52.7, 50.4, 50.6 s | 50.4 s | 1972 MiB | 50 of 50 | 1.0000 |
| Dense Polish A4, 48 lines, 4000 characters | `high` | 43.3, 42.5, 42.0 s | 42.0 s | 1074 MiB | 45 of 48 | 0.9821 |
| Dense English A4 | `normal` | 43.2, 43.4, 41.8 s | 41.8 s | 822 MiB | 49 of 50 | 0.9995 |
| `argent-saga-chronicles-page1.png`, 778 x 932 px, 34 lines | `high` | 30.0, 29.5, 28.2 s | 28.2 s | 752 MiB | 32 of 34 | 0.9993 |
| Sparse 4200 x 4200 px, 50 lines | `high` | 24.8, 23.1, 22.3 s | 22.3 s | 1220 MiB | 50 of 50 | 1.0000 |

The Polish page lost one line to garbage (line 28), dropped a final full stop, and read `tysiąc` and
`siedemdziesiątym` without their `ą`. The `normal` English page and the scan each dropped a final full stop, and the
scan closed up one space around a dash.

`MEASURED_WORST_PAGE_SECONDS` for `PP-OCRv6_small_det` was then 50.4 s (superseded by the third amendment below), the straightened dense English page and the
slowest minimum of every case measured on this detector, straightened photos included. At the default headroom of 4.5
a page was allowed 226.8 s, the reclamation grace was 231.8 s, the reading ceiling 22,680 s and the maximum lifetime
68,040 s. No page here peaked above a figure the startup banner already prices, 1236 MiB plain and 2859 MiB
straightened for `high` mode's largest page, so the banner and the 4 GiB limit in `compose.yaml` are unchanged.

## Third amendment (2026-09-25): the page times measured again with the thread cap

Every time in this record so far was measured while PaddleOCR ran its own 10 compute threads under the 4-CPU quota,
throttled in nearly every scheduling period, because `PADDLE_PDX_CPU_NUM_THREADS` never reached paddlex. `build_engine`
now passes `cpu_threads` equal to the container's CPU limit (see "Memory model and the single worker" in
[07-deployment-view.md](../arc42/07-deployment-view.md)). The second amendment's cases, plus the sparse 4200 x 4200 page
and the flat phone photo read with `straighten`, were measured again in the same set-up and with the same probe on
image `9c100951f59b`, three runs each, time the fastest of three and peak the worst. The host was busy, its whole-CPU
load averaging 54 to 92 percent across the runs, which only lengthens a run, so each fastest time is an upper bound:

| Page | Mode | Runs | Fastest | Peak | Exact lines | Character accuracy |
|---|---|---|---|---|---|---|
| Dense English A4, 50 lines, 4162 characters | `high` | 28.1, 27.7, 22.1 s | 22.1 s | 1132 MiB | 50 of 50 | 1.0000 |
| The same, straightened | `high` | 41.3, 31.7, 24.9 s | 24.9 s | 1958 MiB | 50 of 50 | 1.0000 |
| Dense Polish A4, 48 lines, 4000 characters | `high` | 25.1, 25.9, 30.0 s | 25.1 s | 1070 MiB | 45 of 48 | 0.9821 |
| Dense English A4 | `normal` | 32.8, 31.5, 22.7 s | 22.7 s | 827 MiB | 49 of 50 | 0.9995 |
| `argent-saga-chronicles-page1.png`, 778 x 932 px, 34 lines | `high` | 15.6, 16.8, 22.2 s | 15.6 s | 807 MiB | 32 of 34 | 0.9993 |
| Sparse 4200 x 4200 px, 50 lines | `high` | 15.8, 16.7, 17.4 s | 15.8 s | 1213 MiB | 50 of 50 | 1.0000 |
| Flat phone photo, 3162 x 4200 px, straightened | `high` | 19.5, 29.2, 20.0 s | 19.5 s | 2636 MiB | 19 of 21 | 0.9975 |

Every case the second amendment measured reads the same exact lines at the same character accuracy.
`MEASURED_WORST_PAGE_SECONDS` for `PP-OCRv6_small_det` is now
25.1 s, the dense Polish page, the slowest minimum of every case measured, with the straightened dense English page
0.2 s behind it. At the default headroom of 4.5 a page is allowed 112.95 s, the reclamation grace is 117.95 s, the
reading ceiling 11,295 s and the maximum lifetime 33,885 s. `PP-OCRv5_server_det` keeps its 96.0 s, measured before
the thread cap: no supported language loads it, and it only prices a detector nobody measured. No page peaked above a
figure the startup banner already prices, so the banner and the 4 GiB limit are unchanged.

## Known reading limits

Measured on the same container image, against pages whose text is known:

- The Spanish inverted exclamation mark is never output. It is not in the `PP-OCRv6_small_rec` alphabet, so a line
  that opens with one is read without it.
- Polish `ź` and `ż` are sometimes swapped for each other.
- A low-resolution photo, 482 x 640 px, reads about 98 percent of its characters but only 10 of its 21 lines exactly.
  The same photo reads 18 of 21 lines exactly at 1000 px and 19 of 21 at 1600 px.
- Russian and Korean are not read, as the amendment above records.
- The owner's crumpled phone photo (end-to-end spec 18) reads 17 of 21 lines exactly with `straighten=true`, every
  one of the 21 lines found at 0.8 similarity or better. The same photo without straightening reads 14 of 21 and
  loses two whole lines. The owner accepted 15 of 21 as spec 18's threshold on 2026-09-25: it leaves two phrases of
  margin for fold damage that shifts between readings, and it still sits above the unstraightened 14, so a pass still
  proves straightening helps. Improving crumpled-photo accuracy is future work (a stronger recognition model, a better
  unwarping model, or image cleanup before recognition), tracked as task 7.11 in
  `openspec/changes/fix-ocr-page-resolution/tasks.md`.

## Alternatives considered

- Keep the library defaults. They unwarp every page, which is the measured 9 of 50 on a clean page.
- Turn unwarping off everywhere. It loses the lines UVDoc recovers on crumpled paper, 13 of 21 against 9 of 21.
- Build a second engine with unwarping for straightened requests. The library switches it per call, so a second
  engine only costs memory and a second cache slot.
- Turn text line orientation off. It avoids the batch defect but reads upside-down lines as garbage.
- Leave the line orientation batch at 6. It is the measured 31 of 53 on a mixed page.

## Related

- `openspec/changes/fix-ocr-page-resolution/design.md`.
- `apps/ascend-ocr/src/service/ocr_service.py` (`build_engine`, `preload_models`, `_predict_page`),
  `src/config/config.py` (`reachable_model_pairs`), `Dockerfile`.
- [ADR-007](ADR-007-explicit-ocr-model-selection.md), [ADR-010](ADR-010-quality-modes-and-service-side-rendering.md).
