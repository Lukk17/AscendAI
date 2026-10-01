# ADR-010: Render pages in the service, let a caller pick one of two locked quality modes, and allow each engine its own time

## Status

Accepted, 2026-09-24. Supersedes [ADR-005](ADR-005-fixed-pdf-render-resolution.md) and the parts of
[ADR-006](ADR-006-detector-input-bound.md) its amendment names. OpenSpec change `fix-ocr-page-resolution`. Amended
2026-09-25: every measured figure is superseded by a container measurement, which moves the page allowance and every
duration derived from it (see "Amendment" below).

## Context

Four defects, one cause: the pixels one inference reads, and the time one page is allowed, were each a single value
for the whole process.

1. PaddleOCR rasterized every PDF page itself at `PADDLE_PDX_PDF_RENDER_SCALE`, 2.0 on PDF points, which is 144 dpi,
   read once when `paddlex/utils/flags.py` is imported. No request could ask for more, and ADR-005 recorded that
   144 dpi puts body text at the edge of what is recognised dependably.
2. `OCR_MAX_INFERENCE_PIXELS`, 2,500,000, refused an A4 page scanned at 300 dpi (2480 x 3508, 8.7 megapixels) with
   `FILE_TOO_LARGE`. `src/api/limits.py` also set Pillow's `Image.MAX_IMAGE_PIXELS` from it, so one number was both a
   decompression-bomb guard and an inference ceiling.
3. No request could choose between a quick read and a careful one.
4. `OCR_PAGE_TIMEOUT_SECONDS`, 45 s, was one allowance for every engine. It was 4.5 times the 10.0 s the small pair
   took on an A4 page, and it was never measured against `PP-OCRv5_server_det`, which `ru` and `korean` load.

Measured on 2026-09-24, PaddleOCR 3.7.0, synthetic pages. Every peak and every time in this table is superseded by
the container measurement in the amendment below: the probe sampled memory at intervals and missed the peak, and ran
on the owner's machine rather than in the container.

| Engine | Page | Detection bound | Peak | Wall time | Lines exact |
|---|---|---|---|---|---|
| `PP-OCRv6_small` pair | A4, 300 dpi, 6 / 20 / 50 lines | 1536 | 439 / 439 / 441 MB | 4.1 / 6.0 / 10.0 s | |
| `PP-OCRv6_small` pair | 2100 x 2100 px, 50 lines | 1024 | 394 MiB | 11.3 s | 50 of 50 |
| `PP-OCRv5_server_det` + `eslav_PP-OCRv5_mobile_rec` | 2100 x 2100 px, 50 lines | 1024 | 517 MiB | 46.6 s | 42 of 50 |
| `PP-OCRv6_small` pair | 4200 x 4200 px, 50 lines | 1536 | 501 MiB | 16.3 s | 50 of 50 |
| `PP-OCRv5_server_det` + `eslav_PP-OCRv5_mobile_rec` | 4200 x 4200 px, 50 lines | 1536 | 510 MiB | 138.3 s | 42 of 50 |

Memory is flat at 144 and at 300 dpi once detection is bounded, because detection dominates and the bound caps what
it sees. Recognition crops come from the full-resolution page: the paddlex OCR pipeline rescales the detected boxes
back onto the original before cropping. And the ratio of the rendered long side to the detector bound is a quality
parameter in its own right: with a bound of 512, a page at 144 dpi (a 3.3x downscale) read 28 of 28 lines correctly,
and the same page at 300 dpi (6.85x) had every line found and every line read as garbage.

## Decision

**The service renders every page itself.** PDF pages are rendered with pypdfium2 and images decoded with Pillow, one
page at a time, and each page reaches `PaddleOCR.predict_iter` as a BGR array. The library's rasterizer and its fixed
resolution are off the path. The worker no longer writes the upload to a scratch file, because nothing reads a path.

**Two quality modes, each a locked pair.** `quality` is `normal` or `high` on both surfaces, and a caller never
supplies a number:

| Mode | Setting | Render resolution | Detector bound | Largest long side | Worst ratio (US Legal) |
|---|---|---|---|---|---|
| `normal` | `OCR_QUALITY_NORMAL=150:1024` | 150 dpi | 1024 | 2100 px | 2.05x |
| `high` (default) | `OCR_QUALITY_HIGH=300:1536` | 300 dpi | 1536 | 4200 px | 2.73x |

`high` is the default because it is the configuration that was measured, it costs nothing in memory, it keeps the
detector bound the owner settled on real documents, and `normal` at 150 dpi sits at the same edge 144 dpi did. Each
pair is one setting, so an operator cannot change one half without the other, and a pair whose worst ratio exceeds
3.3x is refused at startup. The detector bound is passed on every `predict_iter` call, so both modes share one cached
engine.

**Oversized input is shrunk, then read.** The largest page a mode supports is US Legal, 14 inches, at its resolution.
A larger PDF page is rendered at the lower scale that fits it, and a larger image is downscaled to it with its aspect
ratio kept. Nothing is scaled up.

**One pixel refusal, for absurd input.** `OCR_MAX_SOURCE_PIXELS`, defaulting to 89,478,485 (Pillow's own
decompression-bomb threshold, above A3 at 600 dpi), refuses a raster image frame from its header before decode, with
`FILE_TOO_LARGE`. Pillow's global guard is set from it and from nothing else. A PDF page is never refused on pixels,
because the service decides how many it renders. A multi-frame TIFF is counted as its frames.

**Each engine is allowed its own time.** `OCR_PAGE_TIMEOUT_SECONDS` is replaced by `OCR_PAGE_ALLOWANCE_HEADROOM`,
default 4.5, the same rule the 45 s was derived with. A page's allowance is the headroom times the worst measured page
of the detection model that reads it, kept as `MEASURED_WORST_PAGE_SECONDS` in `src/config/config.py`: 73.35 s on
`PP-OCRv6_small_det` and 622.35 s on `PP-OCRv5_server_det` (superseded, 127.8 s and 432.0 s since the amendment
below, 226.8 s on the small detector since ADR-011's second amendment, and 112.95 s since its third). A detection model nobody measured gets the slowest
measured figure. The measured page is the largest `high` supports, and `normal` reads strictly smaller inputs, so one
figure per engine bounds both modes.

Everything that was a multiple of the old allowance is derived from the new one, so there is still one source of
truth:

| Quantity | Derivation | At the defaults, 2026-09-24 (superseded) | At the defaults, 2026-09-25, photo (superseded) | At the defaults, 2026-09-25, dense page (superseded) | At the defaults, 2026-09-25, thread cap |
|---|---|---|---|---|---|
| A document's reading budget | its pages x its engine's allowance | 73.35 s or 622.35 s a page | 127.8 s a page | 226.8 s a page | 112.95 s a page |
| Reclamation grace | the engine's allowance + `OCR_DISPATCH_MARGIN_SECONDS` | 78.35 s or 627.35 s | 132.8 s | 231.8 s | 117.95 s |
| Worst allowance | the slowest engine any supported language loads | 622.35 s | 127.8 s | 226.8 s | 112.95 s |
| Reading ceiling | `OCR_JOB_MAX_PAGES` x the worst allowance | 62,235 s | 12,780 s | 22,680 s | 11,295 s |
| Maximum lifetime | (`OCR_JOB_QUEUE_MAX_PAGES` + `OCR_JOB_MAX_PAGES`) x the worst allowance | 186,705 s | 38,340 s | 68,040 s | 33,885 s |
| Poll hint and `Retry-After` | a tenth of the allowed time ahead, each page at its own engine's allowance, held to 1 to 30 s | | | | |

## Consequences

- A 300 dpi scan is read instead of refused, and a caller can ask for the quicker `normal` read.
- A Russian or Korean page is no longer failed by a 45 s budget it could never meet. The same page in `high` mode
  measured 138.3 s.
- An English page is allowed 73.35 s instead of 45 s, because `high` mode admits pages up to 4200 x 4200 px and the
  largest measured 16.3 s.
- The maximum lifetime and the reading ceiling are now set by the slowest engine a supported language can load. With
  `ru` and `korean` in `SUPPORTED_LANGUAGES` a wedged record is failed after about 52 hours rather than 3 h 45 min,
  because a queue full of Russian pages can legitimately take that long at the allowance. Removing both languages
  from the list brings it back to 22,005 s.
- The service owns rasterization. The renderer is one module against two pinned libraries and follows the library's
  own renderer call for call (`init_forms`, BGR order, EXIF orientation, every TIFF frame), and its unit tests pin
  the shape and the channel order.
- `OCR_PAGE_TIMEOUT_SECONDS`, `OCR_MAX_INFERENCE_PIXELS`, `OCR_DETECTOR_MAX_SIDE` and `OCR_SCRATCH_DIR` are gone. A
  leftover value in an environment is ignored.
- Every figure is from synthetic pages. `normal` mode's own time is unmeasured and bounded above by `high`'s.

## Amendment (2026-09-25): the container measurement

Measured again in a Linux container with 4 CPUs, image `7b2cb25e7360`, PaddleOCR 3.7.0, as the cgroup's
`memory.peak`, the worst of three runs for memory and the fastest of three for time:

| Engine | Page | Mode | Detection bound | Peak | Wall time | Lines exact |
|---|---|---|---|---|---|---|
| `PP-OCRv6_small` pair | A4, 300 dpi, 50 lines | `high` | 1536 | 1016 MiB | 20.5 s | 50 of 50 |
| `PP-OCRv6_small` pair | 4200 x 4200 px, 50 lines | `high` | 1536 | 1236 MiB | 24.6 s | 50 of 50 |
| `PP-OCRv6_small` pair | 3162 x 4200 px photos, straightened, worst of six | `high` | 1536 | 2771 MiB | 28.4 s | 19 of 21 |
| `PP-OCRv6_small` pair | 2100 x 2100 px, 50 lines | `normal` | 1024 | 858 MiB | 18.3 s | 49 of 50 |
| `PP-OCRv5_server_det`, `korean` page | A4, 300 dpi, 50 lines | `high` | 1536 | 9297 MiB | 71.2 s | 16 of 50 |
| `PP-OCRv5_server_det`, `korean` page | 4200 x 4200 px, 50 lines | `high` | 1536 | 12754 MiB | 96.0 s | 11 of 50 |
| `PP-OCRv5_server_det`, `korean` page | 2100 x 2100 px, 50 lines | `normal` | 1024 | 5958 MiB | 51.4 s | 8 of 50 |

The straightened row's peak and time come from different photos: 2771 MiB from the one turned 90 degrees, 28.4 s
from the flat one. Both read 19 of 21 lines exactly.

`MEASURED_WORST_PAGE_SECONDS` now holds 28.4 s for `PP-OCRv6_small_det`, the straightened photo, because a caller
may ask for `straighten` and the worst page a caller can send is the one the allowance has to cover. It holds 96.0 s
for `PP-OCRv5_server_det`. `ru` and `korean` are switched off
([ADR-011](ADR-011-explicit-preprocessing-and-straighten.md)), so no supported language loads the server detector,
and its figure now only prices a detector nobody measured. Every duration in the table above follows, in its
third column from the right. A dense A4 prose page then measured slower than every page here, 50.4 s straightened,
and held the small detector's figure from [ADR-011](ADR-011-explicit-preprocessing-and-straighten.md)'s second
amendment, in the second column from the right. Those times were measured while PaddleOCR ran its own 10 threads
throttled under the 4-CPU quota. With the engine's threads capped to the container's CPUs, ADR-011's third amendment
measures the dense Polish page at 25.1 s, the slowest page on the small detector, in the right-hand column.

Two statements in this record do not survive the measurement. `high` is not free in memory: its largest page peaks
at 1236 MiB against 858 MiB for `normal`'s. And the consequence about a queue of Russian pages no longer applies,
because Russian is not read at all. `normal` mode's time, which the Consequences call unmeasured, is now measured at
18.3 s, still below `high`'s 24.6 s.

## Alternatives considered

- **Set `PADDLE_PDX_PDF_RENDER_SCALE` in the environment.** It moves the fixed value rather than removing the fixity.
- **One engine per mode.** It doubles the engine cache for a value the library accepts per call.
- **A numeric `dpi` parameter.** It hands a caller half of a pair it cannot see the other half of.
- **One allowance of 4.5 x 138.3 s for every page.** One number, but it multiplies every budget, grace, hint and
  promise for the ten languages that read in seconds by 8.5, and a worker hung on an English page would be waited on
  for ten minutes before it is replaced.

## Related

- `openspec/changes/fix-ocr-page-resolution/design.md`.
- `apps/ascend-ocr/src/service/page_renderer.py`, `src/api/limits.py`, `src/config/config.py`.
- [ADR-005](ADR-005-fixed-pdf-render-resolution.md), [ADR-006](ADR-006-detector-input-bound.md),
  [ADR-008](ADR-008-every-request-is-a-job.md).
