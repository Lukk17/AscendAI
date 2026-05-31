# OCR Polish canary: e2e test

## What this verifies

- `POST /v1/ocr` with the `argent-saga-chronicles-page1-polish.png` fixture and `lang=pl` returns HTTP 200.
- The response body parses as an `OcrJsonResponse` with `filename`, `language`, `pages`, `processing_time_seconds`.
- `language` is a non-empty string (PaddleOCR returns its configured `DEFAULT_LANGUAGE`, currently `"en"`, regardless of the per-request `lang` parameter — the real proof the Polish model engaged is the Polish-character assertion below).
- The concatenated `pages[*].lines[*].text` (case-insensitive) contains the canary substring `Saga Świetlna`, `Aenaria`, or `Eklipsą`.
- The concatenated extracted text contains at least one Polish-specific accented character from the set
  `{ś, ż, ą, ę, ć, ó, ł, ń, ź}` — this is the assertion that proves the Polish model loaded (and not the English
  model returning ASCII-only extractions).
- Each `OcrTextLine.confidence` is a finite number in `[0.0, 1.0]`.
- `processing_time_seconds` is a finite non-negative number.

## Prerequisites

Check Bruno CLI is installed.

```powershell
bru --version
```

Expect a version string.

Check the PaddleOCR server is reachable.

```powershell
curl -fsS http://localhost:7022/health
```

Expect HTTP 200 with `"status":"ok"` in the body.

Check the Polish canary fixture exists.

```powershell
Test-Path PaddleOCR/e2e/fixtures/argent-saga-chronicles-page1-polish.png
```

Expect `True`. If missing, generate it per [`PaddleOCR/e2e/fixtures/README.md`](../fixtures/README.md) using a font
that supports Polish glyphs.

## Reset state

None. OCR is stateless except for the warmed engine cache. The first call against `lang=pl` may pay a one-time
engine-load cost if the Polish model has not been touched since container startup; this affects `processing_time_seconds`
but not the assertion outcome.

## Run

Single Bruno request.

```powershell
cd docs/api/request/AscendAI
```

```powershell
bru run "paddle-ocr/testing/ocr-polish.yml" --env ascend-local
```

## Expected

- HTTP 200.
- Response body matches the `OcrJsonResponse` schema.
- `language` is a non-empty string (PaddleOCR returns `DEFAULT_LANGUAGE`, not the per-request `lang`).
- `filename` equals `"argent-saga-chronicles-page1-polish.png"`.
- `pages` is non-empty.
- The concatenated text from `pages[*].lines[*].text` (case-insensitive) contains the substring `Saga Świetlna`, `Aenaria`, or `Eklipsą`.
- The same concatenated text contains at least one character from `{ś, ż, ą, ę, ć, ó, ł, ń, ź}` (or their uppercase
  forms).
- For every `OcrTextLine`: `confidence` is a finite number in `[0.0, 1.0]`; `bounding_box` is a list of `[x, y]`
  pairs.
- `processing_time_seconds` is a finite non-negative number.

## Fixtures

- [`PaddleOCR/e2e/fixtures/argent-saga-chronicles-page1-polish.png`](../fixtures/argent-saga-chronicles-page1-polish.png) — black `Saga Świetlna / Aenaria / Eklipsą` text
  on a white background, single line, ~100 pt sans-serif font with Latin Extended-A glyph support.
