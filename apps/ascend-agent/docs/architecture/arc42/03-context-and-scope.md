# 3. Context and Scope

---

### System context

```mermaid
graph TB
    User["User / Client"]
    AscendAiAgent["AscendAI ascend-ai-agent"]
    LMStudio["LM Studio<br/>(localhost:1234)"]
    OpenAI["OpenAI API"]
    Gemini["Gemini API<br/>(OpenAI-compatible)"]
    Anthropic["Anthropic API"]
    MiniMax["MiniMax API<br/>(Anthropic-compatible)"]
    AudioScribe["ascend-audio-scribe MCP<br/>(port 7017)"]
    Weather["ascend-weather-mcp<br/>(port 9998)"]
    WebHunter["ascend-web-hunter MCP<br/>(port 7021)"]
    Memory["AscendMemory<br/>(port 7020)"]

    User -->|"REST API<br/>POST /api/v1/ai/prompt"| AscendAiAgent
    AscendAiAgent -->|"OpenAI API"| LMStudio
    AscendAiAgent -->|"OpenAI API"| OpenAI
    AscendAiAgent -->|"OpenAI API"| Gemini
    AscendAiAgent -->|"Anthropic API"| Anthropic
    AscendAiAgent -->|"Anthropic API"| MiniMax
    AscendAiAgent -->|"MCP (Streamable HTTP)"| AudioScribe
    AscendAiAgent -->|"MCP (SSE)"| Weather
    AscendAiAgent -->|"MCP (Streamable HTTP)"| WebHunter
    AscendAiAgent -->|"REST API"| Memory
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
| S3-compatible storage | S3 API             | Outbound   | Document object storage, provided locally by a self-hosted emulator and by Amazon S3 in production. |
