# 8. Crosscutting Concepts

## Multi-Provider AI

The `ChatModelResolver` initializes a `Map<String, ChatModel>` at startup from `app.ai.providers` configuration. Each enabled provider produces either an `OpenAiChatModel` (for OpenAI-compatible endpoints like Gemini) or an `AnthropicChatModel` (for LM Studio, Anthropic, MiniMax). Provider selection is per-request via the `provider` query parameter, with a configurable default fallback. The `model` parameter optionally overrides the provider's default model at runtime. 
Additionally, each provider configures a `default-embedding` flag to automatically fallback to a stable vector translation model (e.g., mapping Minimax embeddings natively through OpenAI) if the client omits an explicit embedding provider.

Providers using `type: anthropic` may return multi-block responses where the first block contains internal chain-of-thought reasoning. The `ChatResponseContentResolver` resolves the last non-blank `Generation` text from any `ChatResponse`, transparently handling both single-generation and multi-generation (thinking model) responses.

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

> **Prerequisite**: `ascend-memory` requires **LM Studio** to be running locally on port 1234 (serving `text-embedding-nomic-embed-text-v2-moe`) to generate vector embeddings. If LM Studio is unavailable, memory operations will fail with a 500 Internal Server Error.

To ensure deterministic extraction without latency penalties, the Orchestrator employs an asynchronous **SemanticMemoryExtractor** pattern. Following a successful `ChatExecutor` prompt, a Virtual Thread triggers a secondary LLM request using a low-cost, high-speed model (e.g., `gemini-flash-lite-latest` or `claude-3-5-haiku-20241022`) configured per-provider. This explicitly extracts identity and preference facts from the user's input, bypassing unpredictable MCP tool calls, and POSTs the JSON payload to AscendMemory for storage. The extractor uses `ChatResponseContentResolver` to correctly handle thinking-model responses during fact extraction.

## Chat History

`ChatHistoryService` maintains conversational context using a dual-store approach:
- **Redis**: Fast cache with configurable max size (5 turns) utilizing a sliding window to align with industry standard context windows and prevent token flooding.
- **PostgreSQL**: Persistent store via Spring Integration JDBC metadata

## Error Handling

Global exception handlers return structured error responses. The `ChatExecutor` throws `AiGenerationException` for null responses. The `ChatModelResolver` throws `IllegalArgumentException` for unknown or disabled providers with a descriptive message listing available providers.
