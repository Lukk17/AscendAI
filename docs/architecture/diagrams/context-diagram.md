# C4 Context Diagram (Level 1)

```mermaid
graph TB
    User["👤 User / API Client"]

    subgraph "AscendAI System"
        Orchestrator["🧠 AscendAI Orchestrator"]
    end

    LMStudio["🖥️ LM Studio"]
    OpenAI["☁️ OpenAI"]
    Gemini["☁️ Google Gemini"]
    Anthropic["☁️ Anthropic"]
    MiniMax["☁️ MiniMax"]
    AudioScribe["🎙️ AudioScribe"]
    Weather["🌤️ WeatherMCP"]
    WebSearch["🔍 AscendWebSearch"]
    Memory["🧠 AscendMemory"]

    User -->|"REST API"| Orchestrator
    Orchestrator -->|"Chat Completion"| LMStudio
    Orchestrator -->|"Chat Completion"| OpenAI
    Orchestrator -->|"Chat Completion"| Gemini
    Orchestrator -->|"Chat Completion"| Anthropic
    Orchestrator -->|"Chat Completion"| MiniMax
    Orchestrator -->|"MCP"| AudioScribe
    Orchestrator -->|"MCP"| Weather
    Orchestrator -->|"MCP"| WebSearch
    Orchestrator -->|"REST"| Memory
```

The Orchestrator is the central component — it receives user prompts, routes them to the selected AI provider, and invokes MCP tools as needed. AscendMemory provides semantic user context via direct REST.
