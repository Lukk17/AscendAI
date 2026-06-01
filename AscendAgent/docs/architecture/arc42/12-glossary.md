# 12. Glossary

| Term                       | Definition                                                                                                            |
| :------------------------- | :-------------------------------------------------------------------------------------------------------------------- |
| **ChatModel**              | Spring AI abstraction for a chat completion model (OpenAI, Anthropic, etc.).                                          |
| **ChatClient**             | Spring AI builder that combines a `ChatModel` with system prompt, tools, and advisors.                                |
| **ChatModelResolver**      | AscendAI component that manages and resolves `ChatModel` instances by provider name.                                  |
| **MCP**                    | Model Context Protocol. Open standard for LLM tool integration via Streamable HTTP.                                   |
| **RAG**                    | Retrieval-Augmented Generation. Enriching prompts with relevant document fragments from a vector store.               |
| **Provider**               | A named AI service configuration (e.g. `lmstudio`, `openai`, `gemini`, `anthropic`, `minimax`).                       |
| **Semantic Memory**        | Long-term user context stored in AscendMemory, retrieved per prompt to personalise responses.                         |
| **Ingestion Pipeline**     | S3 to Unstructured API to Token Splitter to Qdrant flow for indexing documents.                                       |
| **Virtual Threads**        | Java 21 lightweight threads that enable high-throughput concurrency without thread-pool sizing.                       |
| **Qdrant**                 | Open-source vector database used for RAG similarity search.                                                           |
| **SearXNG**                | Privacy-respecting meta search engine used by AscendWebSearch.                                                        |
| **FlareSolverr**           | Proxy for bypassing Cloudflare protection, used by AscendWebSearch.                                                   |
