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

All four Expected assertions held. The Bruno request returned HTTP 200. The persisted `chat_history` row for `frostyWeatherMcpTest` shows the assistant response "The current weather in Warsaw, Poland: **Temperature:** 25.4°C, **Conditions:** Partly cloudy, **Wind:** 14.0 km/h from the northwest (315°)" — a numeric temperature, a weather condition word, and no refusal phrasing. Bruno's own embedded test script also reported both its assertions passing ("Status code is 200", "Weather content carries a real temperature and condition, not a refusal"). The MCP tool was clearly invoked given the specific, real-time-shaped data (exact wind bearing, timestamped observation) rather than a generic refusal.

Input tokens: not available (Bruno CLI output does not surface token counts for this provider/model combination)

Output tokens: not available (same reason)

Start (UTC): 2026-09-09T17:41:21Z

End (UTC): 2026-09-09T17:43:03Z

Duration: 00:01:42

---

## Additional tasks I did

- Accidentally re-ran `bru run "ascend-agent/testing/weather-mcp-prompt.yml" --env ascend-local` a second time while probing for a Bruno output-file flag (`--output` with an unset variable). This was not prescribed by the spec and produced a second identical prompt/response pair (visible as 4 rows instead of 2 in the pre-cleanup `chat_history` query). No harm to the verdict: the Post-run cleanup step removes all state regardless of row count, and both invocations independently passed the same assertions.
- Queried the persisted `chat_history` table directly (`SELECT role, left(content, 300) ...`) to capture the exact observed response content for this report, beyond what the spec's own Expected section requires as a pass/fail check.
