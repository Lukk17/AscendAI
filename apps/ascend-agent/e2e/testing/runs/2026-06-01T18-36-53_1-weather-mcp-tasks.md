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

All four Expected assertions passed. The Bruno request to `POST /api/v1/ai/prompt` (user `frostyWeatherMcpTest`) returned HTTP 200 with a 2770 ms response time. The `content` field read: "Here's the current weather in **Warsaw**: Temperature: 17.0°C, Wind: 5.0 km/h from SE, Conditions: Partly cloudy (WMO code 1), Observed at 18:30 local time." The numeric temperature value (17.0) satisfies the temperature assertion, "Partly cloudy" satisfies the weather-condition assertion, and there are no refusal phrases in the response, confirming the `getCurrentWeather` MCP tool was invoked successfully. Model used: MiniMax-M2.7.

Input tokens:

Output tokens:

Start (UTC): 2026-06-01T18:36:53Z

End (UTC): 2026-06-01T18:38:08Z

Duration: 00:01:15

---

## Additional tasks I did

<!-- Optional. List anything outside the spec, e.g. diagnostic curls, manual log inspection, retries with different inputs. Leave empty if nothing extra. -->
