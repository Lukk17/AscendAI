# 3. Context and Scope

---

### System context

```mermaid
graph TB
    User["User / Client"]
    AscendAgent["AscendAI AscendAgent"]
    LMStudio["LM Studio<br/>(localhost:1234)"]
    OpenAI["OpenAI API"]
    Gemini["Gemini API<br/>(OpenAI-compatible)"]
    Anthropic["Anthropic API"]
    MiniMax["MiniMax API<br/>(Anthropic-compatible)"]
    AudioScribe["AudioScribe MCP<br/>(port 7017)"]
    Weather["Weather MCP<br/>(port 9998)"]
    WebSearch["AscendWebSearch MCP<br/>(port 7021)"]
    Memory["AscendMemory<br/>(port 7020)"]

    User -->|"REST API<br/>POST /api/v1/ai/prompt"| AscendAgent
    AscendAgent -->|"OpenAI API"| LMStudio
    AscendAgent -->|"OpenAI API"| OpenAI
    AscendAgent -->|"OpenAI API"| Gemini
    AscendAgent -->|"Anthropic API"| Anthropic
    AscendAgent -->|"Anthropic API"| MiniMax
    AscendAgent -->|"MCP (Streamable HTTP)"| AudioScribe
    AscendAgent -->|"MCP (SSE)"| Weather
    AscendAgent -->|"MCP (Streamable HTTP)"| WebSearch
    AscendAgent -->|"REST API"| Memory
```

---

### External interfaces

| Interface          | Protocol             | Direction  | Purpose                                                                  |
| :----------------- | :------------------- | :--------- | :----------------------------------------------------------------------- |
| User REST API      | HTTP / JSON          | Inbound    | Prompt submission with optional image / document / provider / model.     |
| LLM Provider APIs  | HTTP / JSON          | Outbound   | Chat completion requests (OpenAI-compatible or Anthropic).               |
| MCP Tool Services  | Streamable HTTP, SSE | Outbound   | Tool discovery and invocation (transcription, weather, web search).      |
| AscendMemory       | REST API             | Outbound   | Semantic memory storage and retrieval.                                   |
| Redis              | TCP                  | Outbound   | Chat history caching.                                                    |
| PostgreSQL         | TCP                  | Outbound   | Persistent metadata and chat history.                                    |
| Qdrant             | gRPC                 | Outbound   | Vector similarity search for RAG.                                        |
| MinIO              | S3 API               | Outbound   | Document object storage.                                                 |
