# 2. System Context

## Context Diagram

```mermaid
graph TB
    User["User / Client"]

    subgraph "AscendAI Platform"
        Agent["AscendAgent"]
        AudioScribe["AudioScribe"]
        Weather["WeatherMCP"]
        WebSearch["AscendWebSearch"]
        Memory["AscendMemory"]
        PaddleOCR["PaddleOCR"]
    end

    subgraph "AI Providers"
        LMStudio["LM Studio (local)"]
        OpenAI["OpenAI"]
        Anthropic["Anthropic"]
        Gemini["Gemini"]
        MiniMax["MiniMax"]
    end

    subgraph "External Prerequisites"
        Postgres["PostgreSQL"]
        Redis["Redis"]
        Qdrant["Qdrant"]
        MinIO["MinIO"]
    end

    subgraph "Support Services (Docker)"
        SearXNG["SearXNG"]
        FlareSolverr["FlareSolverr"]
        Docling["Docling Serve"]
        Unstructured["Unstructured API"]
    end

    User -->|"REST API"| Agent
    Agent -->|"MCP"| AudioScribe
    Agent -->|"MCP"| Weather
    Agent -->|"MCP"| WebSearch
    Agent -->|"MCP"| PaddleOCR
    Agent -->|"REST"| Memory
    Agent --> Postgres
    Agent --> Redis
    Agent --> Qdrant
    Agent --> MinIO
    Agent --> Docling
    Agent --> Unstructured
    Agent -.->|"per-request"| LMStudio
    Agent -.->|"per-request"| OpenAI
    Agent -.->|"per-request"| Anthropic
    Agent -.->|"per-request"| Gemini
    Agent -.->|"per-request"| MiniMax
    WebSearch --> SearXNG
    WebSearch --> FlareSolverr
    Memory --> Qdrant
```

## External Interfaces

| Interface | Protocol | Direction | Purpose |
|---|---|---|---|
| User REST API | HTTP/JSON, multipart | Inbound | Prompt with optional image/document/provider/model |
| LLM Provider APIs | HTTP/JSON | Outbound | Chat completion (OpenAI-compatible or Anthropic SDK) |
| MCP Tool Services | Streamable HTTP (JSON-RPC) | Outbound | Tool discovery and invocation |
| AscendMemory | REST API | Outbound | Semantic memory insert/search/delete |
| PostgreSQL | TCP (JDBC) | Outbound | Persistent chat history, ingestion metadata |
| Redis | TCP | Outbound | Short-term chat history cache |
| Qdrant | HTTP/gRPC | Outbound | Vector similarity search (RAG + memory) |
| MinIO | S3 API | Outbound | Document object storage for ingestion |
