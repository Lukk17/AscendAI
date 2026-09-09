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

The Bruno CLI (v3.4.0) ran `weather-mcp-prompt.yml` against the live stack and received HTTP 200 in ~8 seconds. The agent routed the prompt "What is current weather in Warsaw?" through the WeatherMCP `getCurrentWeather` MCP tool and returned a structured response: temperature 21.3°C, wind 10.4 km/h from WNW, conditions "Clear sky". All four Expected assertions passed: HTTP 200 confirmed, a numeric temperature value (21.3) present, a weather condition word ("Clear") present, and no refusal phrases in the content. MCP tool discovery and invocation are working end-to-end.

Input tokens:

Output tokens:

Start (UTC): 2026-06-17T16:37:08Z

End (UTC): 2026-06-17T16:38:16Z

Duration: 00:01:08

---

## Additional tasks I did

- Ran a direct `curl` POST to `/api/v1/ai/prompt` after the Bruno run to capture the full response body and verify all Expected content assertions against the actual JSON. Bruno's summary shows only the HTTP status; the body inspection required the extra curl call.
