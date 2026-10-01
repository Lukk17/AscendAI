# ADR-005: The fixed 144 dpi PDF rendering resolution is accepted, recorded, and not exposed

## Status

Accepted, 2026-09-07. Superseded, 2026-09-24, by
[ADR-010](ADR-010-quality-modes-and-service-side-rendering.md): the service now renders every PDF page itself with
pypdfium2, at the resolution the request's quality mode names, and the library's fixed 144 dpi is off the path.

## Why this was superseded

Every reason given below for accepting 144 dpi rested on a memory model that the upgrade to PaddleOCR 3.7.0 voided.
The fitted model priced one A4 page at 300 dpi at 46.7 GiB unbounded and 7.7 GiB with detection bounded to 960. The
measured cost on 3.7.0, with detection bounded to 1536, is about 440 MB on the `PP-OCRv6_small` pair, flat between
144 and 300 dpi, and 510 MiB on `PP-OCRv5_server_det` for a 4200 x 4200 px page. (Corrected 2026-09-25: both
figures came from a probe that sampled memory at intervals and missed the peak. Measured as a Linux container's
cgroup peak, an A4 page at 300 dpi costs 1016 MiB on the small pair and a 4200 x 4200 px page 1236 MiB, against
12754 MiB on `PP-OCRv5_server_det`. The 144 dpi case was not re-measured in the container. See "Memory model and the
single worker" in [07-deployment-view.md](../arc42/07-deployment-view.md).) The cost of the higher resolution
this record refused turned out to be nothing in memory, and the quality it bought turned out not to be confined to
recognition: see the correction in ADR-006's second amendment.

The three rejected alternatives below are each overturned or reshaped by ADR-010. Raising the render scale is done
per request instead of process-wide. Exposing resolution to a caller is done as a choice between two locked pairs,
never as a number, which answers the concern that a caller would multiply the cost of the shared worker: both pairs
are bounded by the same measured ceiling. Rasterizing in the service is what ADR-010 does, in one module that follows
the library's own renderer call for call.

The rest of this record is kept as it was written, with the one figure that is now wrong corrected where it
stands.

## Context

PaddleOCR rasterizes every PDF page at `PDF_RENDER_SCALE = 2.0` (`paddlex/utils/flags.py`, read from the module's own
`.venv`), which is 144 dpi on PDF points. Neither this service nor its caller has any say in that number: it is
baked into the library's `PDFReader`, not a parameter on the `PaddleOCR(...)` constructor this service calls. A
page's cost to this service therefore depends on its physical page size and not at all on the resolution it was
scanned at, because the library discards that information at rasterization time - a 300 dpi and a 600 dpi scan of
the same physical page cost the same to read.

This was invisible until the memory investigation behind
`openspec/changes/stop-ocr-getting-stuck-on-large-jobs/` measured what one page actually costs. The fitted model is

```text
peak_MiB = 635 + 5302 x megapixels_of_the_largest_single_page + 11.5 x pages
```

fitted at a correlation of 0.9993 across six input sizes (see that change's `design.md`, "The measured memory
model"). At 144 dpi, A4 rasterizes to 1190x1684, 2.004 megapixels. Unbounded, that page costs 11,260 MiB against a
12,288 MiB container limit - 92 percent of it, before the engine's own per-language cache is even counted. US Letter
(1.94 MP) and US Legal (2.47 MP) land at 10,921 MiB and 13,731 MiB respectively. Predictable is not the same as low.

## Decision

Accept the library's fixed 144 dpi rasterization as given. Do not build a way to configure it, and do not rasterize
PDF pages inside this service instead of letting the library do it.

**What it buys.** A hard, predictable per-page memory bound for every document, with no work by this service: a
page's cost depends only on its physical dimensions, which are known from the PDF header before any page is
rendered (see [ADR-006](ADR-006-detector-input-bound.md) and `src/api/limits.py`). That predictability is what makes
the pixel ceiling and the detector bound in ADR-006 computable at all.

**What it costs, named rather than buried.** A dense scan cannot be read at higher quality even when the caller
knows it needs to be, and there is no way to ask. A rule of thumb is that a text line needs roughly 20 px of height
to be recognised dependably, which at 144 dpi puts the smallest reliable type at about 10 pt - body text sits right
at that edge, so small print and dense tables are where this constraint is felt. Large-format pages are affected the
other way: an A0 poster at 144 dpi is 32 megapixels, far above the pixel ceiling, so it is refused rather than
downscaled.

### Rejected: raising `PADDLE_PDX_PDF_RENDER_SCALE`

Cost grows with the square of the scale, so 300 dpi is a little over four times the pixels and therefore roughly
four times the memory of a path whose memory is already the live problem. Unbounded, an A4 page at 300 dpi is 8.7
megapixels and the fitted model prices it at 46.7 GiB, not a trade-off but an impossibility. (Corrected 2026-09-24:
the fitted model does not describe PaddleOCR 3.7.0 for any engine. Measured, the same page costs 807 MB unbounded on
`PP-OCRv5_server_det` and about 440 MB bounded to 1536 on the `PP-OCRv6_small` pair. Corrected again 2026-09-25:
both figures missed the peak, and the container measurement puts the bounded page at 1016 MiB on the small pair.)
With the detector bounded
to 960 (see ADR-006) the detector's own share stops growing with input size and the same page prices at roughly 7.7
GiB, which is arithmetically feasible but untested, and rendering higher only to downscale again for detection buys
quality solely in text recognition, which the ADR-006 measurement shows was never the part that suffered. Recorded
here as a follow-up question with its numbers attached, not as work this change does.

### Rejected: exposing the render scale as a per-request parameter

It hands a caller a lever that multiplies the memory cost of a shared single worker (see the worker-count reasoning
in ADR-006 and `src/config/config.py`'s `OCR_WORKER_COUNT` comment) - precisely the failure mode
`stop-ocr-getting-stuck-on-large-jobs` exists to close. It is also a future need rather than a current one.

### Rejected: rasterizing in this service instead of letting the library do it

Takes on ownership of rasterization across every future library upgrade, in exchange for a knob nobody has asked
for yet.

## Consequences

- Every document's memory cost is a function of its physical page size, not its scan quality. Operators reasoning
  about the pixel ceiling (`OCR_MAX_INFERENCE_PIXELS`) and the detector bound (`OCR_DETECTOR_MAX_SIDE`) can use the
  standard page sizes (A4 2.00 MP, US Letter 1.94 MP, US Legal 2.47 MP) as their reference points, unconditionally.
- No configuration knob exists for the rendering resolution, by design. A caller who needs higher-fidelity reading of
  a dense scan cannot get it from this service today.
- The 144 dpi constant is treated by `src/api/limits.py` as a fact to predict against (`PDF_RENDER_SCALE`, matching
  the library's own default), not a value this service controls.

## Related

- `openspec/changes/stop-ocr-getting-stuck-on-large-jobs/design.md` - "The measured memory model", Decision 10.
- `apps/ascend-ocr/src/api/limits.py` - `PDF_RENDER_SCALE`, `_inspect_pdf`.
- [ADR-006](ADR-006-detector-input-bound.md) - the bound that makes an A4 page affordable, not merely predictable.
