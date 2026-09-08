# MCP ocr_process happy path: run tasks template

Spec: [../6-mcp-ocr-test.md](../6-mcp-ocr-test.md)

Copy this file to `../runs/<UTC-timestamp>_6-mcp-ocr-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [ ] Bruno CLI present (`bru --version` returns a version)
- [ ] ascend-ocr `/health` returns HTTP 200 with `"status":"ok"`
- [ ] `apps/ascend-ocr/e2e/fixtures/argent-saga-chronicles-page1.png` exists on the host
- [ ] Object store `curl -fsS http://localhost:9070/_floci/health` returns HTTP 200 with `"s3":"running"`
- [ ] `docker exec ascend-ocr printenv MCP_ALLOWED_HOSTS` returns a list containing `host.docker.internal`

### Reset state

- [ ] `curl -sS -o /dev/null -w "%{http_code}\n" -X PUT "http://localhost:9070/e2e-fixtures"` prints `200`
- [ ] `curl -fsS -X DELETE "http://localhost:9070/e2e-fixtures/argent-saga-chronicles-page1.png"` returned HTTP 204 (object cleared)
- [ ] `curl -sS -o /dev/null -w "%{http_code}\n" -X PUT -H "Content-Type: image/png" --data-binary "@apps/ascend-ocr/e2e/fixtures/argent-saga-chronicles-page1.png" "http://localhost:9070/e2e-fixtures/argent-saga-chronicles-page1.png"` prints `200`
- [ ] `curl -fsS "http://localhost:9070/e2e-fixtures?list-type=2&prefix=argent-saga"` carries `<Key>argent-saga-chronicles-page1.png</Key>` with `<Size>212563</Size>`

### Run

- [ ] Step 1: `curl -fsS -i -X POST http://localhost:7022/mcp ... initialize ...` returns HTTP 200 with an `Mcp-Session-Id` header; capture the UUID
- [ ] Send `mcp-ocr.yml` via `bru run` with `--env-var "mcp_session_id=<captured UUID>"` and wait for HTTP 200

### Expected

- [ ] HTTP 200
- [ ] `result.content` carries a serialised `OcrJsonResponse`
- [ ] `language="en"`
- [ ] `filename="argent-saga-chronicles-page1.png"`
- [ ] `pages` is non-empty
- [ ] Concatenated `pages[*].lines[*].text` (case-insensitive) contains `Argent Saga`, `Aenaria`, or `Halen Veyr`
- [ ] `processing_time_seconds` is a finite non-negative number

### Post-run cleanup

Run regardless of the Run-step verdict; the delete is idempotent.

- [ ] `curl -fsS -X DELETE "http://localhost:9070/e2e-fixtures/argent-saga-chronicles-page1.png"` returned HTTP 204
- [ ] The `e2e-fixtures` bucket itself was left in place

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
