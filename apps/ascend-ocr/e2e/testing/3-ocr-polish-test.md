# OCR Polish canary: e2e test

## What this verifies

- `POST /v1/ocr` with the `argent-saga-chronicles-page1-polish.png` fixture and `lang=pl` returns HTTP 200.
- The response body parses as an `OcrJsonResponse` with `filename`, `language`, `pages`, `processing_time_seconds`.
- `language` equals `"pl"`, echoing the per-request `lang` parameter — the Polish-character assertion below is a
  second, independent proof that the Polish model actually engaged.
- The concatenated `pages[*].lines[*].text` (case-insensitive) contains the canary substring `Saga Świetlna`, `Aenaria`, or `Eklipsą`.
- The concatenated extracted text contains at least one Polish-specific accented character from the set
  `{ś, ż, ą, ę, ć, ó, ł, ń, ź}` — this is the assertion that proves the Polish model loaded (and not the English
  model returning ASCII-only extractions).
- Each `OcrTextLine.confidence` is a finite number in `[0.0, 1.0]`.
- `processing_time_seconds` is a finite non-negative number.

**Corrected expectation (2026-09-08).** Earlier revisions of this spec asserted that the service returned its
configured `DEFAULT_LANGUAGE` regardless of the per-request `lang`, and treated that as intended design. It was not
design, it was a bug: the REST endpoint declared `lang` without a form-field marker, so FastAPI read it as a query
parameter and never saw the multipart form value, meaning every REST OCR request ran the English model no matter
what it asked for. This spec now asserts the behaviour that should always have been true — a Polish request comes
back tagged `"pl"` — instead of the bug's symptom.

## Prerequisites

Check Bruno CLI is installed.

```bash
bru --version
```

Expect a version string.

Check the ascend-ocr server is reachable.

```bash
curl -fsS http://localhost:7022/health
```

Expect HTTP 200 with `"status":"ok"` in the body.

Check the Polish canary fixture exists.

```bash
ls apps/ascend-ocr/e2e/fixtures/argent-saga-chronicles-page1-polish.png
```

Expect the file path printed. If missing, generate it per [`apps/ascend-ocr/e2e/fixtures/README.md`](../fixtures/README.md) using a font
that supports Polish glyphs.

## Reset state

None. OCR is stateless except for the warmed engine cache. The first call against `lang=pl` may pay a one-time
engine-load cost if the Polish model has not been touched since container startup; this affects `processing_time_seconds`
but not the assertion outcome.

## Run

Single Bruno request.

```bash
cd docs/api/request/AscendAI
```

```bash
bru run "ocr/testing/ocr-polish.yml" --env ascend-local
```

## Expected

- HTTP 200.
- Response body matches the `OcrJsonResponse` schema.
- `language` equals `"pl"` (the per-request `lang` parameter, correctly echoed — see "Corrected expectation" above).
- `filename` equals `"argent-saga-chronicles-page1-polish.png"`.
- `pages` is non-empty.
- The concatenated text from `pages[*].lines[*].text` (case-insensitive) contains the substring `Saga Świetlna`, `Aenaria`, or `Eklipsą`.
- The same concatenated text contains at least one character from `{ś, ż, ą, ę, ć, ó, ł, ń, ź}` (or their uppercase
  forms).
- For every `OcrTextLine`: `confidence` is a finite number in `[0.0, 1.0]`; `bounding_box` is a list of `[x, y]`
  pairs.
- `processing_time_seconds` is a finite non-negative number.

## Fixtures

- [`apps/ascend-ocr/e2e/fixtures/argent-saga-chronicles-page1-polish.png`](../fixtures/argent-saga-chronicles-page1-polish.png) — black `Saga Świetlna / Aenaria / Eklipsą` text
  on a white background, single line, ~100 pt sans-serif font with Latin Extended-A glyph support.

## Concurrency

**Engine-bound. Must run sequentially relative to other engine specs (2, 3, 4, 6).**

Same constraint as spec 2, roughly 60 to 110 s of full round trip per call on this deployment's 4-core CPU
allocation. See spec 2's Concurrency section for the measured baseline and how engine time separates from round
trip. On top of that there is a one-time cost: the Polish engine is NOT pre-warmed at container startup (only
`DEFAULT_LANGUAGE`, currently `en`, warms during the lifespan). The first `lang=pl` request triggers an in-request
model load that adds further latency, which is part of why this spec measured 99.9 s of round trip during the
2026-09-03 sweep while four other module suites were hitting the same host. That model load has never been timed on
its own. Combined with concurrent calls on other engine specs the timeout window is exhausted before the first
response is produced. Run sequentially.

Safe to run in parallel with: reject-fast specs (1, 5, 7, 8, 9, 10, 11, 12). Unsafe with: 2, 3, 4, 6.

See [`apps/ascend-ocr/e2e/testing/README.md`](README.md) "Execution order".
