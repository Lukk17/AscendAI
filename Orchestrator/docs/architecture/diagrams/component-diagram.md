# C4 Component Diagram (Level 3) — Orchestrator

```mermaid
graph TB
    subgraph "Orchestrator"
        subgraph "API Layer"
            Controller["PromptController<br/>/api/v1/ai/prompt"]
        end

        subgraph "Service Layer"
            OrchestratorSvc["ChatOrchestratorService"]
            ContextAssembler["ChatContextAssembler"]
            HistoryService["ChatHistoryService"]
            Executor["ChatExecutor"]
            Resolver["ChatModelResolver"]
            RAG["RagService"]
            MemoryClient["SemanticMemoryClient"]
        end

        subgraph "Configuration"
            AppConfig["AppConfig"]
            ProviderProps["AiProviderProperties"]
            IngestionConfig["IngestionPipelineConfig"]
        end
    end

    subgraph "External"
        LLM["AI Providers"]
        MCP["MCP Services"]
        Memory["AscendMemory"]
        VectorDB["Qdrant"]
        Cache["Redis"]
        DB["PostgreSQL"]
    end

    Controller --> OrchestratorSvc
    OrchestratorSvc --> ContextAssembler
    OrchestratorSvc --> HistoryService
    OrchestratorSvc --> Executor
    ContextAssembler --> RAG
    ContextAssembler --> MemoryClient
    Executor --> Resolver
    Resolver --> ProviderProps
    RAG --> VectorDB
    HistoryService --> Cache
    HistoryService --> DB
    MemoryClient --> Memory
    Executor --> LLM
    Executor --> MCP
```

The component diagram shows the internal structure of the Orchestrator. The flow starts at `PromptController`, moves through `ChatOrchestratorService` for coordination, `ChatContextAssembler` for RAG/memory enrichment, and `ChatExecutor` for LLM invocation with dynamic provider resolution.
