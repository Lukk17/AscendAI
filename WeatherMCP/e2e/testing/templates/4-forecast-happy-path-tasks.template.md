# Forecast happy path: run tasks template

Spec: [../4-forecast-happy-path-test.md](../4-forecast-happy-path-test.md)

Copy this file to `../runs/<UTC-timestamp>_4-forecast-happy-path-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [ ] Bruno CLI present (`bru --version` returns a version)
- [ ] WeatherMCP `/actuator/health` returns HTTP 200 with `{"status":"UP"}`
- [ ] Open-Meteo forecast API reachable

### Reset state

- [ ] None required

### Run

- [ ] Step 1: `curl.exe -fsS -i -X POST http://localhost:9998/mcp ... initialize ...` returns HTTP 200 with an `Mcp-Session-Id` header; capture the UUID
- [ ] Send `forecast-warsaw-3d.yml` via `bru run` with `--env-var "mcp_session_id=<captured UUID>"` and wait for HTTP 200

### Expected

- [ ] HTTP 200
- [ ] `status="ok"`, `message` null, `requestedQuery` null
- [ ] `location.name` contains "Warsaw"; `location.countryCode="PL"`
- [ ] `forecast` array length equals 3
- [ ] Each entry: `date` matches `yyyy-MM-dd`; `temperatureMax` and `temperatureMin` are finite numbers with `temperatureMin <= temperatureMax`; `weatherCode` is an integer in 0–99
- [ ] `forecast[*].date` values strictly increasing
- [ ] `temperatureUnit="celsius"`
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
