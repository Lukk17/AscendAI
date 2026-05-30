# Current weather city-not-found envelope: run tasks template

Spec: [../3-current-city-not-found-test.md](../3-current-city-not-found-test.md)

Copy this file to `../runs/<UTC-timestamp>_3-current-city-not-found-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [ ] Bruno CLI present (`bru --version` returns a version)
- [ ] WeatherMCP `/actuator/health` returns HTTP 200 with `{"status":"UP"}`
- [ ] Open-Meteo geocoding API reachable

### Reset state

- [ ] None required

### Run

- [ ] Send `current-not-found.yml` via `bru run` and wait for HTTP 200

### Expected

- [ ] HTTP 200
- [ ] `status="city_not_found"`
- [ ] `message` equals exactly `"Location not found"` (NOT `"City not found: Zzyxxqq"` — that was pre-audit)
- [ ] `requestedQuery="Zzyxxqq"`
- [ ] `location`, `temperature`, `weatherCode`, `wind`, `observedAt` are all `null`
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
