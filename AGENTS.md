# AGENTS.md

This file provides guidance to any AI coding agent (Claude Code, Kilo Code, OpenCode, Copilot, etc.) when working with code in this repository.

## What This Repo Is

AscendAI is a multi-module AI orchestration platform built with Spring AI and the Model Context Protocol (MCP). It routes user prompts to multiple AI providers (LM Studio, OpenAI, Gemini, Anthropic, MiniMax) with per-request selection, extends LLM capabilities with external tools via MCP, and provides a RAG pipeline with semantic memory.

## Monorepo Structure

| Module | Tech Stack | Port | Role |
|---|---|---|---|
| [AscendAgent](AscendAgent/AGENTS.md) | Java 21, Spring Boot 3.5.4, Gradle | 9917 | Main API gateway, multi-provider AI, RAG pipeline, MCP client |
| [AudioScribe](AudioScribe/AGENTS.md) | Python 3.11, FastAPI, FastMCP | 7017 | MCP server for audio transcription (Whisper, OpenAI, HF) |
| [AscendWebSearch](AscendWebSearch/AGENTS.md) | Python 3.12, FastAPI, FastMCP | 7021 | MCP server for web search and scraping via SearXNG |
| [AscendMemory](AscendMemory/AGENTS.md) | Python 3.11, FastAPI, FastMCP | 7020 | Semantic memory service using mem0ai + Qdrant |
| [WeatherMCP](WeatherMCP/AGENTS.md) | Java 21, Spring Boot 3.5.4, Gradle | 9998 | MCP server for weather data |
| [PaddleOCR](PaddleOCR/AGENTS.md) | Python 3.11, FastAPI, FastMCP | 7022 | OCR service using PaddleOCR |

## External Prerequisites

These services must be running before starting docker-compose. In production they map to managed cloud services (e.g., AWS ElastiCache, Qdrant Cloud, S3).

| Service | Port(s) | Purpose |
|---|---|---|
| PostgreSQL | 5432 | Persistent metadata, chat history, ingestion state |
| Redis | 6379 | Chat history cache and session persistence |
| Qdrant | 6333 / 6334 | Vector database for RAG embeddings and semantic memory |
| MinIO | 9070 / 9071 | S3-compatible object storage for RAG document ingestion |

## Docker Compose Services (docker-compose.yaml)

Application and support services deployed via `docker-compose.yaml`:

| Service | Port | Purpose |
|---|---|---|
| SearXNG | 9020 | Privacy-respecting meta search engine |
| FlareSolverr | 8191 | Cloudflare bypass proxy for web scraping |
| Docling Serve | 5001 | Document conversion service |
| Unstructured API | 9080 | Document parsing for RAG pipeline |

## How to Build and Run

```bash
# 1. Ensure external prerequisites are running (PostgreSQL :5432, Redis :6379, Qdrant :6333, MinIO :9070)

# 2. Start application and support services
docker-compose up -d

# 3. Ensure PostgreSQL has database 'ascend_ai' (user: postgres, password: local)

# 4. Run the AscendAgent
cd AscendAgent && ./gradlew bootRun

# 5. Python services run via uvicorn or docker-compose
```

## Cross-Module Conventions

- **Java modules** (AscendAgent, WeatherMCP): Java 21, Spring Boot 3.5.4, Gradle, Spring AI 1.1.4.
- **Python modules** (AudioScribe, AscendWebSearch, AscendMemory, PaddleOCR): FastAPI + Uvicorn, pydantic for validation, FastMCP for MCP server mode.
- All services expose a `/health` endpoint for Docker healthchecks.
- All services are containerized with Dockerfiles and wired through `docker-compose.yaml`.
- MCP servers use SSE (Server-Sent Events) or Streamable HTTP for communication with the AscendAgent.

## Architecture Documentation

- **Monorepo-level**: System overview, service interactions, deployment, ADRs — in `docs/architecture/`
- **AscendAgent internals**: Component diagrams, internal arc42, module-specific ADRs — in `AscendAgent/docs/architecture/`

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

Every implementation plan must include a **Relevant Skills** section listing all skills that should be loaded before implementing. This ensures the agent always knows which domain-specific standards apply to the work at hand.

## Implementation Plan

Before starting any non-trivial implementation work (bug fixes, features, refactors), create or completely overwrite `implementation_plan.md` in the project root. This file serves as the single source of truth for the current active plan.

**Required structure:**
1. **Context** section at the top — what problem is being solved and why
2. **Progress** section — a TODO checklist of all tasks. Update this in real-time:
   - Mark each task as done (`[x]`) immediately after completing it, before starting the next task
   - This section must always reflect the current state of work
3. **Plan** section — detailed implementation steps with file paths, code changes, and rationale
4. **Relevant Skills** section — list all skills that must be loaded before implementation begins
5. **Verification** section — how to test the changes end-to-end

Each new plan completely overwrites the previous `implementation_plan.md`. There is only ever one active plan.

**Approval gate:** After writing `implementation_plan.md`, **always wait for user approval** before starting implementation. The user will review the plan in the markdown file and may add comments or request changes. Do NOT begin modifying source code, configs, or any project files until the user explicitly approves the plan. This is the most important rule in the workflow.

## IDE Compatibility

Always output file edits using strict SEARCH/REPLACE blocks.
Ensure exact matching of existing indentation and formatting for the diff viewer to parse correctly.
