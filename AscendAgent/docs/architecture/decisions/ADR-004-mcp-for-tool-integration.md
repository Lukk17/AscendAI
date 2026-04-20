# ADR-004: MCP for Tool Integration

## Status

Accepted

## Context

The AscendAgent needs to extend LLM capabilities with external tools (audio transcription, weather, web search). We need a standard protocol for tool discovery, invocation, and result handling.

Alternatives considered:
1. **Custom REST endpoints per tool** — N integrations, each with custom request/response mapping
2. **Spring AI Function Calling** — Java functions registered as beans
3. **Model Context Protocol (MCP)** — standardized tool discovery via `SyncMcpToolCallbackProvider`

## Decision

Use Spring AI's MCP client (`spring-ai-starter-mcp-client-webflux`) with Streamable HTTP transport. MCP services are registered in `application.yaml` under `spring.ai.mcp.client.streamable-http.connections`. Tool discovery happens at startup via `SyncMcpToolCallbackProvider`, and tools are attached to each `ChatClient` instance.

## Consequences

- **Positive**: Standardized protocol — any MCP-compliant service is automatically discovered
- **Positive**: Language-agnostic — MCP services can be Java (WeatherMCP), Python (AudioScribe, WebSearch), or any other language
- **Positive**: Adding a new tool = deploying a service + adding one URL to YAML
- **Negative**: Startup dependency on all MCP services being available
- **Negative**: Synchronous MCP calls block the virtual thread during tool execution
