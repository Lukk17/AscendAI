# 4. Solution Strategy

## Key Architecture Decisions

| Decision | Approach | See ADR |
|---|---|---|
| Multi-provider AI | `ChatModelResolver` manages a `Map<String, ChatModel>` — per-request resolution via `provider` param | [ADR-001](../decisions/ADR-001-multi-provider-ai.md) |
| Gemini & MiniMax integration | OpenAI-compatible endpoints — no separate SDKs | [ADR-002](../decisions/ADR-002-openai-compatible-gemini-minimax.md) |
| Semantic memory | Direct REST calls to AscendMemory instead of MCP | [ADR-003](../decisions/ADR-003-semantic-memory-rest-over-mcp.md) |
| Tool integration | Spring AI MCP client for dynamic tool discovery | [ADR-004](../decisions/ADR-004-mcp-for-tool-integration.md) |

## Technology Choices

| Concern | Choice | Rationale |
|---|---|---|
| Chat model abstraction | Spring AI `ChatModel` + `ChatClient` | Unified builder pattern across OpenAI/Anthropic |
| Concurrency | Java Virtual Threads | Lightweight threads for concurrent LLM calls without thread-pool sizing |
| RAG | Qdrant + Spring AI VectorStore | Cosine similarity search with pluggable embedding models |
| Chat history | Redis (cache) + PostgreSQL (persistent) | Fast reads with durable fallback |
| Document processing | Unstructured API + Spring Integration | Token-aware chunking pipeline from S3 to vector store |

## Design Patterns

- **Strategy Pattern**: `ChatModelResolver` selects `ChatModel` implementation based on provider name
- **Builder Pattern**: `ChatClient` built per-request with resolved model, system prompt, MCP tools, and optional model override
- **Pipeline Pattern**: Document ingestion flows S3 → Unstructured API → Token splitter → Vector store
