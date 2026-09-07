# ADR-006: Bound what text detection sees, and measure the deployed value against real documents

## Status

Accepted — 2026-09-07

## Context

The memory investigation behind `openspec/changes/stop-ocr-getting-stuck-on-large-jobs/` found that text detection
accounts for 94 percent of one inference's transient memory: 4984 of the fitted 5302 MiB per megapixel, with the
other four models in the pipeline together responsible for the remaining 318 MiB per megapixel (see that change's
`design.md`, "Where the cost goes").

The cause is one line of pipeline configuration, not the model. PaddleOCR's detection stage is configured with
`limit_type: min` and `limit_side_len: 64` (`paddlex/configs/pipelines/OCR.yaml`), a minimum-side limit that only
ever scales an image **up**. Every real page therefore reaches the detector at its full rendered resolution, while
the detection model was exported expecting a long side of 960. The only upper clamp on that path is
`max_side_limit: 4000`, which admits 16 megapixels of detector input on a square image — six times the container
memory limit, so it bounds nothing that matters in practice.

`text_det_limit_type` and `text_det_limit_side_len` are constructor parameters of `PaddleOCR.__init__`
(`paddleocr/_pipelines/ocr.py`), mapped onto the same pipeline configuration this service already builds in
`OcrService._get_engine`. Two arguments reach the fix.

## Decision

Bound the detector's input with `text_det_limit_type="max"` and `text_det_limit_side_len=OCR_DETECTOR_MAX_SIDE` on
the `PaddleOCR(...)` call, omitting both when the setting is unset so the library keeps its own default (unbounded)
behaviour. The bound is fixed for a worker process's lifetime — it is not part of the per-language engine cache key,
because every cached engine in a process shares one configuration.

**The owner's settled value is `OCR_DETECTOR_MAX_SIDE=1536`.** Three candidates were measured against real
documents — 960, 1280, and 1536 — and 1536 was chosen as near lossless: testing across five real documents found
1536 preserved detail that 1280 lost (dotted separators on a form) and that 960 lost more severely (genuine
footnotes from a legal opinion). The host running the container was also raised from 15.5 GiB to 23.5 GiB of memory
during this evaluation, which removed the swap pressure that would otherwise have forced a tighter bound purely for
host stability rather than for the container's own limit.

### What the measured alternatives cost, for the next person choosing a value

| Detector bound | Predicted peak on one A4 page | Downscale applied to a 1190x1684 page | What was lost, in the one measured sample point |
|---|---|---|---|
| none (today's library default) | 11.0 GiB | none | — |
| **1536 (deployed)** | ~9.2-9.8 GiB (page-count and cache-state dependent; see the live measurement in the change's task 8.9 report) | 0.91 | Near lossless across five real documents |
| 1280 | 6.8 GiB | 0.76 | Lost dotted separators on a form |
| 960 | 4.1 GiB | 0.57 | 28 of 29 lines detected vs 29 of 29 unbounded (mean confidence 0.9834 vs 0.9869); lost genuine footnotes from a legal opinion |

The loss at a lower bound is in detection, not recognition. The detector works on the downscaled image and its boxes
are mapped back onto the full-resolution page for cropping, so recognition still reads at full resolution — a lower
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
sizes) — see `openspec/changes/stop-ocr-getting-stuck-on-large-jobs/design.md`, "The pixel ceiling, recomputed" and
task 1.6 in `tasks.md`. A worst-case square image near that ceiling is not covered by the same headroom a page-shaped
(non-square) document gets from the same bound, which is why the ceiling stays conservative rather than rising to
match A4's full affordability under 1536.

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
- `OCR_MAX_INFERENCE_PIXELS` must be revisited if `OCR_DETECTOR_MAX_SIDE` changes, and vice versa — see the pixel
  ceiling section above. They are documented and tested together (`tests/config/test_config.py`,
  `tests/api/test_limits.py`).
- The bound is not part of the engine cache key (`tests/service/test_ocr_service.py::TestOcrServiceEngineCache::
  test_cache_key_is_language_only_regardless_of_detector_bound`), so changing it requires a process restart to take
  effect on already-warmed engines, matching how every other engine constructor argument behaves today.

## Related

- `openspec/changes/stop-ocr-getting-stuck-on-large-jobs/design.md` — "The measured memory model", "The pixel
  ceiling, recomputed", Decision 11.
- `ascend-ocr/src/service/ocr_service.py` — `OcrService._get_engine`.
- `ascend-ocr/src/config/config.py` — `OCR_DETECTOR_MAX_SIDE`, `OCR_MAX_INFERENCE_PIXELS`.
- `ascend-ocr/src/api/limits.py` — the pixel ceiling enforced at the request boundary, before any worker is touched.
- [ADR-005](ADR-005-fixed-pdf-render-resolution.md) — the fixed rendering resolution this bound is deployed against.
