# ADR-005: The fixed 144 dpi PDF rendering resolution is accepted, recorded, and not exposed

## Status

Accepted — 2026-09-07

## Context

PaddleOCR rasterizes every PDF page at `PDF_RENDER_SCALE = 2.0` (`paddlex/utils/flags.py`, read from the module's own
`.venv`), which is 144 dpi on PDF points. Neither this service nor its caller has any say in that number: it is
baked into the library's `PDFReader`, not a parameter on the `PaddleOCR(...)` constructor this service calls. A
page's cost to this service therefore depends on its physical page size and not at all on the resolution it was
scanned at, because the library discards that information at rasterization time — a 300 dpi and a 600 dpi scan of
the same physical page cost the same to read.

This was invisible until the memory investigation behind
`openspec/changes/stop-ocr-getting-stuck-on-large-jobs/` measured what one page actually costs. The fitted model is

```text
peak_MiB = 635 + 5302 x megapixels_of_the_largest_single_page + 11.5 x pages
```

fitted at a correlation of 0.9993 across six input sizes (see that change's `design.md`, "The measured memory
model"). At 144 dpi, A4 rasterizes to 1190x1684, 2.004 megapixels. Unbounded, that page costs 11,260 MiB against a
12,288 MiB container limit — 92 percent of it, before the engine's own per-language cache is even counted. US Letter
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
to be recognised dependably, which at 144 dpi puts the smallest reliable type at about 10 pt — body text sits right
at that edge, so small print and dense tables are where this constraint is felt. Large-format pages are affected the
other way: an A0 poster at 144 dpi is 32 megapixels, far above the pixel ceiling, so it is refused rather than
downscaled.

### Rejected: raising `PADDLE_PDX_PDF_RENDER_SCALE`

Cost grows with the square of the scale, so 300 dpi is a little over four times the pixels and therefore roughly
four times the memory of a path whose memory is already the live problem. Unbounded, an A4 page at 300 dpi is 8.7
megapixels and the fitted model prices it at 46.7 GiB — not a trade-off, an impossibility. With the detector bounded
to 960 (see ADR-006) the detector's own share stops growing with input size and the same page prices at roughly 7.7
GiB, which is arithmetically feasible but untested, and rendering higher only to downscale again for detection buys
quality solely in text recognition, which the ADR-006 measurement shows was never the part that suffered. Recorded
here as a follow-up question with its numbers attached, not as work this change does.

### Rejected: exposing the render scale as a per-request parameter

It hands a caller a lever that multiplies the memory cost of a shared single worker (see the worker-count reasoning
in ADR-006 and `src/config/config.py`'s `OCR_WORKER_COUNT` comment) — precisely the failure mode
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

- `openspec/changes/stop-ocr-getting-stuck-on-large-jobs/design.md` — "The measured memory model", Decision 10.
- `ascend-ocr/src/api/limits.py` — `PDF_RENDER_SCALE`, `_inspect_pdf`.
- [ADR-006](ADR-006-detector-input-bound.md) — the bound that makes an A4 page affordable, not merely predictable.
