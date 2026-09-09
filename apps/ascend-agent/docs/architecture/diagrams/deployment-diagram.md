# Deployment Diagram

```mermaid
graph TB
    subgraph "Developer Machine"
        LMStudio["LM Studio<br/>localhost:1234"]
        AscendAiAgent["ascend-ai-agent<br/>localhost:9917<br/>(java -jar)"]
        Weather["ascend-weather-mcp<br/>localhost:9998<br/>(java -jar)"]
    end

    subgraph "External Prerequisites"
        Postgres["PostgreSQL<br/>:5432"]
        Redis["Redis<br/>:6379"]
        Qdrant["Qdrant<br/>:6333/:6334"]
        S3["S3-compatible storage<br/>:9070/:9071"]
    end

    subgraph "Docker Compose"
        SearXNG["SearXNG<br/>:9020"]
        FlareSolverr["FlareSolverr<br/>:8191"]
        AudioScribe["ascend-audio-scribe<br/>:7017"]
        WebHunter["ascend-web-hunter<br/>:7021"]
        Memory["AscendMemory<br/>:7020"]
    end

    subgraph "Cloud (Optional)"
        OpenAI["OpenAI API"]
        Gemini["Gemini API"]
        Anthropic["Anthropic API"]
        MiniMax["MiniMax API"]
    end

    AscendAiAgent --> LMStudio
    AscendAiAgent --> Postgres
    AscendAiAgent --> Redis
    AscendAiAgent --> Qdrant
    AscendAiAgent --> S3
    AscendAiAgent --> AudioScribe
    AscendAiAgent --> Weather
    AscendAiAgent --> WebHunter
    AscendAiAgent --> Memory
    AscendAiAgent -.-> OpenAI
    AscendAiAgent -.-> Gemini
    AscendAiAgent -.-> Anthropic
    AscendAiAgent -.-> MiniMax
    WebHunter --> SearXNG
    WebHunter --> FlareSolverr
    Memory --> Qdrant
```

In development, the ascend-ai-agent and ascend-weather-mcp run directly on the host JVM. PostgreSQL, Redis, Qdrant, and
S3-compatible object storage (provided locally by a self-hosted emulator) are external prerequisites that must be running before
starting docker-compose (in production these map to managed cloud services, with Amazon S3 in its place).
Application and support services (ascend-audio-scribe, ascend-web-hunter, AscendMemory, SearXNG, FlareSolverr) run in Docker
Compose. Cloud AI providers are optional (dashed lines), only accessed when their provider is enabled and selected.
