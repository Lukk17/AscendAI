# OCR English canary: e2e test

## What this verifies

- `POST /v1/ocr` with the `argent-saga-chronicles-page1.png` fixture and `lang=en` returns HTTP 200.
- The response body parses as an `OcrJsonResponse` with `filename`, `language`, `pages`, `processing_time_seconds`.
- `language` echoes back `"en"`.
- `pages` is a non-empty array; at least one `OcrPageResult` has at least one `OcrTextLine`.
- The concatenated `pages[*].lines[*].text` (case-insensitive) contains the canary substring `Argent Saga`, `Aenaria`, or `Halen Veyr`.
- Each `OcrTextLine.confidence` is a finite number in `[0.0, 1.0]`.
- Each `OcrTextLine.bounding_box` is a non-empty list of `[x, y]` coordinate pairs.
- `processing_time_seconds` is a finite non-negative number.

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

Check the English canary fixture exists.

```bash
ls apps/ascend-ocr/e2e/fixtures/argent-saga-chronicles-page1.png
```

Expect the file path printed. If missing, generate it per [`apps/ascend-ocr/e2e/fixtures/README.md`](../fixtures/README.md).

## Reset state

None. OCR is stateless except for the warmed engine cache, which is initialised at container startup for the
`DEFAULT_LANGUAGE` and re-used for every request in that language.

## Run

Single Bruno request.

```bash
cd docs/api/request/AscendAI
```

```bash
bru run "ocr/ocr.yml" --env ascend-local
```

## Expected

- HTTP 200.
- Response body matches the `OcrJsonResponse` schema.
- `language` equals `"en"`.
- `filename` equals `"argent-saga-chronicles-page1.png"`.
- `pages` is non-empty.
- The concatenated text from `pages[*].lines[*].text` (case-insensitive) contains the substring `Argent Saga`, `Aenaria`, or `Halen Veyr`.
- For every `OcrTextLine`: `confidence` is a finite number in `[0.0, 1.0]`; `bounding_box` is a list of length ≥ 1
  where each element is a list of length 2 with two finite numbers.
- `processing_time_seconds` is a finite non-negative number.

## Fixtures

- [`apps/ascend-ocr/e2e/fixtures/argent-saga-chronicles-page1.png`](../fixtures/argent-saga-chronicles-page1.png), a screenshot of page 1 of
  `apps/ascend-agent/e2e/fixtures/argent-saga-chronicle.pdf`: black body-size sans-serif text on a white background, a
  title line, two bold part headings and about 30 wrapped body lines of prose. The canary words `Argent Saga`,
  `Aenaria` and `Halen Veyr` sit in the title and the first paragraph, so the response carries roughly 30 text
  lines, not one.

## Concurrency

Engine-bound. This spec runs alone: no runner of any suite active while it is in flight, from this suite or from any other module's sweep, not even a reject-fast spec of this suite. Start it only when nothing else is running anywhere, and start nothing else until it has returned.

The reason is the engine, not the fixture. `ocr_service.process_file` invokes PaddleOCR's blocking `engine.predict` inside the OCR worker process, and the engine is single-threaded (defect register A47), so inference runs at one core's speed and any other runner on the host competes for that core. Measured on 2026-09-10 with the English fixture: 59.2 seconds of round trip on a quiet host, 160.9 seconds on a loaded one, past the 150 second per-page budget compose sets. A loaded host turns a passing run into a timeout, so raising the budget is not the fix.

Engine time, the `processing_time_seconds` the service reports for itself, measured 57.1 s and 72.4 s on isolated calls against this 212 KB fixture on 2026-09-03, and full round trip 60.7 s and 82.1 s the same day. Plan for about 60 to 110 s per call on a quiet host and read anything above that as host load, not as a hang.

Unsafe with everything: the other engine-bound specs (2, 3, 4, 6) and the reject-fast specs (1, 5, 7, 8, 9, 10, 11, 12) alike.

See [`apps/ascend-ocr/e2e/README.md`](../README.md) "Parallelism and execution order" and [`apps/ascend-ocr/e2e/testing/README.md`](README.md) "Execution order".
