# 6. Runtime View

## Prompt Processing Flow

```mermaid
sequenceDiagram
    participant User
    participant Controller as PromptController
    participant AscendAgent as ChatAscendAgentService
    participant Context as ChatContextAssembler
    participant History as ChatHistoryService
    participant Executor as ChatExecutor
    participant Resolver as ChatModelResolver
    participant LLM as AI Provider

    User->>Controller: POST /api/v1/ai/prompt
    Controller->>AscendAgent: prompt(text, image, doc, userId, provider, model)
    AscendAgent->>Context: buildSystemMessage(userId, prompt)
    Context->>Context: RAG search + semantic memory
    Context-->>AscendAgent: enriched system message
    AscendAgent->>Context: buildUserMessage(prompt, document)
    Context-->>AscendAgent: user text
    AscendAgent->>History: loadHistory(userId)
    History-->>AscendAgent: message list
    AscendAgent->>Executor: execute(userId, system, user, history, image, provider, model)
    Executor->>Resolver: resolve(provider)
    Resolver-->>Executor: ChatModel
    Executor->>Executor: build ChatClient with model + MCP tools
    Executor->>LLM: chat completion request
    LLM-->>Executor: response (may include tool calls)
    Executor-->>AscendAgent: AiResponse
    AscendAgent->>History: saveHistory(userId, text, response)
    AscendAgent-->>Controller: AiResponse
    Controller-->>User: 200 OK + JSON
```

## MCP Tool Call Flow

```mermaid
sequenceDiagram
    participant Executor as ChatExecutor
    participant LLM as AI Provider
    participant MCP as MCP Tool Service

    Executor->>LLM: prompt with tool definitions
    LLM-->>Executor: tool_call(name, args)
    Executor->>MCP: invoke tool (Streamable HTTP)
    MCP-->>Executor: tool result
    Executor->>LLM: continue with tool result
    LLM-->>Executor: final response
```

## REST API: Request / Response Examples

### Prompt Request

```
POST /api/v1/ai/prompt
Content-Type: multipart/form-data
X-User-Id: user1

prompt=What is the weather in Warsaw?
provider=lmstudio
model=meta-llama-3.1-8b-instruct
```

### Prompt Response

```json
{
  "content": "The current weather in Warsaw is 15°C with partly cloudy skies.",
  "metadata": {
    "model": "meta-llama-3.1-8b-instruct",
    "usage": {
      "promptTokens": 245,
      "completionTokens": 32,
      "totalTokens": 277
    },
    "toolsUsed": ["weather_get_current"]
  }
}
```

### Provider Selection Examples

```
# Use default provider (lmstudio)
prompt=Hello

# Use Gemini with specific model
prompt=Summarize this&provider=gemini&model=gemini-2.5-pro

# Use Anthropic with default model
prompt=Explain quantum computing&provider=anthropic
```
