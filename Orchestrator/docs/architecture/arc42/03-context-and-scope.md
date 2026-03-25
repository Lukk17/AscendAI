# 3. Context and Scope

## System Context

```mermaid
graph TB
    User["👤 User / Client"]
    Orchestrator["🧠 AscendAI Orchestrator"]
    LMStudio["🖥️ LM Studio<br/>(localhost:1234)"]
    OpenAI["☁️ OpenAI API"]
    Gemini["☁️ Gemini API<br/>(OpenAI-compatible)"]
    Anthropic["☁️ Anthropic API"]
    MiniMax["☁️ MiniMax API<br/>(OpenAI-compatible)"]
    AudioScribe["🎙️ AudioScribe MCP<br/>(port 7017)"]
    Weather["🌤️ Weather MCP<br/>(port 9998)"]
    WebSearch["🔍 AscendWebSearch MCP<br/>(port 7021)"]
    Memory["🧠 AscendMemory<br/>(port 7020)"]

    User -->|"REST API<br/>POST /api/v1/ai/prompt"| Orchestrator
    Orchestrator -->|"OpenAI API"| LMStudio
    Orchestrator -->|"OpenAI API"| OpenAI
    Orchestrator -->|"OpenAI API"| Gemini
    Orchestrator -->|"Anthropic API"| Anthropic
    Orchestrator -->|"OpenAI API"| MiniMax
    Orchestrator -->|"MCP (Streamable HTTP)"| AudioScribe
    Orchestrator -->|"MCP (Streamable HTTP)"| Weather
    Orchestrator -->|"MCP (Streamable HTTP)"| WebSearch
    Orchestrator -->|"REST API"| Memory
```

## External Interfaces

| Interface | Protocol | Direction | Purpose |
|---|---|---|---|
| User REST API | HTTP/JSON | Inbound | Prompt submission with optional image/document/provider/model |
| LLM Provider APIs | HTTP/JSON | Outbound | Chat completion requests (OpenAI-compatible or Anthropic) |
| MCP Tool Services | Streamable HTTP | Outbound | Tool discovery and invocation (transcription, weather, web search) |
| AscendMemory | REST API | Outbound | Semantic memory storage and retrieval |
| Redis | TCP | Outbound | Chat history caching |
| PostgreSQL | TCP | Outbound | Persistent metadata and chat history |
| Qdrant | gRPC | Outbound | Vector similarity search for RAG |
| MinIO | S3 API | Outbound | Document object storage |
