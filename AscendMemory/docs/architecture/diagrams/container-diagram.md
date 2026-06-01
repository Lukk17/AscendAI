# C4 Container Diagram — AscendMemory

```mermaid
graph TB
    accTitle: AscendMemory C4 Container Diagram
    accDescr: Shows AscendMemory and its direct dependencies: callers AscendAgent and MCP clients, and external services Qdrant and the embedding provider.

    subgraph "Callers"
        AscendAgent["AscendAgent\n(Spring Boot, Java 21)\n:9917"]
        MCPClient["MCP-capable Agent\n(any FastMCP client)"]
    end

    subgraph "AscendMemory :7020"
        REST["REST API\n/api/v1/memory/\n(FastAPI, rest_endpoints.py)"]
        MCP["MCP Server\n/mcp\n(FastMCP, mcp_server.py)"]
        Service["AscendMemoryClient\n(memory_client.py)\nper-provider singletons"]
        Config["Settings + PROVIDER_CONFIGS\n(config.py)"]
    end

    subgraph "External Prerequisites"
        Qdrant["Qdrant\n:6333\nvector store"]
        EmbeddingProvider["Embedding Provider\nLM Studio :1234\nor OpenAI / Gemini\n(OpenAI-compat HTTP)"]
    end

    AscendAgent -->|"HTTP REST"| REST
    MCPClient -->|"MCP Streamable HTTP"| MCP
    REST --> Service
    MCP --> Service
    Service --> Config
    Service -->|"mem0ai / qdrant-client"| Qdrant
    Service -->|"POST /embeddings\nOpenAI-compat"| EmbeddingProvider
```

---

AscendAgent is the primary REST caller. It calls `/api/v1/memory/insert` after each chat turn (via
`SemanticMemoryExtractor`) and `/api/v1/memory/search` at prompt time (via `SemanticMemoryClient`). The MCP surface
at `/mcp` exposes the same operations as tools; AscendAgent does not use this path, but any FastMCP-capable agent
can.

Both REST and MCP handlers delegate to `AscendMemoryClient` via `get_memory_client()`. That client constructs a
`mem0.Memory` instance from the per-provider configuration in `PROVIDER_CONFIGS`, which maps each named provider to
its embedding model, Qdrant collection, base URL, and API key env var.

Qdrant stores the vectors. The embedding provider generates them. In the default configuration (`provider=lmstudio`),
LM Studio runs locally at port 1234 serving `text-embedding-nomic-embed-text-v2-moe` (768 dimensions, collection
`ascend_memory_768`). Switching to `provider=openai` routes to `api.openai.com` and uses collection
`ascend_memory_1536` (1536 dimensions).
