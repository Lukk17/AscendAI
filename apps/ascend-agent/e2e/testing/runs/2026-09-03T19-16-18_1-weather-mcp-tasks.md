# Weather MCP: run tasks template

Spec: [../1-weather-mcp-test.md](../1-weather-mcp-test.md)

Copy this file to `runs/<UTC-timestamp>_1-weather-mcp-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [x] Bruno CLI present (`bru --version` returns a version) - 3.4.0
- [x] AscendAgent `/actuator/health` returns HTTP 200 with `{"status":"UP"}`
- [x] WeatherMCP `/actuator/health` returns HTTP 200 with `{"status":"UP"}`

### Reset state

- [x] Deleted Postgres `chat_history` rows where `user_id = 'frostyWeatherMcpTest'` (found 2 leftover rows from a prior run, confirms the pre-run reset is load-bearing)
- [x] Deleted Redis key `chat:frostyWeatherMcpTest`
- [x] Deleted Redis key `user:frostyWeatherMcpTest:instructions`

### Run

- [x] Send `weather-mcp-prompt.yml` via `bru run` and wait for response

### Expected

- [x] HTTP 200
- [x] Response `content` contains a numeric temperature value for the requested city (19.0 degrees C)
- [x] Response `content` contains a weather condition word (cloudy / clear / sunny / rain / etc.) (Overcast)
- [x] Response `content` does NOT contain refusal phrases like "I cannot access live data" or "I don't have real-time data"

### Post-run cleanup

Run regardless of Run-step verdict. Every command is idempotent.

- [x] Deleted Postgres `chat_history` rows where `user_id = 'frostyWeatherMcpTest'`
- [x] Deleted Redis key `chat:frostyWeatherMcpTest`
- [x] Deleted Redis key `user:frostyWeatherMcpTest:instructions`
- [x] `POST http://localhost:7020/api/v1/memory/wipe?user_id=frostyWeatherMcpTest` returned `{"status":"success","message":"All memories wiped for user frostyWeatherMcpTest"}`

### Verdict

- [x] Verdict: PASS

## Result summary

Both Bruno test assertions passed (status code 200, weather content check). The response body's `content` field reported the current weather for Warsaw as 19.0 C, Overcast, with wind data and a last-updated timestamp, matching the WeatherMCP tool's expected output shape. No refusal phrase was present, confirming the MCP tool round trip fired end to end. All four pieces of post-run state (Postgres row, Redis chat key, Redis instructions key, AscendMemory wipe) were cleared successfully.

Provider: minimax. Model: MiniMax-M2.7 (per the request's `provider` and `model` form fields, echoed back in `metadata.model`).

Token usage (single call, from `metadata.usage` in the response body):
Input (prompt) tokens: 3692
Output (completion) tokens: 260
Total tokens: 3952
Cached tokens: not reported by this provider for this endpoint, no `nativeUsage` block was present in the response.

Input tokens: 3692

Output tokens: 260

Start (UTC): 2026-09-03T19:17:43Z

End (UTC): 2026-09-03T19:18:37Z

Duration: 00:00:54

---

## Additional tasks I did

Wrote the Bruno run output to a scratch JSON file (`bru run ... -o <scratch>/test1-weather.json`) so the full response body, including `metadata.usage`, could be inspected for token accounting. This is outside the spec's own assertions (which only check `content`) but was needed to satisfy the sweep's token-accounting requirement. The scratch file lives outside the repository (session scratchpad) and was not committed anywhere.
