# Document routing: run tasks template

Spec: [../14-document-routing-test.md](../14-document-routing-test.md)

Copy this file to `../runs/<UTC-timestamp>_14-document-routing-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [ ] Bruno CLI present (`bru --version` returns a version)
- [ ] ascend-web-hunter `/health` returns HTTP 200 with `{"status":"ok"}`
- [ ] docling-serve `/health` returns HTTP 200 with `{"status":"ok"}`
- [ ] ascend-ocr `/health` returns HTTP 200 with `{"status":"ok"}`
- [ ] ascend-audio-scribe `/health` returns HTTP 200 with `{"status":"ok"}`
- [ ] Fake site reachable: `curl -fsS http://127.0.0.1:7031/__requests` returns a request list

### Reset state

- [ ] `POST http://127.0.0.1:7031/__reset` returned `{"reset":true}`
- [ ] Listed ascend-ocr jobs and deleted each one (HTTP 204 each), so the job list is empty

### Run

- [ ] Sent `route-pdf.yml` via `bru run` and got HTTP 200
- [ ] Sent `route-image.yml` via `bru run` and got HTTP 200
- [ ] Sent `route-audio.yml` via `bru run` and got HTTP 200
- [ ] Sent `route-pdf-oversized.yml` via `bru run` and got HTTP 200
- [ ] Sent `route-private-link.yml` via `bru run` and got HTTP 200

### Expected

- [ ] Call 1 body: `content` holds `"HELIX-FINCH"`
- [ ] Call 2 body: `content` holds `"Mirellion"`, and the OCR job list holds a job in state `"succeeded"`
- [ ] Call 3 body: `content` holds `"KAKSMA"`
- [ ] Call 4 body: `routing_error` field present; the request log entry for `/files/oversized.pdf` has `bytes_sent` equal to `0`
- [ ] Call 5 body: `content` holds `"HALCYON-PLOVER"` plus `routing_error`; the request log holds `/pdf-link-blocked` and no path containing `e2e-fake-site-blocked`
- [ ] Deleted the OCR jobs the run created (job list empty again)

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
