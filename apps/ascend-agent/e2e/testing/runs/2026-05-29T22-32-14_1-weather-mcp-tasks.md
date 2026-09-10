# Weather MCP: run tasks template

Spec: [1-weather-mcp-test.md](../1-weather-mcp-test.md)

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

All four Expected assertions passed. Bruno reported HTTP 200 in 14,898 ms. The response `content` field read: "Temperature: 17.7°C … Conditions: Partly cloudy (WMO code 2)". The numeric temperature (17.7) satisfies the temperature assertion; "Partly cloudy" satisfies the weather-condition assertion; the body contains no refusal phrases, confirming the WeatherMCP `getCurrentWeather` tool was invoked end-to-end. The extra curl call to capture the body was used solely for assertion verification and is logged under Additional tasks.

Input tokens:

Output tokens:

Start (UTC): 2026-05-29T22:32:57Z

End (UTC): 2026-05-29T22:34:22Z

Duration: 00:01:25

---

## Additional tasks I did

- Issued a second curl POST to `http://localhost:9917/api/v1/ai/prompt` (same parameters as the Bruno request) to capture the full response body for assertion verification, because `bru run` does not print the response body to stdout by default.
