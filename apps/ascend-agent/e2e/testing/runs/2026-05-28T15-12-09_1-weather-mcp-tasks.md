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

All four Expected assertions passed. The Bruno run returned HTTP 200. The response `content` field read: "Temperature: 19.9°C" (numeric temperature present), "Partly cloudy (WMO code 1)" (weather condition word present), and "A pleasant late-spring afternoon in Warsaw with a bit of a breeze!" — containing no refusal phrases. The WeatherMCP `getCurrentWeather` tool was demonstrably invoked end-to-end, routing through the AscendAgent to Warsaw live weather data.

Input tokens: 3200

Output tokens: 420

Start (UTC): 2026-05-28T15:12:09Z

End (UTC): 2026-05-28T15:13:47Z

Duration: 00:01:38

---

## Additional tasks I did

<!-- Optional. List anything outside the spec, e.g. diagnostic curls, manual log inspection, retries with different inputs. Leave empty if nothing extra. -->
