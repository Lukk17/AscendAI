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
        S3["S3-compatible storage<br/>:9070/:9071"]
    end

    subgraph "Docker Compose"
        SearXNG["SearXNG<br/>:9020"]
        FlareSolverr["FlareSolverr<br/>:8191"]
        AudioScribe["AudioScribe<br/>:7017"]
        WebHunter["ascend-web-hunter<br/>:7021"]
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
    AscendAgent --> S3
    AscendAgent --> AudioScribe
    AscendAgent --> Weather
    AscendAgent --> WebHunter
    AscendAgent --> Memory
    AscendAgent -.-> OpenAI
    AscendAgent -.-> Gemini
    AscendAgent -.-> Anthropic
    AscendAgent -.-> MiniMax
    WebHunter --> SearXNG
    WebHunter --> FlareSolverr
    Memory --> Qdrant
```

In development, the AscendAgent and WeatherMCP run directly on the host JVM. PostgreSQL, Redis, Qdrant, and
S3-compatible object storage (provided locally by a self-hosted emulator) are external prerequisites that must be running before
starting docker-compose (in production these map to managed cloud services, with Amazon S3 in its place).
Application and support services (AudioScribe, ascend-web-hunter, AscendMemory, SearXNG, FlareSolverr) run in Docker
Compose. Cloud AI providers are optional (dashed lines), only accessed when their provider is enabled and selected.
