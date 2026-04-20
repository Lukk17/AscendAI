# C4 Component Diagram (Level 3) — AscendAgent

```mermaid
graph TB
    subgraph "AscendAgent"
        subgraph "API Layer"
            Controller["PromptController<br/>/api/v1/ai/prompt"]
        end

        subgraph "Service Layer"
            AscendAgentSvc["AscendChatService"]
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

    Controller --> AscendAgentSvc
    AscendAgentSvc --> ContextAssembler
    AscendAgentSvc --> HistoryService
    AscendAgentSvc --> Executor
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

The component diagram shows the internal structure of the AscendAgent. The flow starts at `PromptController`, moves through `AscendChatService` for coordination, `ChatContextAssembler` for RAG/memory enrichment, and `ChatExecutor` for LLM invocation with dynamic provider resolution.
