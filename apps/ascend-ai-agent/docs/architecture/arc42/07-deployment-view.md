# 7. Deployment View

---

### Docker Compose topology

```mermaid
graph TB
    subgraph "External Prerequisites"
        Postgres["PostgreSQL<br/>:5432"]
        Redis["Redis<br/>:6379"]
        Qdrant["Qdrant<br/>:6333/6334"]
        S3["S3-compatible storage<br/>:9070/9071"]
    end

    subgraph "Docker Compose Network"
        subgraph "Application Services"
            AscendAiAgent["ascend-ai-agent<br/>:9917"]
            AudioScribe["ascend-audio-scribe<br/>:7017"]
            Weather["ascend-weather-mcp<br/>:9998"]
            WebHunter["ascend-web-hunter<br/>:7021"]
            Memory["AscendMemory<br/>:7020"]
        end

        subgraph "Support Services"
            SearXNG["SearXNG<br/>:9020"]
            FlareSolverr["FlareSolverr<br/>:8191"]
        end
    end

    subgraph "External (Host)"
        LMStudio["LM Studio<br/>:1234"]
    end

    AscendAiAgent -->|"MCP"| AudioScribe
    AscendAiAgent -->|"MCP"| Weather
    AscendAiAgent -->|"MCP"| WebHunter
    AscendAiAgent -->|"REST"| Memory
    AscendAiAgent --> Postgres
    AscendAiAgent --> Redis
    AscendAiAgent --> Qdrant
    AscendAiAgent --> S3
    WebHunter --> SearXNG
    WebHunter --> FlareSolverr
    Memory --> Qdrant
    AscendAiAgent -->|"OpenAI API"| LMStudio
```

---

### Service port map

| Service           | Port(s)                       | Protocol      | Notes                                                   |
| :---------------- | :---------------------------- | :------------ | :------------------------------------------------------ |
| ascend-ai-agent       | 9917                          | HTTP          | Main API gateway.                                       |
| LM Studio         | 1234                          | HTTP          | Local LLM, runs on host, not in Docker.                 |
| ascend-audio-scribe       | 7017                          | HTTP          | MCP server for audio transcription.                     |
| ascend-weather-mcp | 9998                          | HTTP          | MCP server for weather data.                            |
| ascend-web-hunter   | 7021                          | HTTP          | MCP server for web search.                              |
| AscendMemory      | 7020                          | HTTP          | REST API for semantic memory.                           |
| PostgreSQL        | 5432                          | TCP           | Relational database (external prerequisite).            |
| Redis             | 6379                          | TCP           | Cache (external prerequisite).                          |
| Qdrant            | 6333 (HTTP), 6334 (gRPC)      | HTTP / gRPC   | Vector database (external prerequisite).                |
| S3-compatible storage | 9070 (API), 9071 (UI)      | HTTP          | Object storage (external prerequisite), provided locally by a self-hosted emulator and by Amazon S3 in production. |
| SearXNG           | 9020                          | HTTP          | Meta search engine.                                     |
| FlareSolverr      | 8191                          | HTTP          | Cloudflare bypass proxy.                                |

---

### Infrastructure requirements

- **Docker Engine** 24+ with Compose V2.
- **Java 21+** for ascend-ai-agent and ascend-weather-mcp (run outside Docker during dev).
- **Python 3.11+** for ascend-audio-scribe, ascend-web-hunter, AscendMemory.
- **LM Studio** installed on host for local LLM inference.
- **External prerequisites.** PostgreSQL, Redis, Qdrant, and S3-compatible object storage must be running before
  starting docker-compose. In production these map to managed cloud services.
