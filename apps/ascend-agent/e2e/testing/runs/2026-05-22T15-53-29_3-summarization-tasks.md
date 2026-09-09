# Document summarization: run tasks template

Spec: [3-summarization-test.md](../3-summarization-test.md)

Copy this file to `runs/<UTC-timestamp>_3-summarization-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [x] Bruno CLI present (`bru --version` returns a version) — 3.3.0
- [x] AscendAgent `/actuator/health` returns HTTP 200 with `{"status":"UP"}`
- [x] Docling Serve `/health` returns HTTP 200 — `{"status":"ok"}`
- [x] Fixture `AscendAgent/e2e/fixtures/argent-saga-chronicle.pdf` exists

### Run

- [x] Send `doc-summarization-prompt.yml` via `bru run` and wait for response (may take 30–90s)

### Expected

- [ ] HTTP 200 — FAILED: received HTTP 422
- [ ] Response `content` is a coherent summary that quotes specific facts from the source document
- [ ] Response `content` contains at least three of the expected proper nouns listed in the spec's Expected section
- [ ] Response `content` is NOT a refusal like "the document context block is empty" or "I don't see a document attached"

### Verdict

- [x] Verdict: FAIL

## Result summary

The AscendAgent returned HTTP 422 `{"message":"Failed to route PDF page: argent-saga-chronicle.pdf","error":"Unprocessable Entity","status":422}`. Root cause: DocumentRouter splits the PDF page-by-page; at least one page has < 50 characters of extractable text (image/scanned page) and is routed to PaddleOCR at `http://localhost:7022/v1/ocr`. PaddleOCR's health endpoint responds normally (`{"status":"ok"}`) but POST requests to `/v1/ocr` hang indefinitely (HTTP 100 Continue is returned but no response body arrives within 60 seconds). The hanging PaddleOCR call propagates as a RestClientException that the DocumentRouter catches and re-throws as DocumentRoutingException, which the global exception handler maps to HTTP 422. Docling Serve itself was confirmed healthy and processed the full PDF successfully in a direct test (200 in 14 seconds).

Input tokens: N/A (request failed before reaching the LLM)

Output tokens: N/A

Start (UTC): 2026-05-22T16:01:04Z

End (UTC): 2026-05-22T16:12:16Z

Duration: 00:11:12

---

## Additional tasks I did

1. Confirmed Docling Serve is healthy (`/health` returns 200) and can process the full PDF directly (`/v1/convert/file` returned 200 in ~14s for the fixture PDF).
2. Confirmed PaddleOCR health endpoint returns 200 but POST to `/v1/ocr` hangs — tested with both the PDF fixture and `image.png` via curl with `--max-time 60`; both returned HTTP 100 Continue with no body, indicating the inference worker is unresponsive.
3. Confirmed the DocumentRouter code path: pages with < 50 text characters (image pages) are dispatched to PaddleOcrClient, which wraps the call in a CompletableFuture; when PaddleOCR hangs, the ExecutionException is caught and rethrown as DocumentRoutingException → HTTP 422.
4. Confirmed the ingestion RestClient timeouts are 300 000 ms (5 min) — long enough that the request ran for ~83 s before bru reported 422, consistent with the PaddleOCR read-timeout or an internal agent cancellation rather than a client-side timeout.
