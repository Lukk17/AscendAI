# Geocode multiple candidates: run tasks template

Spec: [../6-geocode-multiple-candidates-test.md](../6-geocode-multiple-candidates-test.md)

Copy this file to `../runs/<UTC-timestamp>_6-geocode-multiple-candidates-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [ ] Bruno CLI present (`bru --version` returns a version)
- [ ] WeatherMCP `/actuator/health` returns HTTP 200 with `{"status":"UP"}`
- [ ] Open-Meteo geocoding API reachable with ≥ 3 results for `Springfield`

### Reset state

- [ ] None required

### Run

- [ ] Step 1: `curl.exe -fsS -i -X POST http://localhost:9998/mcp ... initialize ...` returns HTTP 200 with an `Mcp-Session-Id` header; capture the UUID
- [ ] Send `geocode-springfield.yml` via `bru run` with `--env-var "mcp_session_id=<captured UUID>"` and wait for HTTP 200

### Expected

- [ ] HTTP 200
- [ ] `status="ok"`, `message` null, `requestedQuery` null
- [ ] `candidates` array has length ≥ 3
- [ ] All `(latitude, longitude)` tuples across the entries are distinct
- [ ] At least one entry has `countryCode="US"`
- [ ] Each entry's `name` contains "Springfield" (case-insensitive)
- [ ] Each entry's `latitude` and `longitude` are finite numbers
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
