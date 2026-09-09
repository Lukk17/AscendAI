# C4 Context Diagram (Level 1)

```mermaid
graph TB
    User["👤 User / API Client"]

    subgraph "AscendAI System"
        AscendAiAgent["🧠 AscendAI ascend-ai-agent"]
    end

    LMStudio["🖥️ LM Studio"]
    OpenAI["☁️ OpenAI"]
    Gemini["☁️ Google Gemini"]
    Anthropic["☁️ Anthropic"]
    MiniMax["☁️ MiniMax"]
    AudioScribe["🎙️ ascend-audio-scribe"]
    Weather["🌤️ ascend-weather-mcp"]
    WebHunter["🔍 ascend-web-hunter"]
    Memory["🧠 AscendMemory"]

    User -->|"REST API"| AscendAiAgent
    AscendAiAgent -->|"Chat Completion"| LMStudio
    AscendAiAgent -->|"Chat Completion"| OpenAI
    AscendAiAgent -->|"Chat Completion"| Gemini
    AscendAiAgent -->|"Chat Completion"| Anthropic
    AscendAiAgent -->|"Chat Completion"| MiniMax
    AscendAiAgent -->|"MCP"| AudioScribe
    AscendAiAgent -->|"MCP"| Weather
    AscendAiAgent -->|"MCP"| WebHunter
    AscendAiAgent -->|"REST"| Memory
```

The ascend-ai-agent is the central component. It receives user prompts, routes them to the selected AI provider, and
invokes MCP tools as needed. AscendMemory provides semantic user context via direct REST.
