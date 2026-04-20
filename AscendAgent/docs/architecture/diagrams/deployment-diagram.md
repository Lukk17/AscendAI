# Deployment Diagram

```mermaid
graph TB
    subgraph "Developer Machine"
        LMStudio["LM Studio<br/>localhost:1234"]
        AscendAgent["AscendAgent<br/>localhost:9917<br/>(java -jar)"]
        Weather["WeatherMCP<br/>localhost:9998<br/>(java -jar)"]
    end

    subgraph "External Prerequisites"
        Postgres["PostgreSQL<br/>:5432"]
        Redis["Redis<br/>:6379"]
        Qdrant["Qdrant<br/>:6333/:6334"]
        MinIO["MinIO<br/>:9070/:9071"]
    end

    subgraph "Docker Compose"
        SearXNG["SearXNG<br/>:9020"]
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

    AscendAgent --> LMStudio
    AscendAgent --> Postgres
    AscendAgent --> Redis
    AscendAgent --> Qdrant
    AscendAgent --> MinIO
    AscendAgent --> AudioScribe
    AscendAgent --> Weather
    AscendAgent --> WebSearch
    AscendAgent --> Memory
    AscendAgent -.-> OpenAI
    AscendAgent -.-> Gemini
    AscendAgent -.-> Anthropic
    AscendAgent -.-> MiniMax
    WebSearch --> SearXNG
    WebSearch --> FlareSolverr
    Memory --> Qdrant
```

In development, the AscendAgent and WeatherMCP run directly on the host JVM. PostgreSQL, Redis, Qdrant, and MinIO are external prerequisites that must be running before starting docker-compose (in production these map to managed cloud services). Application and support services (AudioScribe, AscendWebSearch, AscendMemory, SearXNG, FlareSolverr) run in Docker Compose. Cloud AI providers are optional (dashed lines) — only accessed when their provider is enabled and selected.
