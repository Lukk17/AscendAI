# 8. Crosscutting Concepts

## Multi-Provider AI

The `ChatModelResolver` initializes a `Map<String, ChatModel>` at startup from `app.ai.providers` configuration. Each enabled provider produces either an `OpenAiChatModel` (for OpenAI-compatible endpoints including LM Studio, Gemini, MiniMax) or an `AnthropicChatModel`. Provider selection is per-request via the `provider` query parameter, with a configurable default fallback. The `model` parameter optionally overrides the provider's default model at runtime.

## Model Context Protocol (MCP)

MCP services expose tools via Streamable HTTP endpoints. The Orchestrator discovers available tools at startup using `SyncMcpToolCallbackProvider` and attaches them to every `ChatClient` instance. When an LLM decides to use a tool, Spring AI transparently routes the call to the appropriate MCP service.

Currently registered MCP services:
- **AudioScribe** — audio transcription
- **WeatherMCP** — current weather data
- **AscendWebSearch** — web search via SearXNG

## RAG (Retrieval-Augmented Generation)

Documents uploaded to MinIO are processed through an ingestion pipeline: Unstructured API parses the document, a token splitter chunks it, and embeddings are stored in Qdrant. At prompt time, `RagService` performs a cosine similarity search and injects the top-k relevant fragments into the system prompt.

## Semantic Memory

`SemanticMemoryClient` calls AscendMemory's REST API to store and retrieve user-specific context. This enriches the system prompt with long-term user preferences and interaction patterns. AscendMemory uses Qdrant for its own vector storage.

## Chat History

`ChatHistoryService` maintains conversational context using a dual-store approach:
- **Redis**: Fast cache with configurable TTL (default: 24 hours)
- **PostgreSQL**: Persistent store via Spring Integration JDBC metadata

## Error Handling

Global exception handlers return structured error responses. The `ChatExecutor` throws `AiGenerationException` for null responses. The `ChatModelResolver` throws `IllegalArgumentException` for unknown or disabled providers with a descriptive message listing available providers.
