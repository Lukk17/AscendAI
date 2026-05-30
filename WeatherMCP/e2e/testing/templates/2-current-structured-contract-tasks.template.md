# Current weather structured contract: run tasks template

Spec: [../2-current-structured-contract-test.md](../2-current-structured-contract-test.md)

Copy this file to `../runs/<UTC-timestamp>_2-current-structured-contract-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [ ] Bruno CLI present (`bru --version` returns a version)
- [ ] WeatherMCP `/actuator/health` returns HTTP 200 with `{"status":"UP"}`
- [ ] Open-Meteo geocoding API reachable via `curl -fsS https://geocoding-api.open-meteo.com/v1/search?name=Berlin&count=1`

### Reset state

- [ ] None required

### Run

- [ ] Step 1: `curl.exe -fsS -i -X POST http://localhost:9998/mcp ... initialize ...` returns HTTP 200 with an `Mcp-Session-Id` header; capture the UUID
- [ ] Send `list-tools.yml` via `bru run` with `--env-var "mcp_session_id=<captured UUID>"` and wait for HTTP 200
- [ ] Send `current-warsaw.yml` via `bru run` with `--env-var "mcp_session_id=<captured UUID>"` and wait for HTTP 200

### Expected

- [ ] `list-tools.yml`: `result.tools` contains an entry with `name="weather.current"`
- [ ] `list-tools.yml`: that entry's `inputSchema.properties` advertises `city` (required), `countryCode`, `unit`, `language`
- [ ] `current-warsaw.yml`: `status="ok"`, `message` is null, `requestedQuery` is null
- [ ] `location.name` contains "Warsaw" (case-insensitive)
- [ ] `location.countryCode="PL"`
- [ ] `location.latitude` in 51.5–53.0; `location.longitude` in 20.5–22.0
- [ ] `temperature.value` is a finite number; `temperature.unit="celsius"`
- [ ] `weatherCode` is an integer in 0–99
- [ ] `wind.speed` is a non-null number ≥ 0; `wind.unit="km/h"`
- [ ] `observedAt` is a non-empty string
- [ ] `source="open-meteo"`; `fetchedAt` parses as a valid `Instant`

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
