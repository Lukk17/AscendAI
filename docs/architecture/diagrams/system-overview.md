# System Overview Diagram

```mermaid
graph TB
    User["User"]

    subgraph "AscendAI Platform"
        Agent["AscendAgent<br/>REST API :9917<br/>Spring Boot · Java 21"]

        subgraph "MCP Tool Services"
            AudioScribe["ascend-audio-scribe<br/>:7017<br/>Audio Transcription"]
            Weather["ascend-weather-mcp<br/>:9998<br/>Weather Data"]
            WebHunter["ascend-web-hunter<br/>:7021<br/>Web Search"]
            PaddleOCR["ascend-ocr<br/>:7022<br/>OCR"]
        end

        subgraph "Memory & Storage"
            Memory["AscendMemory<br/>:7020<br/>Semantic Memory"]
        end
    end

    subgraph "AI Providers"
        Local["LM Studio :1234<br/>(local, default)"]
        Cloud["Cloud APIs<br/>OpenAI · Anthropic<br/>Gemini · MiniMax"]
    end

    subgraph "Data Layer (External Prerequisites)"
        PG["PostgreSQL :5432<br/>Chat history · Metadata"]
        RD["Redis :6379<br/>Chat cache"]
        QD["Qdrant :6333<br/>Vector DB (RAG + Memory)"]
        S3["S3-compatible storage :9070<br/>Document storage"]
    end

    subgraph "Support (Docker)"
        SX["SearXNG :9020"]
        FS["FlareSolverr :8191"]
        DL["Docling :5001"]
        UN["Unstructured :9080"]
    end

    User -->|"POST /api/v1/ai/prompt"| Agent

    Agent -->|"MCP"| AudioScribe
    Agent -->|"MCP"| Weather
    Agent -->|"MCP"| WebHunter
    Agent -->|"MCP"| PaddleOCR
    Agent -->|"REST"| Memory

    Agent -.-> Local
    Agent -.-> Cloud

    Agent --> PG
    Agent --> RD
    Agent --> QD
    Agent --> S3
    Agent --> DL
    Agent --> UN

    WebHunter --> SX
    WebHunter --> FS
    Memory --> QD
```

---

### Data flow summary

| Flow                | Path                                                                | Protocol                            |
| :------------------ | :------------------------------------------------------------------ | :---------------------------------- |
| User prompt         | User to AscendAgent to AI Provider to User                          | REST + LLM API                      |
| Tool call           | AscendAgent to MCP Service to AscendAgent                           | MCP (Streamable HTTP)               |
| RAG retrieval       | AscendAgent to Qdrant                                               | gRPC / HTTP                         |
| Memory              | AscendAgent to AscendMemory to Qdrant                               | REST + Qdrant API                   |
| Chat history        | AscendAgent to Redis (read / write), PostgreSQL (persist)           | TCP                                 |
| Document ingestion  | S3-compatible storage to AscendAgent to Docling / Unstructured to Qdrant | S3 + REST + Qdrant              |
| Web search          | AscendAgent to ascend-web-hunter to SearXNG to FlareSolverr           | MCP + HTTP                          |
