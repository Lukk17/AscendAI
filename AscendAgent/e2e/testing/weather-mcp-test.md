### Weather MCP — End-to-End Test

Verifies the AscendAgent discovers and calls the WeatherMCP tool when the prompt asks about weather.

#### Pre-flight

```bash
curl http://localhost:9917/   # AscendAgent
curl http://localhost:9998/   # WeatherMCP
```

Both must respond. WeatherMCP must be reachable from AscendAgent at startup — if WeatherMCP was started after AscendAgent, restart AscendAgent so the MCP client picks it up.

#### Test — Ask about the weather

Use a chat provider that handles tool calls reliably (Anthropic / OpenAI / Gemini). LM Studio works only if the loaded model supports tool use.

```bash
curl -X POST http://localhost:9917/api/v1/ai/prompt \
  -H "X-User-Id: weatherttest-001" \
  -F "prompt=What is the current weather in Warsaw?" \
  -F "provider=anthropic" -F "model=claude-sonnet-4-6"
```

**Pass:**
- HTTP 200; response `content` mentions concrete weather data (temperature, condition) for Warsaw — not a generic "I don't have real-time data" answer.
- AscendAgent log shows the `getCurrentWeather` MCP tool being invoked for this request.

If the response is a "I can't access real-time weather" answer, the agent didn't call the tool — check that WeatherMCP is registered in AscendAgent's MCP client config and that the chosen chat provider/model supports tool calls.
