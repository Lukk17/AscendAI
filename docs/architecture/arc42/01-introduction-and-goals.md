# 1. Introduction and Goals

## Purpose

AscendAI is a modular AI orchestration platform built as a monorepo. It provides a unified REST API for interacting with multiple AI providers, extends LLM capabilities through external tool services via the Model Context Protocol (MCP), and implements a RAG pipeline with semantic memory for contextual conversations.

The system is designed for local-first development (LM Studio on localhost) with seamless switching to cloud AI providers (OpenAI, Anthropic, Gemini, MiniMax) per-request.

## Key Capabilities

- **Multi-provider AI routing** — per-request provider and model selection across 5 AI backends
- **Tool integration via MCP** — audio transcription, web search, weather data as discoverable tools
- **RAG pipeline** — document ingestion, vector storage, and similarity-based context injection
- **Semantic memory** — long-term user preference storage and retrieval across conversations
- **Document processing** — PDF, DOCX, image OCR through multiple processing backends

## Quality Goals

| Priority | Goal | Scenario |
|---|---|---|
| 1 | **Extensibility** | Adding an AI provider requires only a YAML config entry |
| 2 | **Provider Agnosticism** | Switching between local and cloud LLMs is a per-request parameter |
| 3 | **Modularity** | Each service is independently deployable, testable, and replaceable |
| 4 | **Local-first** | Full functionality without cloud API keys using LM Studio |
