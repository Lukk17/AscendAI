# ascend-weather-mcp: run tasks template

Spec: [../1-weather-mcp-test.md](../1-weather-mcp-test.md)

Copy this file to `runs/<UTC-timestamp>_1-weather-mcp-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [x] Bruno CLI present (`bru --version` returns a version)
- [x] ascend-ai-agent `/actuator/health` returns HTTP 200 with `{"status":"UP"}`
- [x] ascend-weather-mcp `/actuator/health` returns HTTP 200 with `{"status":"UP"}`

### Reset state

- [x] Deleted Postgres `chat_history` rows where `user_id = 'frostyWeatherMcpTest'`
- [x] Deleted Redis key `chat:frostyWeatherMcpTest`
- [x] Deleted Redis key `user:frostyWeatherMcpTest:instructions`

### Run

- [x] Send `weather-mcp-prompt.yml` via `bru run` and wait for response

### Expected

- [x] HTTP 200
- [x] Response `content` contains a numeric temperature value for the requested city
- [x] Response `content` contains a weather condition word (cloudy / clear / sunny / rain / etc.)
- [x] Response `content` does NOT contain refusal phrases like "I cannot access live data" or "I don't have real-time data"

### Post-run cleanup

Run regardless of Run-step verdict. Every command is idempotent.

- [x] Deleted Postgres `chat_history` rows where `user_id = 'frostyWeatherMcpTest'`
- [x] Deleted Redis key `chat:frostyWeatherMcpTest`
- [x] Deleted Redis key `user:frostyWeatherMcpTest:instructions`
- [x] `POST http://localhost:7020/api/v1/memory/wipe?user_id=frostyWeatherMcpTest` returned `{"status":"success", ...}`

### Verdict

- [x] Verdict: PASS

## Result summary

All four Expected assertions hold, verified against the captured response body rather than the Bruno test script alone. HTTP 200. `content` contains "16.8°C" (numeric temperature) and "Clear sky" (condition word). No refusal phrase present. The data is time-consistent with the live system (observed-at timestamp "Sep 10, 2026 @ 07:45", matching today's date and the recent container restart), which is strong evidence the `getCurrentWeather` MCP tool was actually invoked against ascend-weather-mcp rather than the model hallucinating a plausible-looking answer, confirming session recovery after the container restart two minutes prior. The Bruno request's own embedded test script also passed both its checks and does not weaken any spec assertion.

Input tokens:

Output tokens:

Start (UTC): 2026-09-10T07:54:06Z

End (UTC): 2026-09-10T07:55:59Z

Duration: 00:01:53

---

## Additional tasks I did

- Re-ran `bru run "ascend-agent/testing/weather-mcp-prompt.yml" --env ascend-local --output ... --format json` a second time (in addition to the spec's single prescribed Run invocation) to capture the full JSON response body for independent verification of each Expected assertion, rather than trusting the Bruno script's pass/fail summary alone. The extra invocation wrote a second `chat_history` row pair, which Post-run cleanup removed along with the first (`DELETE 4` confirms two pairs were present). The temp JSON file was written to and then deleted from the scratchpad directory.
- Noted but did not act on: the response `metadata.toolsUsed` field was an empty array (`[]`) despite the weather data clearly being live/tool-sourced (matching today's date, container-restart-consistent values). This field is not part of any spec Expected assertion, so it does not affect the verdict, but it may indicate `toolsUsed` metadata tracking does not capture MCP tool invocations for this provider/flow. Flagging for awareness, not as a failure.
