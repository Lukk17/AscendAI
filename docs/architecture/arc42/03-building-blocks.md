# 3. Building Block View

## Level 1: Service Decomposition

```mermaid
graph TB
    subgraph "Application Services"
        Agent["AscendAgent<br/>Java 21 · Spring Boot<br/>:9917"]
        AudioScribe["AudioScribe<br/>Python · FastMCP<br/>:7017"]
        Weather["WeatherMCP<br/>Java · Spring Boot<br/>:9998"]
        WebSearch["AscendWebSearch<br/>Python · FastMCP<br/>:7021"]
        Memory["AscendMemory<br/>Python · FastAPI<br/>:7020"]
        PaddleOCR["PaddleOCR<br/>Python · FastMCP<br/>:7022"]
    end

    subgraph "External Prerequisites"
        Postgres["PostgreSQL :5432"]
        Redis["Redis :6379"]
        Qdrant["Qdrant :6333"]
        MinIO["MinIO :9070"]
    end

    subgraph "Support Services"
        SearXNG["SearXNG :9020"]
        Flare["FlareSolverr :8191"]
        Docling["Docling :5001"]
        Unstructured["Unstructured :9080"]
    end

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
    WebSearch --> SearXNG
    WebSearch --> Flare
    Memory --> Qdrant
```

## Service Responsibilities

| Service | Role | Tech Stack | Communication |
|---|---|---|---|
| **AscendAgent** | Central gateway — receives user prompts, routes to AI providers, assembles context (RAG + memory + history), dispatches MCP tool calls | Java 21, Spring Boot 3.5, Spring AI 1.1 | REST API (inbound), MCP client (outbound) |
| **AudioScribe** | Audio transcription — local (faster-whisper/GPU), OpenAI Whisper API, or HuggingFace. Supports multi-track Audacity projects | Python 3.11, FastMCP | MCP server + REST API |
| **WeatherMCP** | Current weather data provider | Java 21, Spring Boot 3.5, Spring AI | MCP server |
| **AscendWebSearch** | Web search via SearXNG + multi-tiered content extraction with Cloudflare bypass | Python 3.12, FastMCP, Playwright | MCP server + REST API |
| **AscendMemory** | Semantic memory — stores/searches user-scoped facts using mem0ai + Qdrant | Python 3.11, FastAPI, mem0ai | REST API + MCP server |
| **PaddleOCR** | OCR text extraction from images, multi-language | Python 3.11, FastMCP, PaddleOCR | MCP server + REST API |

## How Services Interact

### Prompt Flow (happy path)

```mermaid
sequenceDiagram
    actor User
    participant Agent as AscendAgent
    participant Redis
    participant Qdrant
    participant Memory as AscendMemory
    participant LLM as AI Provider
    participant MCP as MCP Services

    User->>Agent: POST /api/v1/ai/prompt
    Agent->>Redis: Load chat history
    Agent->>Qdrant: RAG similarity search
    Agent->>Memory: Search semantic memory
    Agent->>Agent: Assemble system prompt<br/>(RAG + memory + history)
    Agent->>LLM: Chat completion request

    alt LLM decides to use a tool
        LLM-->>Agent: tool_call response
        Agent->>MCP: Execute tool (e.g., web_search)
        MCP-->>Agent: Tool result
        Agent->>LLM: Continue with tool result
    end

    LLM-->>Agent: Final response
    Agent->>Redis: Save to chat history
    Agent->>Memory: Extract & store new facts (async)
    Agent-->>User: JSON response
```

### Document Ingestion Flow

```mermaid
sequenceDiagram
    participant MinIO as MinIO (S3)
    participant Agent as AscendAgent
    participant Docling as Docling / Unstructured
    participant Qdrant

    MinIO->>Agent: New document detected (polling)
    Agent->>Docling: Parse document (PDF/DOCX)
    Docling-->>Agent: Extracted text
    Agent->>Agent: Token-aware chunking
    Agent->>Qdrant: Store embeddings
```

## Detailed Module Documentation

Each module has its own `AGENTS.md` with build instructions, architecture details, and conventions:

- [AscendAgent](../../AscendAgent/AGENTS.md) — includes internal arc42 docs in `AscendAgent/docs/architecture/`
- [AudioScribe](../../AudioScribe/AGENTS.md)
- [AscendWebSearch](../../AscendWebSearch/AGENTS.md)
- [AscendMemory](../../AscendMemory/AGENTS.md)
- [WeatherMCP](../../WeatherMCP/AGENTS.md)
- [PaddleOCR](../../PaddleOCR/AGENTS.md)
