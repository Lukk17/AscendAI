# OCR English canary: run tasks template

Spec: [../2-ocr-english-test.md](../2-ocr-english-test.md)

Copy this file to `../runs/<UTC-timestamp>_2-ocr-english-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [ ] Bruno CLI present (`bru --version` returns a version)
- [ ] PaddleOCR `/health` returns HTTP 200 with `"status":"ok"`
- [ ] `PaddleOCR/e2e/fixtures/argent-saga-chronicles-page1.png` exists

### Reset state

- [ ] None required

### Run

- [ ] Send `ocr-english.yml` via `bru run` and wait for HTTP 200

### Expected

- [ ] HTTP 200
- [ ] Response body matches `OcrJsonResponse` schema
- [ ] `language="en"`
- [ ] `filename="argent-saga-chronicles-page1.png"`
- [ ] `pages` is non-empty
- [ ] Concatenated `pages[*].lines[*].text` (case-insensitive) contains `Argent Saga`, `Aenaria`, or `Halen Veyr`
- [ ] Every `OcrTextLine.confidence` is a finite number in `[0.0, 1.0]`
- [ ] Every `OcrTextLine.bounding_box` is a list of `[x, y]` pairs of finite numbers
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
