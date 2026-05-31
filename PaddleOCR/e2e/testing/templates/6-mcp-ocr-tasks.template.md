# MCP ocr_process happy path: run tasks template

Spec: [../6-mcp-ocr-test.md](../6-mcp-ocr-test.md)

Copy this file to `../runs/<UTC-timestamp>_6-mcp-ocr-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [ ] Bruno CLI present (`bru --version` returns a version)
- [ ] PaddleOCR `/health` returns HTTP 200 with `"status":"ok"`
- [ ] `PaddleOCR/e2e/fixtures/argent-saga-chronicles-page1.png` exists on the host
- [ ] `docker exec paddle-ocr test -f /e2e-fixtures/argent-saga-chronicles-page1.png` returns exit code `0` (fixtures dir mounted into container)

### Reset state

- [ ] None required

### Run

- [ ] Step 1: `curl.exe -fsS -i -X POST http://localhost:7022/mcp/ ... initialize ...` returns HTTP 200 with an `Mcp-Session-Id` header; capture the UUID
- [ ] Send `mcp-ocr.yml` via `bru run` with `--env-var "mcp_session_id=<captured UUID>"` and wait for HTTP 200

### Expected

- [ ] HTTP 200
- [ ] `result.content` carries a serialised `OcrJsonResponse`
- [ ] `language="en"`
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
