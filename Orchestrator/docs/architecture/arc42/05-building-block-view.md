# 5. Building Block View

## Level 1: System Decomposition

```mermaid
graph TB
    subgraph "AscendAI Platform"
        Orchestrator["Orchestrator<br/>(Spring Boot)"]
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

    Orchestrator --> AudioScribe
    Orchestrator --> Weather
    Orchestrator --> WebSearch
    Orchestrator --> Memory
    Orchestrator --> Postgres
    Orchestrator --> Redis
    Orchestrator --> Qdrant
    Orchestrator --> MinIO
    WebSearch --> SearXNG
    WebSearch --> FlareSolverr
```

## Level 2: Orchestrator Internals

```mermaid
graph TB
    subgraph "Orchestrator"
        Controller["PromptController"]
        OrchestratorSvc["ChatOrchestratorService"]
        ContextAssembler["ChatContextAssembler"]
        HistoryService["ChatHistoryService"]
        Executor["ChatExecutor"]
        Resolver["ChatModelResolver"]
        RAG["RagService"]
        Ingestion["IngestionPipelineConfig"]
        MemoryClient["SemanticMemoryClient"]
    end

    Controller --> OrchestratorSvc
    OrchestratorSvc --> ContextAssembler
    OrchestratorSvc --> HistoryService
    OrchestratorSvc --> Executor
    Executor --> Resolver
    ContextAssembler --> RAG
    ContextAssembler --> MemoryClient
```

## Component Responsibilities

| Component | Responsibility |
|---|---|
| `PromptController` | REST endpoint, request validation, provider/model parameter extraction |
| `ChatOrchestratorService` | Orchestrates context assembly, history, AI execution |
| `ChatContextAssembler` | Builds system message with RAG context and semantic memory |
| `ChatHistoryService` | Loads/saves chat history from Redis with PostgreSQL fallback |
| `ChatExecutor` | Builds per-request `ChatClient`, attaches MCP tools, calls LLM |
| `ChatModelResolver` | Resolves `ChatModel` by provider name from pre-initialized map |
| `RagService` | Performs vector similarity search in Qdrant |
| `SemanticMemoryClient` | Direct REST calls to AscendMemory for user profiles |
| `IngestionPipelineConfig` | S3 → Unstructured API → Token splitter → Qdrant pipeline |
