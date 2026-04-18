# AGENTS.md

This file provides guidance to any AI coding agent (Claude Code, Kilo Code, OpenCode, Copilot, etc.) when working with code in this repository.

## What This Repo Is

AscendAI is a multi-module AI orchestration platform built with Spring AI and the Model Context Protocol (MCP). It routes user prompts to multiple AI providers (LM Studio, OpenAI, Gemini, Anthropic, MiniMax) with per-request selection, extends LLM capabilities with external tools via MCP, and provides a RAG pipeline with semantic memory.

## Monorepo Structure

| Module | Tech Stack | Port | Role |
|---|---|---|---|
| [Orchestrator](Orchestrator/AGENTS.md) | Java 21, Spring Boot 3.5.4, Gradle | 9917 | Main API gateway, multi-provider AI, RAG pipeline, MCP client |
| [AudioScribe](AudioScribe/AGENTS.md) | Python 3.11, FastAPI, FastMCP | 7017 | MCP server for audio transcription (Whisper, OpenAI, HF) |
| [AscendWebSearch](AscendWebSearch/AGENTS.md) | Python 3.12, FastAPI, FastMCP | 7021 | MCP server for web search and scraping via SearXNG |
| [AscendMemory](AscendMemory/AGENTS.md) | Python 3.11, FastAPI, FastMCP | 7020 | Semantic memory service using mem0ai + Qdrant |
| [WeatherMCP](WeatherMCP/AGENTS.md) | Java 21, Spring Boot 3.5.4, Gradle | 9998 | MCP server for weather data |
| [AudioForge](AudioForge/AGENTS.md) | Python 3.13, FastAPI | 7018 | Audio processing service (convert, silence removal) |
| [PaddleOCR](PaddleOCR/AGENTS.md) | Python 3.11, FastAPI, FastMCP | 7022 | OCR service using PaddleOCR |
| [OpenMemory](OpenMemory/AGENTS.md) | Docker wrapper | - | Deprecated wrapper for mem0 OpenMemory MCP (replaced by AscendMemory) |

## Infrastructure (docker-compose.yaml)

All services are deployed via `docker-compose.yaml` in the project root. Key infrastructure:

| Service | Port | Purpose |
|---|---|---|
| MinIO | 9070 / 9071 | S3-compatible object storage for RAG document ingestion |
| Qdrant | 6333 / 6334 | Vector database for RAG embeddings and semantic memory |
| Redis | 6379 | Chat history cache and session persistence |
| SearXNG | 9020 | Privacy-respecting meta search engine |
| FlareSolverr | 8191 | Cloudflare bypass proxy for web scraping |
| Docling Serve | 5001 | Document conversion service |
| Unstructured API | 9080 | Document parsing for RAG pipeline |
| PostgreSQL | 5432 | Persistent metadata, chat history, ingestion state |

## How to Build and Run

```bash
# 1. Start infrastructure
docker-compose up -d

# 2. Ensure PostgreSQL has database 'ascend_ai' (user: postgres, password: local)

# 3. Run the Orchestrator
cd Orchestrator && ./gradlew bootRun

# 4. Python services run via uvicorn or docker-compose
```

## Cross-Module Conventions

- **Java modules** (Orchestrator, WeatherMCP): Java 21, Spring Boot 3.5.4, Gradle, Spring AI 1.1.2.
- **Python modules** (AudioScribe, AscendWebSearch, AscendMemory, AudioForge, PaddleOCR): FastAPI + Uvicorn, pydantic for validation, FastMCP for MCP server mode.
- All services expose a `/health` endpoint for Docker healthchecks.
- All services are containerized with Dockerfiles and wired through `docker-compose.yaml`.
- MCP servers use SSE (Server-Sent Events) or Streamable HTTP for communication with the Orchestrator.

## Architecture Documentation

Full arc42 architecture docs, ADRs, and C4 diagrams are in `Orchestrator/docs/architecture/`.

## Proactive Skill Usage

Always invoke relevant project skills before starting implementation work. Skills provide domain-specific standards and patterns that must be followed. Available skills are in `.agents/skills/` (or `.claude/skills/` for Claude Code). Examples:

- `/code-reviewer` before reviewing code
- `/security-review` before auditing for vulnerabilities
- `/coding-standards` before writing new code
- `/springboot-patterns` or `/java-coding-standards` for Java/Spring Boot work
- `/python-patterns` or `/python-testing` for Python work
- `/docker-patterns` for Docker/compose changes
- `/api-design` for REST API design
- `/git-workflow` for branching and commit conventions
- `/database-migrations` for schema changes

## Implementation Plan

Before starting any non-trivial implementation work (bug fixes, features, refactors), create or completely overwrite `implementation_plan.md` in the project root. This file serves as the single source of truth for the current active plan.

**Required structure:**
1. **Context** section at the top — what problem is being solved and why
2. **Progress** section — a TODO checklist of all tasks. Update this in real-time:
   - Mark each task as done (`[x]`) immediately after completing it, before starting the next task
   - This section must always reflect the current state of work
3. **Plan** section — detailed implementation steps with file paths, code changes, and rationale
4. **Verification** section — how to test the changes end-to-end

Each new plan completely overwrites the previous `implementation_plan.md`. There is only ever one active plan.

## IDE Compatibility

Always output file edits using strict SEARCH/REPLACE blocks.
Ensure exact matching of existing indentation and formatting for the diff viewer to parse correctly.
