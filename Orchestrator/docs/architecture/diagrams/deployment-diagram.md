# Deployment Diagram

```mermaid
graph TB
    subgraph "Developer Machine"
        LMStudio["LM Studio<br/>localhost:1234"]
        Orchestrator["Orchestrator<br/>localhost:9917<br/>(java -jar)"]
        Weather["WeatherMCP<br/>localhost:9998<br/>(java -jar)"]
    end

    subgraph "Docker Compose"
        Postgres["PostgreSQL<br/>:5432"]
        Redis["Redis<br/>:6379"]
        Qdrant["Qdrant<br/>:6333/:6334"]
        MinIO["MinIO<br/>:9070/:9071"]
        SearXNG["SearXNG<br/>:8088"]
        FlareSolverr["FlareSolverr<br/>:8191"]
        AudioScribe["AudioScribe<br/>:7017"]
        WebSearch["AscendWebSearch<br/>:7021"]
        Memory["AscendMemory<br/>:7020"]
    end

    subgraph "Cloud (Optional)"
        OpenAI["OpenAI API"]
        Gemini["Gemini API"]
        Anthropic["Anthropic API"]
        MiniMax["MiniMax API"]
    end

    Orchestrator --> LMStudio
    Orchestrator --> Postgres
    Orchestrator --> Redis
    Orchestrator --> Qdrant
    Orchestrator --> MinIO
    Orchestrator --> AudioScribe
    Orchestrator --> Weather
    Orchestrator --> WebSearch
    Orchestrator --> Memory
    Orchestrator -.-> OpenAI
    Orchestrator -.-> Gemini
    Orchestrator -.-> Anthropic
    Orchestrator -.-> MiniMax
    WebSearch --> SearXNG
    WebSearch --> FlareSolverr
    Memory --> Qdrant
```

In development, the Orchestrator and WeatherMCP run directly on the host JVM. All infrastructure services and Python-based MCP servers run in Docker Compose. Cloud AI providers are optional (dashed lines) — only accessed when their provider is enabled and selected.
