# ascend-weather-mcp: run tasks template

Spec: [../1-weather-mcp-test.md](../1-weather-mcp-test.md)

Copy this file to `runs/<UTC-timestamp>_1-weather-mcp-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [x] Bruno CLI present (`bru --version` returns a version) — observed `3.4.0`
- [x] ascend-ai-agent `/actuator/health` returns HTTP 200 with `{"status":"UP"}` — observed `{"status":"UP","groups":["liveness","readiness"]}` HTTP 200
- [x] ascend-weather-mcp `/actuator/health` returns HTTP 200 with `{"status":"UP"}` — observed `{"status":"UP","groups":["liveness","readiness"]}` HTTP 200

### Reset state

- [x] Deleted Postgres `chat_history` rows where `user_id = 'frostyWeatherMcpTest'` — `DELETE 0` (no leaked rows)
- [x] Deleted Redis key `chat:frostyWeatherMcpTest` — `0` (key not present)
- [x] Deleted Redis key `user:frostyWeatherMcpTest:instructions` — `0` (key not present)

### Run

- [x] Send `weather-mcp-prompt.yml` via `bru run` and wait for response — request sent, response received: HTTP 500 (Bruno output: `ascend-agent\testing\weather-mcp-prompt (500 ) - 11269 ms`, tests 0/2 passed)

### Expected

- [ ] HTTP 200 — OBSERVED: HTTP 500 with body `{"timestamp":"2026-09-07T18:28:56...","message":"An unexpected error occurred. Check server logs for details.","error":"Internal Server Error","status":500}`
- [ ] Response `content` contains a numeric temperature value for the requested city — OBSERVED: no `content` field in the error body (Bruno test reported "expected undefined to be a string")
- [ ] Response `content` contains a weather condition word (cloudy / clear / sunny / rain / etc.) — not evaluable, no `content` field present
- [ ] Response `content` does NOT contain refusal phrases like "I cannot access live data" or "I don't have real-time data" — not evaluable, no `content` field present; the failure is a 500, not a refusal string

### Post-run cleanup

Run regardless of Run-step verdict. Every command is idempotent.

- [x] Deleted Postgres `chat_history` rows where `user_id = 'frostyWeatherMcpTest'` — `DELETE 0` (no rows: every attempt 500'd before reaching the persistence step)
- [x] Deleted Redis key `chat:frostyWeatherMcpTest` — `0` (key not present, consistent with no completed turn)
- [x] Deleted Redis key `user:frostyWeatherMcpTest:instructions` — `1` (key was present — `UserInstructionService` writes its EMPTY marker early, before the MCP tool-discovery failure point, on all 3 attempts made during this run)
- [x] `POST http://localhost:7020/api/v1/memory/wipe?user_id=frostyWeatherMcpTest` returned `{"status":"success", ...}` — observed `{"status":"success","message":"All memories wiped for user frostyWeatherMcpTest"}`

### Verdict

- [x] Verdict: FAIL

## Result summary

The official Run step (`bru run weather-mcp-prompt.yml`) returned HTTP 500, not the expected HTTP 200, so none of the four Expected assertions could be evaluated against real content: the response body carried only a generic `{"error":"Internal Server Error","status":500}` with no `content` field. Root-cause tracing via `docker logs ascend-ai-agent` (diagnostic only, not a pass criterion) shows the failure is unrelated to both the provider situation named in this run's brief and to the weather MCP tool itself. The pinned `embeddingProvider=openai` (dead credential, HTTP 401 from OpenAI) is caught inside `RagRetrievalService` and `SemanticMemoryClient`, logged as a WARN ("Similarity search failed", "Semantic memory search failed"), and the orchestration continues with RAG/semantic-memory context simply omitted — it does not abort the request. The actual 500 is thrown later, during MCP tool-discovery (`SyncMcpToolCallbackProvider.getToolCallbacks` -> `McpSyncClient.listTools`), when one of the agent's registered MCP clients has a stale session the server no longer recognizes (`McpTransportSessionNotFoundException` -> unhandled `RuntimeException: MCP session with server terminated` -> `GlobalExceptionHandler` 500). This happened on 3 consecutive attempts (the official run plus 2 diagnostic replays), each time against a different MCP server in rotation (ascend-web-hunter, then ascend-audio-scribe, then ascend-weather-mcp itself on the 3rd attempt), consistent with every registered MCP client's session having gone stale during the ~4 hour idle uptime of the compose stack, healing one at a time per request attempt but still failing the request that triggered the heal. The weather MCP tool was never reached in any of the 3 attempts; MiniMax's chat completion endpoint was also never reached, so the pinned `provider=minimax` chat path is unverified either way. Verdict: FAIL, and the failure is a genuine product-level resilience gap in MCP tool-discovery error handling, not the environmental credential problem the run brief anticipated.

Input tokens: 0 (the request never reached a chat completion call; the OpenAI embedding call 401'd before token consumption)

Output tokens: 0 (same reason — no model call completed)

Start (UTC): 2026-09-07T18:27:51Z

End (UTC): 2026-09-07T18:32:05Z

Duration: 00:04:14

---

## Additional tasks I did

- Replayed the same multipart request twice more via `curl` (not `bru`) after the official Run step, purely to capture the response body (Bruno's CLI output doesn't print it) and to check whether the HTTP 500 was a one-off idle-session hiccup or reproducible. Both replays also returned HTTP 500. This is diagnostic evidence only; the Verdict is anchored to the one official `bru run` execution, which itself already failed the Expected assertions.
- Ran `docker logs --since <window> ascend-ai-agent` (read-only) after the failure to identify the root cause per the "no log-substring assertions" rule's exception for diagnostics-on-failure. Logs are cited in the Result summary as the diagnostic trail for a FAIL verdict, never as the pass criterion.
- Discovered mid-run that `ascend-ai-agent` is currently running as a Docker container (`docker ps` shows it `Up 4 hours (healthy)`), not via `./gradlew bootRun` on the host as AGENTS.md's dev-workflow section describes. This let me reach its logs via `docker logs` where the spec/README assumed no such access would exist; noting it in case it's a stale AGENTS.md assumption or a temporary local deviation.
- No permission-classifier blocks encountered; every command in this run (health checks, `docker exec postgres/redis`, `bru run`, the diagnostic `curl` replays, `docker logs`, the memory wipe `curl`) executed without a denial.
