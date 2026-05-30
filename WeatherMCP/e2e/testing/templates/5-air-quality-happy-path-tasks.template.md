# Air quality happy path: run tasks template

Spec: [../5-air-quality-happy-path-test.md](../5-air-quality-happy-path-test.md)

Copy this file to `../runs/<UTC-timestamp>_5-air-quality-happy-path-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [ ] Bruno CLI present (`bru --version` returns a version)
- [ ] WeatherMCP `/actuator/health` returns HTTP 200 with `{"status":"UP"}`
- [ ] Open-Meteo air-quality API reachable

### Reset state

- [ ] None required

### Run

- [ ] Step 1: `curl.exe -fsS -i -X POST http://localhost:9998/mcp ... initialize ...` returns HTTP 200 with an `Mcp-Session-Id` header; capture the UUID
- [ ] Send `air-quality-warsaw.yml` via `bru run` with `--env-var "mcp_session_id=<captured UUID>"` and wait for HTTP 200

### Expected

- [ ] HTTP 200
- [ ] `status="ok"`, `message` null, `requestedQuery` null
- [ ] `location.name` contains "Warsaw" (case-insensitive); `location.countryCode="PL"`
- [ ] At least one of `pm10` or `pm25` is a finite non-negative number
- [ ] At least one of `usAqi` or `europeanAqi` is an integer ≥ 0
- [ ] `source="open-meteo"`
- [ ] `fetchedAt` parses as a valid `Instant`

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
