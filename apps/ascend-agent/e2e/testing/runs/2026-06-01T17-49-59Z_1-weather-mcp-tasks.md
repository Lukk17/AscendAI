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

Bruno ran `weather-mcp-prompt.yml` against the live stack and received HTTP 200 in ~4.9 s. The response `content` field read: "Here's the current weather in **Warsaw**: Temperature: 17.1°C, Wind: 5.4 km/h from ESE, Conditions: Mainly clear (WMO code 1), Is Day: Yes." All four Expected assertions pass: the status was 200, a numeric temperature value (17.1°C) was present, a weather condition word ("Mainly clear") was present, and no refusal phrases appeared. The MCP tool was demonstrably invoked — the agent returned live weather data from WeatherMCP, not a canned refusal.

Input tokens:

Output tokens:

Start (UTC): 2026-06-01T17:49:59Z

End (UTC): 2026-06-01T17:52:10Z

Duration: 00:02:11

---

## Additional tasks I did

<!-- Optional. List anything outside the spec, e.g. diagnostic curls, manual log inspection, retries with different inputs. Leave empty if nothing extra. -->
