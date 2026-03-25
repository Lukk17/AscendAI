# 7. Deployment View

## Docker Compose Topology

```mermaid
graph TB
    subgraph "Docker Compose Network"
        subgraph "Application Services"
            Orchestrator["Orchestrator<br/>:9917"]
            AudioScribe["AudioScribe<br/>:7017"]
            Weather["WeatherMCP<br/>:9998"]
            WebSearch["AscendWebSearch<br/>:7021"]
            Memory["AscendMemory<br/>:7020"]
        end

        subgraph "Infrastructure Services"
            Postgres["PostgreSQL<br/>:5432"]
            Redis["Redis<br/>:6379"]
            Qdrant["Qdrant<br/>:6333/6334"]
            MinIO["MinIO<br/>:9070/9071"]
            SearXNG["SearXNG<br/>:8088"]
            FlareSolverr["FlareSolverr<br/>:8191"]
        end

        subgraph "External (Host)"
            LMStudio["LM Studio<br/>:1234"]
        end
    end

    Orchestrator -->|"MCP"| AudioScribe
    Orchestrator -->|"MCP"| Weather
    Orchestrator -->|"MCP"| WebSearch
    Orchestrator -->|"REST"| Memory
    Orchestrator --> Postgres
    Orchestrator --> Redis
    Orchestrator --> Qdrant
    Orchestrator --> MinIO
    WebSearch --> SearXNG
    WebSearch --> FlareSolverr
    Memory --> Qdrant
    Orchestrator -->|"OpenAI API"| LMStudio
```

## Service Port Map

| Service | Port(s) | Protocol | Notes |
|---|---|---|---|
| Orchestrator | 9917 | HTTP | Main API gateway |
| LM Studio | 1234 | HTTP | Local LLM (runs on host, not in Docker) |
| AudioScribe | 7017 | HTTP | MCP server for audio transcription |
| WeatherMCP | 9998 | HTTP | MCP server for weather data |
| AscendWebSearch | 7021 | HTTP | MCP server for web search |
| AscendMemory | 7020 | HTTP | REST API for semantic memory |
| PostgreSQL | 5432 | TCP | Relational database |
| Redis | 6379 | TCP | Cache |
| Qdrant | 6333 (HTTP), 6334 (gRPC) | HTTP/gRPC | Vector database |
| MinIO | 9070 (API), 9071 (Console) | HTTP | S3-compatible object storage |
| SearXNG | 8088 | HTTP | Meta search engine |
| FlareSolverr | 8191 | HTTP | Cloudflare bypass proxy |

## Infrastructure Requirements

- **Docker Engine** 24+ with Compose V2
- **Java 21+** for Orchestrator and WeatherMCP (run outside Docker during dev)
- **Python 3.11+** for AudioScribe, AscendWebSearch, AscendMemory
- **LM Studio** installed on host for local LLM inference
