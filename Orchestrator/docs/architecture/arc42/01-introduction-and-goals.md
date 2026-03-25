# 1. Introduction and Goals

## Purpose

AscendAI is a modular AI orchestration platform that routes user prompts to multiple AI providers (LM Studio, OpenAI, Gemini, Anthropic, MiniMax), enriches them with RAG-based context, chat history, and semantic memory, and extends LLM capabilities through MCP (Model Context Protocol) tool integrations.

## Stakeholders

| Role | Expectation |
|---|---|
| Developer/Owner | Full control over AI provider selection, local-first development with LM Studio, cloud deployment with commercial APIs |
| End User | Unified REST API for AI interaction with image/document upload, transparent provider switching |

## Quality Goals

| Priority | Quality Goal | Scenario |
|---|---|---|
| 1 | **Extensibility** | Adding a new AI provider requires only a YAML config entry — no code changes |
| 2 | **Provider Agnosticism** | Switching between local and cloud LLMs is a per-request parameter |
| 3 | **Modularity** | Each MCP service is independently deployable and testable |
| 4 | **Observability** | Every prompt logs provider, model, tools used, and response metadata |
