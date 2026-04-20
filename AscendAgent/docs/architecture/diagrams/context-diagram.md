# C4 Context Diagram (Level 1)

```mermaid
graph TB
    User["👤 User / API Client"]

    subgraph "AscendAI System"
        AscendAgent["🧠 AscendAI AscendAgent"]
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

    User -->|"REST API"| AscendAgent
    AscendAgent -->|"Chat Completion"| LMStudio
    AscendAgent -->|"Chat Completion"| OpenAI
    AscendAgent -->|"Chat Completion"| Gemini
    AscendAgent -->|"Chat Completion"| Anthropic
    AscendAgent -->|"Chat Completion"| MiniMax
    AscendAgent -->|"MCP"| AudioScribe
    AscendAgent -->|"MCP"| Weather
    AscendAgent -->|"MCP"| WebSearch
    AscendAgent -->|"REST"| Memory
```

The AscendAgent is the central component — it receives user prompts, routes them to the selected AI provider, and invokes MCP tools as needed. AscendMemory provides semantic user context via direct REST.
