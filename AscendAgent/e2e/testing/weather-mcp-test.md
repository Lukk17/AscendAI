# Weather MCP — manual e2e test

## What this verifies

The AscendAgent discovers the WeatherMCP server at startup, routes a weather prompt to its `getCurrentWeather` tool, and returns concrete weather data in the response rather than a generic "I don't have real-time data" refusal. This is a smoke test for MCP client wiring; it does not cover a specific bug fix.

## Prerequisites

- `docker compose up -d` brought the stack up cleanly
- AscendAgent reachable on port 9917
- WeatherMCP reachable on port 9998
- A chat provider that supports tool calls (Anthropic, OpenAI, Gemini, or MiniMax M2.5+)

If WeatherMCP was started after AscendAgent, restart the agent so the MCP client picks it up.

## Bruno collection

Open Bruno → `docs/api/request/AscendAI/ascend-agent/testing/` → `weather-mcp-prompt.yml`.

Most prompt-style Bruno requests in this collection are templates with several alternative rows saved against the same form-field name (e.g. multiple `provider=` rows toggled on/off via the disabled flag). Before sending, select the single row per field that matches the scenario you want to test.

For this test the parameters to enable are:

- `prompt`: `What is current weather in Warsaw ?`
- `provider`: `minimax` (the default in the file — swap to `anthropic` / `openai` / `gemini` if you don't have a MiniMax key)
- `model`: `MiniMax-M2.7` (or the matching model for the provider you pick)
- `embeddingProvider`: `openai`

Header `X-User-Id: frosty` is already pinned.

## Steps

1. Confirm both services respond: `GET http://localhost:9917/` and `GET http://localhost:9998/`.
2. In Bruno, send `weather-mcp-prompt.yml`.
3. Watch the AscendAgent log while the request runs.

## Expected

- HTTP 200; `content` mentions a temperature and a condition for Warsaw — not "I cannot access live data".
- AscendAgent log shows the `getCurrentWeather` MCP tool being invoked for this request id.
- A refusal usually means the chosen provider/model doesn't support tool calls — switch to Anthropic claude-sonnet-4-6 or OpenAI gpt-5.1.

## Bugs this covers

None directly. This is an MCP wiring smoke test.

## Fixtures

None.
