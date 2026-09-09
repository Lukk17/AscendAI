# Weather MCP: run tasks template

Spec: [1-weather-mcp-test.md](1-weather-mcp-test.md)

Copy this file to `runs/<UTC-timestamp>_1-weather-mcp-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [x] Bruno CLI present (`bru --version` returns a version) — 3.4.0
- [x] AscendAgent `/actuator/health` returns HTTP 200 with `{"status":"UP"}`
- [x] WeatherMCP `/actuator/health` returns HTTP 200 with `{"status":"UP"}`

### Run

- [x] Send `weather-mcp-prompt.yml` via `bru run` and wait for response

### Expected

- [x] HTTP 200
- [x] Response `content` contains a numeric temperature value for the requested city — 18.1°C
- [x] Response `content` contains a weather condition word (cloudy / clear / sunny / rain / etc.) — "Partly cloudy"
- [x] Response `content` does NOT contain refusal phrases like "I cannot access live data" or "I don't have real-time data"

### Verdict

- [x] Verdict: PASS

## Result summary

HTTP 200. Content: "Here's the current weather in Warsaw: Temperature: 18.1°C, Wind: 2.2 km/h from WSW, Conditions: Partly cloudy (WMO code 3), Is Day: No (nighttime). A cool and calm late-spring night in Warsaw!" MCP tool invoked successfully.

Input tokens: 0 (MiniMax-M2.7 — metadata not returned)

Output tokens: 0 (MiniMax-M2.7 — metadata not returned)

Start (UTC): 2026-05-23T23:10:43Z

End (UTC): 2026-05-23T23:11:25Z

Duration: 00:00:42

---

## Additional tasks I did

<!-- Optional. List anything outside the spec, e.g. diagnostic curls, manual log inspection, retries with different inputs. Leave empty if nothing extra. -->
