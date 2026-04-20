# Prompt Processing Flow

## Sequence Diagram

```mermaid
sequenceDiagram
    actor User
    participant Controller as PromptController
    participant Chat as AscendChatService
    participant Context as ChatContextAssembler
    participant History as ChatHistoryService
    participant RAG as RagService
    participant MemClient as SemanticMemoryClient
    participant Executor as ChatExecutor
    participant Resolver as ChatModelResolver
    participant LLM as AI Provider
    participant MCP as MCP Tools
    participant MemExtract as SemanticMemoryExtractor

    User->>Controller: POST /api/v1/ai/prompt<br/>{prompt, provider, model, document, image}

    Controller->>Chat: process(prompt, userId, provider, model, ...)

    par Context Assembly
        Chat->>Context: assembleContext(userId, prompt)
        Context->>RAG: search(prompt, embeddingProvider)
        RAG-->>Context: relevant document fragments
        Context->>MemClient: searchMemory(userId, prompt, embeddingProvider)
        MemClient-->>Context: user facts & preferences
        Context-->>Chat: enriched system prompt
    and Load History
        Chat->>History: loadHistory(userId)
        History-->>Chat: recent conversation turns
    end

    Chat->>Executor: execute(systemPrompt, userMessage, history, provider, model)
    Executor->>Resolver: resolve(provider)
    Resolver-->>Executor: ChatModel instance

    Executor->>LLM: chat completion request

    opt Tool Use
        LLM-->>Executor: tool_call (e.g., web_search, transcribe)
        Executor->>MCP: invoke tool
        MCP-->>Executor: tool result
        Executor->>LLM: continue with tool result
    end

    LLM-->>Executor: final response
    Executor-->>Chat: response text + metadata

    par Post-Processing
        Chat->>History: saveHistory(userId, prompt, response)
    and Async Memory Extraction
        Chat->>MemExtract: extract(userId, prompt, provider)
        Note over MemExtract: Virtual Thread — low-cost model<br/>extracts user facts, POSTs to AscendMemory
    end

    Chat-->>Controller: response DTO
    Controller-->>User: JSON {content, metadata}
```

## Key Design Decisions

- **Parallel context assembly**: RAG search and memory search run concurrently
- **Per-request provider selection**: User chooses AI provider and model at prompt time
- **Transparent tool routing**: LLM decides when to use tools; Spring AI MCP handles dispatch
- **Async memory extraction**: Runs on a Virtual Thread after response, uses a cheap/fast model
- **Dual history store**: Redis for fast reads, PostgreSQL for persistence
