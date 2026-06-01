# 10. Quality Requirements

---

### Quality tree

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
    Testability --> T2["Integration tests with Testcontainers (Postgres/Redis/Qdrant/MinIO)"]
    Testability --> T3["E2E capability tests via Bruno collection, behavior assertions only, no log substrings"]

    Security --> S1["API keys from environment variables"]
    Security --> S2["No hardcoded secrets in config"]
```

---

### Quality scenarios

| Quality        | Scenario                                                      | Expected behaviour                                                                                                              |
| :------------- | :------------------------------------------------------------ | :------------------------------------------------------------------------------------------------------------------------------ |
| Extensibility  | Developer adds a new OpenAI-compatible provider.              | Add YAML block under `app.ai.providers`, set `enabled: true`. No Java code changes.                                             |
| Extensibility  | Developer adds a new MCP tool service.                        | Deploy the service, add its URL to `spring.ai.mcp.client.streamable-http.connections`.                                          |
| Reliability    | User requests an unknown provider.                            | `IllegalArgumentException` with list of enabled providers returned as HTTP 400.                                                 |
| Reliability    | LLM returns null response.                                    | `AiGenerationException` thrown, caught by global handler.                                                                       |
| Testability    | Running tests without LLM access.                             | All external dependencies mocked via `@MockitoBean` in `BaseIntegrationTest`.                                                   |
| Testability    | Running integration tests against real backing services.      | `./gradlew integrationTest` boots Postgres / Redis / Qdrant / MinIO via Testcontainers; specs live under [src/test/java/.../integration/](../../../src/test/java/com/lukk/ascend/ai/agent/integration/). |
| Testability    | Running capability tests against a live stack.                | Five numbered specs in [AscendAgent/e2e/testing/](../../../e2e/README.md). Each runnable by Bruno CLI, asserts only observable behaviour (HTTP / response body / persisted state), never log substrings. |
| Security       | API key not set for a provider.                               | Provider remains disabled (`enabled: false`), key defaults to `not-set`.                                                        |
