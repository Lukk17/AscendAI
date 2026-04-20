# ADR-M002: MCP as the Standard Protocol for Tool Services

## Status

Accepted

## Context

The AscendAgent needs to invoke external tools (audio transcription, web search, weather, OCR) during LLM conversations. Options considered:
1. Direct REST API calls hardcoded in the AscendAgent
2. Plugin architecture with in-process extensions
3. Model Context Protocol (MCP) — an open standard for LLM tool integration

## Decision

Use MCP (Streamable HTTP transport) as the standard protocol for all tool services. Spring AI provides `SyncMcpToolCallbackProvider` for automatic tool discovery and invocation.

Tool services implement MCP servers using:
- **Java**: `spring-ai-starter-mcp-server-webmvc` (WeatherMCP)
- **Python**: `FastMCP` library (AudioScribe, AscendWebSearch, PaddleOCR)

Exception: AscendMemory uses REST API instead of MCP for memory operations (see AscendAgent ADR-003) because memory operations are tightly coupled to the prompt flow and need synchronous, predictable behavior rather than LLM-driven tool selection.

## Consequences

- **Positive**: LLM autonomously decides when to use tools — no hardcoded dispatch logic
- **Positive**: Adding new tools requires only a new MCP server + docker-compose entry
- **Positive**: Tools are discoverable at runtime — the AscendAgent doesn't need to know tool implementations
- **Negative**: MCP adds protocol overhead compared to direct REST calls
- **Negative**: Debugging tool calls requires understanding the MCP JSON-RPC layer
