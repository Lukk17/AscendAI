# Weather MCP: run tasks template

Spec: [../1-weather-mcp-test.md](../1-weather-mcp-test.md)

Copy this file to `runs/<UTC-timestamp>_1-weather-mcp-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [ ] Bruno CLI present (`bru --version` returns a version)
- [ ] AscendAgent `/actuator/health` returns HTTP 200 with `{"status":"UP"}`
- [ ] WeatherMCP `/actuator/health` returns HTTP 200 with `{"status":"UP"}`

### Reset state

- [ ] Deleted Postgres `chat_history` rows where `user_id = 'frostyWeatherMcpTest'`
- [ ] Deleted Redis key `chat:frostyWeatherMcpTest`
- [ ] Deleted Redis key `user:frostyWeatherMcpTest:instructions`

### Run

- [ ] Send `weather-mcp-prompt.yml` via `bru run` and wait for response

### Expected

- [ ] HTTP 200
- [ ] Response `content` contains a numeric temperature value for the requested city
- [ ] Response `content` contains a weather condition word (cloudy / clear / sunny / rain / etc.)
- [ ] Response `content` does NOT contain refusal phrases like "I cannot access live data" or "I don't have real-time data"

### Post-run cleanup

Run regardless of Run-step verdict. Every command is idempotent.

- [ ] Deleted Postgres `chat_history` rows where `user_id = 'frostyWeatherMcpTest'`
- [ ] Deleted Redis key `chat:frostyWeatherMcpTest`
- [ ] Deleted Redis key `user:frostyWeatherMcpTest:instructions`
- [ ] `POST http://localhost:7020/api/v1/memory/wipe?user_id=frostyWeatherMcpTest` returned `{"status":"success", ...}`

### Verdict

- [ ] Verdict: PASS / FAIL (delete the wrong one)

## Result summary



Input tokens:

Output tokens:

Start (UTC):

End (UTC):

Duration:

---

## Additional tasks I did

<!-- Optional. List anything outside the spec, e.g. diagnostic curls, manual log inspection, retries with different inputs. Leave empty if nothing extra. -->
