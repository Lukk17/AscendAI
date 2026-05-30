# Invalid input rejection: run tasks template

Spec: [../1-invalid-input-test.md](../1-invalid-input-test.md)

Copy this file to `../runs/<UTC-timestamp>_1-invalid-input-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [ ] Bruno CLI present (`bru --version` returns a version)
- [ ] WeatherMCP `/actuator/health` returns HTTP 200 with `{"status":"UP"}`

### Reset state

- [ ] None required

### Run

- [ ] Step 1: `curl.exe -fsS -i -X POST http://localhost:9998/mcp ... initialize ...` returns HTTP 200 with an `Mcp-Session-Id` header; capture the UUID
- [ ] Send `invalid-blank-city.yml` via `bru run` with `--env-var "mcp_session_id=<captured UUID>"` and wait for HTTP 200
- [ ] Send `invalid-crlf-city.yml` via `bru run` with `--env-var "mcp_session_id=<captured UUID>"` and wait for HTTP 200
- [ ] Send `invalid-country-code.yml` via `bru run` with `--env-var "mcp_session_id=<captured UUID>"` and wait for HTTP 200

### Expected

- [ ] All three calls return HTTP 200
- [ ] Each response has `status="invalid_input"`
- [ ] Each `message` is non-empty and does NOT contain the offending value
- [ ] Each `requestedQuery` echoes the verbatim input
- [ ] Each `location`, `temperature`, `weatherCode`, `wind`, `observedAt` is `null`
- [ ] Each `source` equals `"open-meteo"`
- [ ] Each `fetchedAt` is a valid ISO-8601 instant
- [ ] Per-call duration < 500 ms (proxy for "validator short-circuited; no upstream call")

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
