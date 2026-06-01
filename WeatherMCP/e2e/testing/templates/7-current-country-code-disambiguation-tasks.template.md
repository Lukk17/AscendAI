# Current weather country-code disambiguation: run tasks template

Spec: [../7-current-country-code-disambiguation-test.md](../7-current-country-code-disambiguation-test.md)

Copy this file to `../runs/<UTC-timestamp>_7-current-country-code-disambiguation-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [ ] Bruno CLI present (`bru --version` returns a version)
- [ ] WeatherMCP `/actuator/health` returns HTTP 200 with `{"status":"UP"}`
- [ ] Open-Meteo geocoding query for `Warsaw` with `count=5` returns at least one entry with `country_code="US"`

### Reset state

- [ ] `docker restart weather-mcp` to clear the Caffeine geocoding cache
- [ ] `/actuator/health` returns HTTP 200 with `{"status":"UP"}` after the restart

### Run

- [ ] Step 1: `curl.exe -fsS -i -X POST http://localhost:9998/mcp ... initialize ...` returns HTTP 200 with an `Mcp-Session-Id` header; capture the UUID
- [ ] Send `current-warsaw.yml` via `bru run` with `--env-var "mcp_session_id=<captured UUID>"` and wait for HTTP 200
- [ ] Send `current-warsaw-us.yml` via `bru run` with `--env-var "mcp_session_id=<captured UUID>"` and wait for HTTP 200

### Expected

First call (no `countryCode`):

- [ ] `status="ok"`
- [ ] `location.countryCode="PL"`
- [ ] `location.latitude` in 51.5–53.0
- [ ] `location.longitude` in 20.5–22.0

Second call (`countryCode="US"`):

- [ ] `status="ok"`
- [ ] `location.countryCode="US"`
- [ ] `location.latitude` in 38.0–43.0
- [ ] `location.longitude` in -95.0 to -75.0

Cross-call:

- [ ] The two `location.latitude` values differ by at least 8 degrees
- [ ] The two `location.countryCode` values differ

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
