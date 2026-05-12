# Weather MCP — run tasks template

Spec: [1-weather-mcp-test.md](../1-weather-mcp-test.md)

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

WeatherMCP routed successfully. Bruno HTTP 200 in ~16.3s. Response `content` reports Warsaw weather with concrete data: temperature 10.2°C, wind 11.5 km/h at 329° (NW), conditions "Overcast (WMO code 3)", timestamp "2026-05-12 at 17:15 GMT". No refusal phrasing. `getCurrentWeather` MCP tool was invoked.

Input tokens: ~600

Output tokens: ~90

Start (UTC): 2026-05-12T17:25:16Z

End (UTC): 2026-05-12T17:26:26Z

Duration: 00:01:10

---

## Additional tasks I did

None.
