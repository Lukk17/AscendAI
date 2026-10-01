# ADR-006: Bound what text detection sees, and measure the deployed value against real documents

## Status

Accepted, 2026-09-07. Amended, 2026-09-24: the detector this was measured against is no longer the one most
requests load, and the cache key it refers to is no longer the language (see "Amendment" below). Partly superseded,
2026-09-24, by [ADR-010](ADR-010-quality-modes-and-service-side-rendering.md) (see "Second amendment" below): the
bound now belongs to a request's quality mode, and the pixel ceiling it was deployed with is gone. Amended again,
2026-09-25: every memory figure below is superseded by a container measurement, and no supported language loads
`PP-OCRv5_server_det` any more (see "Third amendment" below).

## Context

The memory investigation behind `openspec/changes/stop-ocr-getting-stuck-on-large-jobs/` found that text detection
accounts for 94 percent of one inference's transient memory: 4984 of the fitted 5302 MiB per megapixel, with the
other four models in the pipeline together responsible for the remaining 318 MiB per megapixel (see that change's
`design.md`, "Where the cost goes").

The cause is one line of pipeline configuration, not the model. PaddleOCR's detection stage is configured with
`limit_type: min` and `limit_side_len: 64` (`paddlex/configs/pipelines/OCR.yaml`), a minimum-side limit that only
ever scales an image **up**. Every real page therefore reaches the detector at its full rendered resolution, while
the detection model was exported expecting a long side of 960. The only upper clamp on that path is
`max_side_limit: 4000`, which admits 16 megapixels of detector input on a square image - six times the container
memory limit, so it bounds nothing that matters in practice.

`text_det_limit_type` and `text_det_limit_side_len` are constructor parameters of `PaddleOCR.__init__`
(`paddleocr/_pipelines/ocr.py`), mapped onto the same pipeline configuration this service already builds in
`OcrService._get_engine`. Two arguments reach the fix.

## Decision

Bound the detector's input with `text_det_limit_type="max"` and `text_det_limit_side_len=OCR_DETECTOR_MAX_SIDE` on
the `PaddleOCR(...)` call, omitting both when the setting is unset so the library keeps its own default (unbounded)
behaviour. The bound is fixed for a worker process's lifetime - it is not part of the engine cache key, because every
cached engine in a process shares one configuration.

**The owner's settled value is `OCR_DETECTOR_MAX_SIDE=1536`.** Three candidates were measured against real
documents - 960, 1280, and 1536 - and 1536 was chosen as near lossless: testing across five real documents found
1536 preserved detail that 1280 lost (dotted separators on a form) and that 960 lost more severely (genuine
footnotes from a legal opinion). The host running the container was also raised from 15.5 GiB to 23.5 GiB of memory
during this evaluation, which removed the swap pressure that would otherwise have forced a tighter bound purely for
host stability rather than for the container's own limit.

### What the measured alternatives cost, for the next person choosing a value

| Detector bound | Predicted peak on one A4 page | Downscale applied to a 1190x1684 page | What was lost, in the one measured sample point |
|---|---|---|---|
| none (today's library default) | 11.0 GiB | none | - |
| **1536 (deployed)** | ~9.2-9.8 GiB (page-count and cache-state dependent; see the live measurement in the change's task 8.9 report) | 0.91 | Near lossless across five real documents |
| 1280 | 6.8 GiB | 0.76 | Lost dotted separators on a form |
| 960 | 4.1 GiB | 0.57 | 28 of 29 lines detected vs 29 of 29 unbounded (mean confidence 0.9834 vs 0.9869); lost genuine footnotes from a legal opinion |

The predicted peaks in this table are superseded by the container measurement in the third amendment below. They
were the fitted model's predictions for `PP-OCRv5_server_det` on a 144 dpi page, and stay here as the record of what
the choice of 1536 was made against.

The loss at a lower bound is in detection, not recognition. The detector works on the downscaled image and its boxes
are mapped back onto the full-resolution page for cropping, so recognition still reads at full resolution - a lower
bound means small lines stop being *found* at all, not that found text is misread. Decision 10's rule of thumb (a
line needs roughly 20 px of height at the library's fixed 144 dpi, [ADR-005](ADR-005-fixed-pdf-render-resolution.md))
scales inversely with the bound: 1536 keeps the reliable floor near 11 pt, 1280 near 13 pt, 960 near 17 pt. These are
extrapolations from one rule of thumb, which is why the deployed value was chosen by measuring the owner's own
documents rather than read off this table.

### The pixel ceiling this bound is deployed with

`OCR_MAX_INFERENCE_PIXELS` and `OCR_DETECTOR_MAX_SIDE` are one decision expressed as two settings and neither is safe
deployed alone: an unbounded detector forces the pixel ceiling under 2 megapixels to stay memory-safe, which refuses
A4 and US Legal outright; a bound deployed without a correspondingly raised ceiling changes nothing the caller can
submit. They ship together at `1536` / `2,500,000`, the pair `design.md`'s own concluding guidance settles on as
defensible pending its task 1.6 (confirming the residual memory model at ceilings further above the standard page
sizes) - see `openspec/changes/stop-ocr-getting-stuck-on-large-jobs/design.md`, "The pixel ceiling, recomputed" and
task 1.6 in `tasks.md`. A worst-case square image near that ceiling is not covered by the same headroom a page-shaped
(non-square) document gets from the same bound, which is why the ceiling stays conservative rather than rising to
match A4's full affordability under 1536.

## Amendment (2026-09-24): a different detector, and a different cache key

[ADR-007](ADR-007-explicit-ocr-model-selection.md) replaced the detector every measurement above was taken against.
Three statements in this record need reading in that light, and none of the measurements themselves changes: they
were taken against `PP-OCRv5_server_det` and remain true of it.

**Which detector.** `PP-OCRv5_server_det` is now loaded only by `ru` and `korean`. Every other supported language
loads `PP-OCRv6_small_det`. So the 94 percent detection share, the 4984 MiB per megapixel, and every predicted peak
in the table above are exact for those two languages and an upper bound for the rest, until someone re-measures on a
host with memory to spare (task 4.6 of `openspec/changes/upgrade-ocr-to-ppocrv6/tasks.md`).

**The export geometry.** The Context section says the detection model "was exported expecting a long side of 960",
which is a statement about `PP-OCRv5_server_det`. The corresponding figure for `PP-OCRv6_small_det` has not been
read, so nothing here should be taken as saying what the new detector expects. What does not depend on the model is
the cause the section identifies: the pipeline's `limit_type: min` with `limit_side_len: 64` still only ever scales
an image up, unchanged in `paddlex/configs/pipelines/OCR.yaml` at 3.7.2, so the bound is as necessary as it was.

**The cache key.** When this was written the cache was keyed by the language, and the Decision section said the
bound was not part of that key. The key is now the resolved model pair, and the bound is still not part of it, for
the same reason: every engine in a process shares one bound. The test that pins it is
`tests/service/test_ocr_service.py::TestOcrServiceEngineCache::test_cache_key_is_the_model_pair_regardless_of_detector_bound`.

**What has not changed.** `OCR_DETECTOR_MAX_SIDE` is still 1536, `OCR_MAX_INFERENCE_PIXELS` is still 2,500,000, and
they are still one decision in two settings. Whether a smaller detector affords a different pair is an open question
in that change's design, deliberately not answered by it.

## Second amendment (2026-09-24): the bound belongs to a quality mode, and it does affect recognition

**What is superseded.** `OCR_DETECTOR_MAX_SIDE` is deleted. The bound is no longer one value fixed at engine
construction for a process's lifetime. Each quality mode carries its own bound in a locked pair with its render
resolution, `OCR_QUALITY_NORMAL=150:1024` and `OCR_QUALITY_HIGH=300:1536`, and the bound is passed on every
`predict_iter` call. The owner's settled 1536 survives as the `high` bound, which is the default mode. Leaving the bound
unset is no longer possible, because every mode names one. The engine cache is still keyed by the model pair alone,
now because the bound is not a construction argument at all.

`OCR_MAX_INFERENCE_PIXELS` is deleted with it. "The pixel ceiling this bound is deployed with" above no longer
describes the service: an oversized page is shrunk to the largest size its mode supports and then read, and the only
pixel refusal left is `OCR_MAX_SOURCE_PIXELS`, a decompression-bomb guard on raster images.

**What is corrected.** The Decision section says "the loss at a lower bound is in detection, not recognition" and that
"a lower bound means small lines stop being found at all, not that found text is misread". That is false. With a bound
of 512, a page rendered at 144 dpi (a 3.3x downscale) read 28 of 28 lines correctly, and the same page rendered at
300 dpi (a 6.85x downscale) had every line found and every line read as garbage. Recognition does crop from the
full-resolution page, so the likely mechanism is that boxes found on a heavily downscaled image are too coarse once
scaled back, and the crops cut into the glyphs. That mechanism is a hypothesis. The measurement is not. What decides
recognition quality is the ratio of the rendered long side to the bound, and ADR-010 refuses at startup any pair whose
ratio exceeds 3.3x, the largest measured to read cleanly.

**What is corrected about the fitted model.** The first amendment calls the fitted model's figures "exact" for `ru`
and `korean`. They are not: the fitted model was taken on PaddleOCR 3.6.0, and on the installed 3.7.0
`PP-OCRv5_server_det` measured 539 MB for an A4 page at 144 dpi bounded to 1536, 720 MB unbounded at 144 dpi, 807 MB
unbounded at 300 dpi and 510 MiB for a 4200 x 4200 px page bounded to 1536. The fitted model is void for every pair.

## Third amendment (2026-09-25): the container measurement

Every figure the second amendment quotes, and the statement that the fitted model is void for every pair, came from
a probe that sampled memory at intervals and missed the peak. Measured as a Linux container's cgroup `memory.peak`,
4 CPUs, image `7b2cb25e7360`, worst of three runs:

| Engine | Page | Detection bound | Superseded figure | Container peak |
|---|---|---|---|---|
| `PP-OCRv6_small` pair | A4, 300 dpi | 1536 | about 440 MB | 1016 MiB |
| `PP-OCRv6_small` pair | 4200 x 4200 px | 1536 | 501 MiB | 1236 MiB |
| `PP-OCRv6_small` pair | 2100 x 2100 px | 1024 | 394 MiB | 858 MiB |
| `PP-OCRv5_server_det`, `korean` page | A4, 300 dpi | 1536 | 539 MB at 144 dpi | 9297 MiB |
| `PP-OCRv5_server_det`, `korean` page | 4200 x 4200 px | 1536 | 510 MiB | 12754 MiB |
| `PP-OCRv5_server_det`, `korean` page | 2100 x 2100 px | 1024 | 517 MiB | 5958 MiB |

So the fitted model is not void for `PP-OCRv5_server_det` after all: it runs 22 to 41 percent above the container measurement of that detector (11,727 MiB predicted against 9297 measured on the A4 page at 300 dpi, 18,015 against 12,754 on the 4200 x 4200 page, 7275 against 5958 on the 2100 x 2100 page), and eleven to fifteen times above it on the small pair. The server detector's peaks are why `ru` and `korean` are switched off: the worst was above the 12 GiB limit
the container then carried (see [ADR-011](ADR-011-explicit-preprocessing-and-straighten.md)). The bound itself is
unchanged: 1536 in `high` mode and 1024 in `normal`.

## Rejected alternatives

**Leave the pipeline configuration alone and rely on the pixel ceiling.** Rejected: that ceiling then has to sit
below the pages this service exists to read, making the service safe and useless at once.

**Cut the page into overlapping pieces and reassemble the result** (the approach the superseded
`add-ocr-full-resolution-reading` change proposed). Rejected: it reaches a similar per-inference input size through
joining, duplicate removal, and reading-order reconstruction that this service would then own forever, where two
constructor arguments reach the same place with nothing to maintain.

**Pick a single default and not expose the setting.** Rejected: this is an accuracy trade against small text, which
is exactly what varies most between operators' real documents, so the setting is built, the candidates and their
costs are stated here, and the deployed value is chosen by measurement rather than guessed.

## Consequences

- Detected accuracy on very small text is a function of `OCR_DETECTOR_MAX_SIDE`. Lowering it trades detected lines
  for memory; the deployed 1536 was chosen to be the least aggressive of the three measured points while still
  reducing an A4 page's cost from 92 percent of the container limit to a level with real headroom.
- `OCR_MAX_INFERENCE_PIXELS` must be revisited if `OCR_DETECTOR_MAX_SIDE` changes, and vice versa - see the pixel
  ceiling section above. They are documented and tested together (`tests/config/test_config.py`,
  `tests/api/test_limits.py`).
- The bound is not part of the engine cache key (`tests/service/test_ocr_service.py::TestOcrServiceEngineCache::
  test_cache_key_is_the_model_pair_regardless_of_detector_bound`), so changing it requires a process restart to take
  effect on already-warmed engines, matching how every other engine constructor argument behaves today.

## Related

- `openspec/changes/stop-ocr-getting-stuck-on-large-jobs/design.md` - "The measured memory model", "The pixel
  ceiling, recomputed", Decision 11.
- `apps/ascend-ocr/src/service/ocr_service.py` - `OcrService._get_engine`.
- `apps/ascend-ocr/src/config/config.py` - `OCR_DETECTOR_MAX_SIDE`, `OCR_MAX_INFERENCE_PIXELS`.
- `apps/ascend-ocr/src/api/limits.py` - the pixel ceiling enforced at the request boundary, before any worker is touched.
- [ADR-005](ADR-005-fixed-pdf-render-resolution.md) - the fixed rendering resolution this bound is deployed against.
