# OCR default-language fallback: e2e test

## What this verifies

- `POST /v1/ocr` with the `argent-saga-chronicles-page1.png` fixture and **no** `lang` form field falls back to the server's
  `DEFAULT_LANGUAGE` setting (`"en"` out of the box per `src/config/config.py`).
- The response body's `language` field equals `"en"` — proof the server-side fallback fired, not the client.
- The concatenated `pages[*].lines[*].text` (case-insensitive) contains the canary substring `Argent Saga`, `Aenaria`, or `Halen Veyr`.
- The default-language path is functionally equivalent to the explicit `lang=en` path: both produce a populated
  `pages` array with the same canary substring.

This spec assumes the server is running with `DEFAULT_LANGUAGE=en` (the shipped default). If the deployment overrides
`DEFAULT_LANGUAGE` to a non-English value, this spec's assertion on `language="en"` is the wrong assertion to run;
update the spec to match the deployment's default before the run.

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

Expect the file path printed.

Check the running container's `DEFAULT_LANGUAGE` is `en` (the documented default). If unsure, inspect the container
environment.

```bash
docker inspect ascend-ocr --format '{{range .Config.Env}}{{println .}}{{end}}'
```

Look for `DEFAULT_LANGUAGE=en` or its absence (absence means the in-code default of `en` applies).

## Reset state

None.

## Run

Single Bruno request.

```bash
cd docs/api/request/AscendAI
```

```bash
bru run "ocr/testing/ocr-default-lang.yml" --env ascend-local
```

## Expected

- HTTP 200.
- Response body matches the `OcrJsonResponse` schema.
- `language` equals `"en"` (the server's `DEFAULT_LANGUAGE`).
- `filename` equals `"argent-saga-chronicles-page1.png"`.
- `pages` is non-empty.
- The concatenated `pages[*].lines[*].text` (case-insensitive) contains the substring `Argent Saga`, `Aenaria`, or `Halen Veyr`.
- `processing_time_seconds` is a finite non-negative number.

## Fixtures

- [`apps/ascend-ocr/e2e/fixtures/argent-saga-chronicles-page1.png`](../fixtures/argent-saga-chronicles-page1.png) — same fixture as test 2.

## Concurrency

Engine-bound. This spec runs alone: no runner of any suite active while it is in flight, from this suite or from any other module's sweep, not even a reject-fast spec of this suite. Start it only when nothing else is running anywhere, and start nothing else until it has returned.

The reason is the engine, not the fixture. `ocr_service.process_file` invokes PaddleOCR's blocking `engine.predict` inside the OCR worker process, and the engine is single-threaded (defect register A47), so inference runs at one core's speed and any other runner on the host competes for that core. Measured on 2026-09-10 with the English fixture: 59.2 seconds of round trip on a quiet host, 160.9 seconds on a loaded one, past the 150 second per-page budget compose sets. A loaded host turns a passing run into a timeout, so raising the budget is not the fix.

The fallback-to-`DEFAULT_LANGUAGE` logic is trivial. The bottleneck is identical to specs 2, 3 and 6.

Unsafe with everything: the other engine-bound specs (2, 3, 4, 6) and the reject-fast specs (1, 5, 7, 8, 9, 10, 11, 12) alike.

See [`apps/ascend-ocr/e2e/README.md`](../README.md) "Parallelism and execution order" and [`apps/ascend-ocr/e2e/testing/README.md`](README.md) "Execution order".
