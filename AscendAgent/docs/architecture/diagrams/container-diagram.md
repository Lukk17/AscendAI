# C4 Container Diagram (Level 2)

```mermaid
graph TB
    User["👤 User"]

    subgraph "AscendAI Platform"
        AscendAgent["AscendAgent<br/>(Spring Boot, Java 21)<br/>:9917"]
        AudioScribe["ascend-audio-scribe<br/>(FastMCP, Python)<br/>:7017"]
        Weather["ascend-weather-mcp<br/>(Spring Boot, Java)<br/>:9998"]
        WebHunter["ascend-web-hunter<br/>(FastMCP, Python)<br/>:7021"]
        Memory["AscendMemory<br/>(FastAPI, Python)<br/>:7020"]
    end

    subgraph "External Prerequisites"
        Postgres["PostgreSQL<br/>:5432"]
        Redis["Redis<br/>:6379"]
        Qdrant["Qdrant<br/>:6333"]
        S3["S3-compatible storage<br/>:9070"]
    end

    subgraph "Search Infrastructure"
        SearXNG["SearXNG<br/>:9020"]
        FlareSolverr["FlareSolverr<br/>:8191"]
    end

    subgraph "LLM Providers"
        LMStudio["LM Studio<br/>:1234"]
        CloudAPIs["Cloud APIs<br/>(OpenAI, Gemini, Anthropic, MiniMax)"]
    end

    User -->|"HTTP"| AscendAgent
    AscendAgent -->|"MCP"| AudioScribe
    AscendAgent -->|"MCP"| Weather
    AscendAgent -->|"MCP"| WebHunter
    AscendAgent -->|"REST"| Memory
    AscendAgent --> Postgres
    AscendAgent --> Redis
    AscendAgent --> Qdrant
    AscendAgent --> S3
    AscendAgent --> LMStudio
    AscendAgent --> CloudAPIs
    WebHunter --> SearXNG
    WebHunter --> FlareSolverr
    Memory --> Qdrant
```

Each container represents a separately deployable unit. The AscendAgent communicates with MCP services via Streamable HTTP, with data stores via their native protocols, and with LLM providers via HTTP APIs. PostgreSQL, Redis, Qdrant, and S3-compatible object storage (provided locally by a self-hosted emulator) are external prerequisites (in production these map to managed cloud services, with Amazon S3 in its place).
