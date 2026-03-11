# C4 Container Diagram (Level 2)

```mermaid
graph TB
    User["👤 User"]

    subgraph "AscendAI Platform"
        Orchestrator["Orchestrator<br/>(Spring Boot, Java 21)<br/>:9917"]
        AudioScribe["AudioScribe<br/>(FastMCP, Python)<br/>:7017"]
        Weather["WeatherMCP<br/>(Spring Boot, Java)<br/>:9998"]
        WebSearch["AscendWebSearch<br/>(FastMCP, Python)<br/>:7021"]
        Memory["AscendMemory<br/>(FastAPI, Python)<br/>:7020"]
    end

    subgraph "Data Stores"
        Postgres["PostgreSQL<br/>:5432"]
        Redis["Redis<br/>:6379"]
        Qdrant["Qdrant<br/>:6333"]
        MinIO["MinIO<br/>:9070"]
    end

    subgraph "Search Infrastructure"
        SearXNG["SearXNG<br/>:8088"]
        FlareSolverr["FlareSolverr<br/>:8191"]
    end

    subgraph "LLM Providers"
        LMStudio["LM Studio<br/>:1234"]
        CloudAPIs["Cloud APIs<br/>(OpenAI, Gemini, Anthropic, MiniMax)"]
    end

    User -->|"HTTP"| Orchestrator
    Orchestrator -->|"MCP"| AudioScribe
    Orchestrator -->|"MCP"| Weather
    Orchestrator -->|"MCP"| WebSearch
    Orchestrator -->|"REST"| Memory
    Orchestrator --> Postgres
    Orchestrator --> Redis
    Orchestrator --> Qdrant
    Orchestrator --> MinIO
    Orchestrator --> LMStudio
    Orchestrator --> CloudAPIs
    WebSearch --> SearXNG
    WebSearch --> FlareSolverr
    Memory --> Qdrant
```

Each container represents a separately deployable unit. The Orchestrator communicates with MCP services via Streamable HTTP, with data stores via their native protocols, and with LLM providers via HTTP APIs.
