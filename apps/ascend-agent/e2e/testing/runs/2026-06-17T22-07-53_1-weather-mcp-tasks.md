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

Bruno returned HTTP 200 in 10,855 ms. The response body `content` field contained "17.7°C" (numeric temperature), "Overcast" (weather condition word), and did not contain any refusal phrases. The MCP tool was demonstrably invoked: live weather data for Warsaw (17.7°C, overcast, WMO code 3, wind 9.4 km/h from WNW, observed at 22:00 local time) was returned. All four Expected assertions passed.

Input tokens:

Output tokens:

Start (UTC): 2026-06-17T22:07:53Z

End (UTC): 2026-06-17T22:09:15Z

Duration: 00:01:22

---

## Additional tasks I did

- Issued a second curl invocation (same parameters as the Bruno request) to capture the full JSON response body for Expected assertion evaluation, since `bru run` CLI output does not print the response body.
