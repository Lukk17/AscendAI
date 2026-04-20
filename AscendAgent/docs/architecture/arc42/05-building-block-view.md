# 5. Building Block View

## Level 1: System Decomposition

```mermaid
graph TB
    subgraph "AscendAI Platform"
        AscendAgent["AscendAgent<br/>(Spring Boot)"]
        AudioScribe["AudioScribe<br/>(FastMCP/Python)"]
        Weather["WeatherMCP<br/>(Spring Boot/Java)"]
        WebSearch["AscendWebSearch<br/>(FastMCP/Python)"]
        Memory["AscendMemory<br/>(FastAPI/Python)"]
    end

    subgraph "Infrastructure"
        Postgres["PostgreSQL"]
        Redis["Redis"]
        Qdrant["Qdrant"]
        MinIO["MinIO"]
        SearXNG["SearXNG"]
        FlareSolverr["FlareSolverr"]
    end

    AscendAgent --> AudioScribe
    AscendAgent --> Weather
    AscendAgent --> WebSearch
    AscendAgent --> Memory
    AscendAgent --> Postgres
    AscendAgent --> Redis
    AscendAgent --> Qdrant
    AscendAgent --> MinIO
    WebSearch --> SearXNG
    WebSearch --> FlareSolverr
```

## Level 2: AscendAgent Internals

```mermaid
graph TB
    subgraph "AscendAgent"
        Controller["PromptController"]
        AscendAgentSvc["AscendChatService"]
        ContextAssembler["ChatContextAssembler"]
        HistoryService["ChatHistoryService"]
        Executor["ChatExecutor"]
        Resolver["ChatModelResolver"]
        RAG["RagService"]
        Ingestion["IngestionPipelineConfig"]
        MemoryClient["SemanticMemoryClient"]
    end

    Controller --> AscendAgentSvc
    AscendAgentSvc --> ContextAssembler
    AscendAgentSvc --> HistoryService
    AscendAgentSvc --> Executor
    Executor --> Resolver
    ContextAssembler --> RAG
    ContextAssembler --> MemoryClient
```

## Component Responsibilities

| Component | Responsibility |
|---|---|
| `PromptController` | REST endpoint, request validation, provider/model parameter extraction |
| `AscendChatService` | Orchestrates context assembly, history, AI execution |
| `ChatContextAssembler` | Builds system message with RAG context and semantic memory |
| `ChatHistoryService` | Loads/saves chat history from Redis with PostgreSQL fallback |
| `ChatExecutor` | Builds per-request `ChatClient`, attaches MCP tools, calls LLM |
| `ChatModelResolver` | Resolves `ChatModel` by provider name from pre-initialized map |
| `RagService` | Performs vector similarity search in Qdrant |
| `SemanticMemoryClient` | Direct REST calls to AscendMemory for user profiles |
| `IngestionPipelineConfig` | S3 → Unstructured API → Token splitter → Qdrant pipeline |
