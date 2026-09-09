# 5. Building Block View

---

### Level 1: system decomposition

```mermaid
graph TB
    subgraph "AscendAI Platform"
        AscendAiAgent["ascend-ai-agent<br/>(Spring Boot)"]
        AudioScribe["ascend-audio-scribe<br/>(FastMCP/Python)"]
        Weather["ascend-weather-mcp<br/>(Spring Boot/Java)"]
        WebHunter["ascend-web-hunter<br/>(FastMCP/Python)"]
        Memory["AscendMemory<br/>(FastAPI/Python)"]
    end

    subgraph "Infrastructure"
        Postgres["PostgreSQL"]
        Redis["Redis"]
        Qdrant["Qdrant"]
        S3["S3-compatible storage"]
        SearXNG["SearXNG"]
        FlareSolverr["FlareSolverr"]
    end

    AscendAiAgent --> AudioScribe
    AscendAiAgent --> Weather
    AscendAiAgent --> WebHunter
    AscendAiAgent --> Memory
    AscendAiAgent --> Postgres
    AscendAiAgent --> Redis
    AscendAiAgent --> Qdrant
    AscendAiAgent --> S3
    WebHunter --> SearXNG
    WebHunter --> FlareSolverr
```

---

### Level 2: ascend-ai-agent internals

```mermaid
graph TB
    subgraph "ascend-ai-agent"
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

---

### Component responsibilities

| Component                  | Responsibility                                                                                            |
| :------------------------- | :-------------------------------------------------------------------------------------------------------- |
| `PromptController`         | REST endpoint, request validation, provider / model parameter extraction.                                 |
| `AscendChatService`        | Orchestrates context assembly, history, AI execution.                                                     |
| `ChatContextAssembler`     | Builds system message with RAG context and semantic memory.                                               |
| `ChatHistoryService`       | Loads / saves chat history from Redis with PostgreSQL fallback.                                           |
| `ChatExecutor`             | Builds per-request `ChatClient`, attaches MCP tools, calls LLM.                                           |
| `ChatModelResolver`        | Resolves `ChatModel` by provider name from a pre-initialised map.                                         |
| `RagService`               | Performs vector similarity search in Qdrant.                                                              |
| `SemanticMemoryClient`     | Direct REST calls to AscendMemory for user profiles.                                                      |
| `IngestionPipelineConfig`  | S3 to Unstructured API to Token splitter to Qdrant pipeline.                                              |
