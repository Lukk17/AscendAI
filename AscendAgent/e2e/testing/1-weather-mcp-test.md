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

None. This test does not write persisted state.

## Run

Send the Bruno request and wait for the response before moving to the Expected section.

```bash
cd docs/api/request/AscendAI && bru run "ascend-agent/testing/weather-mcp-prompt.yml" --env ascend-local
```

## Expected

The Bruno output shows HTTP 200.

The response body's `content` field contains a numeric temperature value for the requested city.

The response body's `content` field contains a weather condition word (cloudy / clear / sunny / rain / etc.).

The response body's `content` field does NOT contain refusal phrases like "I cannot access live data" or "I don't have real-time data". Those indicate the MCP tool was not invoked.

## Fixtures

None.

## Concurrency

- **Mutates:** Postgres `chat_history` (user_id=`frostyWeatherMcpTest`); Redis key `chat:frostyWeatherMcpTest`
- **Conflicts with:** none
- **Serial:** false
