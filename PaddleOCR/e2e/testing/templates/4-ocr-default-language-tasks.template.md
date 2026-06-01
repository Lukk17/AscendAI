# OCR default-language fallback: run tasks template

Spec: [../4-ocr-default-language-test.md](../4-ocr-default-language-test.md)

Copy this file to `../runs/<UTC-timestamp>_4-ocr-default-language-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [ ] Bruno CLI present (`bru --version` returns a version)
- [ ] PaddleOCR `/health` returns HTTP 200 with `"status":"ok"`
- [ ] `PaddleOCR/e2e/fixtures/argent-saga-chronicles-page1.png` exists
- [ ] Container `DEFAULT_LANGUAGE` is `en` (the shipped default; absence of the env var also means `en`)

### Reset state

- [ ] None required

### Run

- [ ] Send `ocr-default-lang.yml` via `bru run` and wait for HTTP 200

### Expected

- [ ] HTTP 200
- [ ] Response body matches `OcrJsonResponse` schema
- [ ] `language="en"` (the server's `DEFAULT_LANGUAGE`)
- [ ] `filename="argent-saga-chronicles-page1.png"`
- [ ] `pages` is non-empty
- [ ] Concatenated `pages[*].lines[*].text` (case-insensitive) contains `Argent Saga`, `Aenaria`, or `Halen Veyr`
- [ ] `processing_time_seconds` is a finite non-negative number

### Verdict

- [ ] Verdict: PASS / FAIL (delete the wrong one)

## Result summary



Input tokens: 0

Output tokens: 0

Start (UTC):

End (UTC):

Duration:

---

## Additional tasks I did

<!-- Optional. List anything outside the spec, e.g. diagnostic curls, manual log inspection, retries with different inputs. Leave empty if nothing extra. -->
