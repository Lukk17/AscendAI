# Weather MCP: run tasks template

Spec: [1-weather-mcp-test.md](1-weather-mcp-test.md)

Copy this file to `runs/<UTC-timestamp>_1-weather-mcp-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [x] Bruno CLI present (`bru --version` returns a version)
- [x] AscendAgent `/actuator/health` returns HTTP 200 with `{"status":"UP"}`
- [x] WeatherMCP `/actuator/health` returns HTTP 200 with `{"status":"UP"}`

### Run

- [x] Send `weather-mcp-prompt.yml` via `bru run` and wait for response

### Expected

- [x] HTTP 200
- [x] Response `content` contains a numeric temperature value for the requested city
- [x] Response `content` contains a weather condition word (cloudy / clear / sunny / rain / etc.)
- [x] Response `content` does NOT contain refusal phrases like "I cannot access live data" or "I don't have real-time data"

### Verdict

- [x] Verdict: PASS

## Result summary

HTTP 200. Response content: "Temperature: 16.5°C", "Partly cloudy (WMO code 1)". MCP tool was invoked — live weather data returned for Warsaw. No refusal phrases present.

Input tokens: 0 (MCP tool, not LLM tokens tracked)

Output tokens: 0

Start (UTC): 2026-05-24T01:50:28Z

End (UTC): 2026-05-24T01:51:44Z

Duration: 00:01:16

---

## Additional tasks I did

<!-- Optional. List anything outside the spec, e.g. diagnostic curls, manual log inspection, retries with different inputs. Leave empty if nothing extra. -->
