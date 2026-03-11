# 10. Quality Requirements

## Quality Tree

```mermaid
graph TB
    Quality["Quality"]
    Quality --> Extensibility
    Quality --> Reliability
    Quality --> Testability
    Quality --> Security

    Extensibility --> E1["New AI provider = YAML entry only"]
    Extensibility --> E2["New MCP tool = deploy service + add URL"]

    Reliability --> R1["Fail-fast on unknown provider"]
    Reliability --> R2["Null response detection in ChatExecutor"]

    Testability --> T1["Unit tests with @Mock/@InjectMocks"]
    Testability --> T2["Integration tests with mocked external deps"]

    Security --> S1["API keys from environment variables"]
    Security --> S2["No hardcoded secrets in config"]
```

## Quality Scenarios

| Quality | Scenario | Expected Behavior |
|---|---|---|
| Extensibility | Developer adds a new OpenAI-compatible provider | Add YAML block under `app.ai.providers`, set `enabled: true` — no Java code changes |
| Extensibility | Developer adds a new MCP tool service | Deploy the service, add its URL to `spring.ai.mcp.client.streamable-http.connections` |
| Reliability | User requests an unknown provider | `IllegalArgumentException` with list of enabled providers returned as HTTP 400 |
| Reliability | LLM returns null response | `AiGenerationException` thrown, caught by global handler |
| Testability | Running tests without LLM access | All external dependencies mocked via `@MockitoBean` in `BaseIntegrationTest` |
| Security | API key not set for a provider | Provider remains disabled (`enabled: false`), key defaults to `not-set` |
