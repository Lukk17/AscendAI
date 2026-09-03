# Weather MCP: e2e test

## What this verifies

- The AscendAgent discovers the WeatherMCP server at startup.
- A weather prompt is routed to the `getCurrentWeather` MCP tool.
- The response contains concrete weather data for the requested city, not a generic refusal.

## Prerequisites

Check Bruno CLI is installed.

```bash
bru --version
```

Expect a version string. If the command is not found, install it with `npm install -g @usebruno/cli`.

Check the AscendAgent health endpoint.

```bash
curl -fsS http://localhost:9917/actuator/health
```

Expect HTTP 200 with `{"status":"UP"}`.

Check the WeatherMCP server is reachable.

```bash
curl -fsS http://localhost:9998/actuator/health
```

Expect HTTP 200 with `{"status":"UP"}`.

## Reset state

Clear this spec's per-user state before the run. Post-run cleanup removes the same three pieces of state, but a run that crashed before reaching that section leaves them behind, and stale `chat_history` rows change the prompt the model sees on the next run. Every command is idempotent.

Drop this spec's chat-history rows.

```bash
docker exec postgres psql -U postgres -d ascend_ai -c "DELETE FROM chat_history WHERE user_id = 'frostyWeatherMcpTest';"
```

Drop the Redis chat cache key.

```bash
docker exec redis redis-cli DEL chat:frostyWeatherMcpTest
```

Drop the Redis instructions cache key.

```bash
docker exec redis redis-cli DEL user:frostyWeatherMcpTest:instructions
```

## Run

Send the Bruno request and wait for the response before moving to the Expected section.

```bash
cd docs/api/request/AscendAI && bru run "ascend-agent/testing/weather-mcp-prompt.yml" --env ascend-local
```

## Post-run cleanup

Every prompt this spec sends writes three pieces of per-user state: a `chat_history` row pair in Postgres, the same turns cached under the Redis `chat:` key, and a Redis instructions-cache entry that `UserInstructionService` writes on every prompt (an `EMPTY` marker with a 24 hour TTL when the user has no stored instructions). The agent also runs its semantic-memory extractor after every prompt, whether or not the prompt itself concerns memory, so a fourth cleanup step wipes any fact AscendMemory happened to extract from this prompt. Remove all four so the run leaves the system exactly as it found it. Run these regardless of whether the Run step passed or failed. Every command is idempotent.

Drop this spec's chat-history rows.

```bash
docker exec postgres psql -U postgres -d ascend_ai -c "DELETE FROM chat_history WHERE user_id = 'frostyWeatherMcpTest';"
```

Drop the Redis chat cache key.

```bash
docker exec redis redis-cli DEL chat:frostyWeatherMcpTest
```

Drop the Redis instructions cache key.

```bash
docker exec redis redis-cli DEL user:frostyWeatherMcpTest:instructions
```

Wipe any semantic-memory points AscendMemory's background extractor stored for this user. With no `provider` query parameter the endpoint clears the user across every provider collection, which stays correct if the embedding provider changes.

```bash
curl -sS -X POST "http://localhost:7020/api/v1/memory/wipe?user_id=frostyWeatherMcpTest"
```

Expect `{"status":"success","message":"All memories wiped for user frostyWeatherMcpTest"}`.

## Expected

The Bruno output shows HTTP 200.

The response body's `content` field contains a numeric temperature value for the requested city.

The response body's `content` field contains a weather condition word (cloudy / clear / sunny / rain / etc.).

The response body's `content` field does NOT contain refusal phrases like "I cannot access live data" or "I don't have real-time data". Those indicate the MCP tool was not invoked.

## Fixtures

None.

## Concurrency

- **Mutates:** Postgres `chat_history` (user_id=`frostyWeatherMcpTest`); Redis keys `chat:frostyWeatherMcpTest` and `user:frostyWeatherMcpTest:instructions`; Qdrant collections `ascend_memory_*` (user-scoped: `frostyWeatherMcpTest`, written by the background memory extractor on any prompt)
- **Conflicts with:** none
- **Serial:** false
- **Hermetic contract:** Self-cleaning. `Reset state` (pre) and `Post-run cleanup` (post) both remove every row, key and vector point this spec's user id could carry.
