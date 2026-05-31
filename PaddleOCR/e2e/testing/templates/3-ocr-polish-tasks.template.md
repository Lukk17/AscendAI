# OCR Polish canary: run tasks template

Spec: [../3-ocr-polish-test.md](../3-ocr-polish-test.md)

Copy this file to `../runs/<UTC-timestamp>_3-ocr-polish-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [ ] Bruno CLI present (`bru --version` returns a version)
- [ ] PaddleOCR `/health` returns HTTP 200 with `"status":"ok"`
- [ ] `PaddleOCR/e2e/fixtures/argent-saga-chronicles-page1-polish.png` exists

### Reset state

- [ ] None required

### Run

- [ ] Send `ocr-polish.yml` via `bru run` and wait for HTTP 200

### Expected

- [ ] HTTP 200
- [ ] Response body matches `OcrJsonResponse` schema
- [ ] `language` is a non-empty string (server returns `DEFAULT_LANGUAGE`, not request `lang`)
- [ ] `filename="argent-saga-chronicles-page1-polish.png"`
- [ ] `pages` is non-empty
- [ ] Concatenated `pages[*].lines[*].text` (case-insensitive) contains `Saga Świetlna`, `Aenaria`, or `Eklipsą`
- [ ] The same concatenated text contains at least one character from `{ś, ż, ą, ę, ć, ó, ł, ń, ź}` (or their uppercase forms)
- [ ] Every `OcrTextLine.confidence` is a finite number in `[0.0, 1.0]`
- [ ] Every `OcrTextLine.bounding_box` is a list of `[x, y]` pairs
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
