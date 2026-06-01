# REST OCR unsupported MIME rejection: run tasks template

Spec: [../12-ocr-unsupported-mime-test.md](../12-ocr-unsupported-mime-test.md)

Copy this file to `../runs/<UTC-timestamp>_12-ocr-unsupported-mime-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [ ] Bruno CLI present (`bru --version` returns a version)
- [ ] PaddleOCR `/health` returns HTTP 200 with `"status":"ok"`
- [ ] `PaddleOCR/e2e/fixtures/not-an-image.txt` exists on the host

### Reset state

- [ ] None required

### Run

- [ ] `bru run "paddle-ocr/testing/ocr-unsupported-mime.yml" --env ascend-local` returns HTTP 400

### Expected

- [ ] HTTP 400
- [ ] Body `code` equals `UNSUPPORTED_FILE_TYPE`
- [ ] Body `detail` equals `Unsupported file type` (generic, no upstream leak)

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
