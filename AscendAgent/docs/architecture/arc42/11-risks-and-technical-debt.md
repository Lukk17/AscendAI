# 11. Risks and Technical Debt

## Risks

| Risk | Impact | Mitigation |
|---|---|---|
| LLM provider API changes | Breaking changes to OpenAI-compatible endpoints | Pin Spring AI version, monitor changelogs |
| MCP service unavailability | Tool calls fail at runtime | MCP client timeout (300s), graceful degradation — LLM can respond without tools |
| Token limit exceeded | Large RAG context + history may exceed model context window | Configurable `max-context-chars` (4000) and history `max-size` (50) |

## Technical Debt

| Item | Description | Priority |
|---|---|---|
| Javadoc on public beans | `AppConfig` still has Javadoc comments — should be removed per coding rules | Low |
| Fully qualified names in `AppConfig.s3Client()` | Uses `software.amazon.awssdk.*` inline instead of imports | Low |
| `ChatClient` built per-request | Performance overhead of creating `ChatClient` on every request — consider caching | Medium |
| No rate limiting | Missing per-provider rate limiting for cloud APIs | Medium |

