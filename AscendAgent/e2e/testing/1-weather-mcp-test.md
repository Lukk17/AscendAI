# Weather MCP — e2e test

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

The Bruno output shows HTTP 200 and a response body whose `content` field contains a temperature value and a weather condition for the requested city.

The AscendAgent log (tail it during the run) shows the `getCurrentWeather` MCP tool being invoked for the request id printed in the controller log line.

The response must NOT say "I cannot access live data" or "I don't have real-time data".

## Fixtures

None.
