# AGENTS.md — AscendAgent

## Project Overview

The AscendAgent is the central Spring Boot API gateway for the AscendAI platform. It routes user prompts to multiple AI providers with per-request model selection, implements a Soft-RAG pipeline with thresholded retrieval, integrates external tools via MCP, and manages chat history across Redis (short-term) and PostgreSQL (long-term).

## Tech Stack

- **Language**: Java 21
- **Framework**: Spring Boot 3.5.4
- **Build Tool**: Gradle (`build.gradle.kts`)
- **Key Libraries**: Spring AI 1.1.2, Qdrant client 1.11.0, CommonMark 0.21.0, PDFBox 3.0.4, Liquibase

## Build & Run Commands

```bash
# Build
./gradlew build

# Run (port 9917)
./gradlew bootRun

# Run tests
./gradlew test

# Run a single test class
./gradlew test --tests "com.lukk.ascend.ai.agent.service.SomeTest"

# Docker
docker build -t ascend-agent:latest .
```

## Architecture

**Package structure**: `com.lukk.ascend.ai.agent`

| Package | Purpose |
|---|---|
| `config/` | Spring configuration, API client beans, properties binding |
| `config/api/` | AI provider client configurations (OpenAI, Anthropic, Gemini, MiniMax, LM Studio) |
| `config/properties/` | `@ConfigurationProperties` classes |
| `controller/` | REST controllers (chat, ingestion, web) |
| `dto/` | Request/response DTOs |
| `exception/` | Global exception handlers |
| `memory/` | Semantic memory integration (calls AscendMemory REST API) |
| `model/` | Domain models |
| `repository/` | Spring Data JPA repositories |
| `service/` | Core business logic (chat, RAG, provider routing) |
| `service/ingestion/` | Document ingestion pipeline (MinIO, Markdown, Unstructured) |
| `service/ingestion/client/` | External service clients (Docling, Unstructured API) |
| `service/memory/` | Memory service orchestration |
| `util/` | Utility classes |

**Configuration**: `src/main/resources/application.yaml` — all provider URLs, model names, Qdrant settings, MinIO credentials, Redis, PostgreSQL.

**Database migrations**: Liquibase changelogs in `src/main/resources/db/changelog/`.

**Architecture docs**: `docs/architecture/` contains full arc42 documentation, ADRs, and C4 diagrams.

## Supported AI Providers

- **OpenAI**: gpt-5.4, gpt-5.1, gpt-5-mini, gpt-4o, gpt-4o-mini
- **Anthropic**: claude-opus-4-6, claude-sonnet-4-6, claude-sonnet-4-5, claude-haiku-4-5
- **Gemini**: gemini-3.1-pro, gemini-3.1-flash, gemini-2.5-pro, gemini-2.5-flash
- **MiniMax**: MiniMax-M2.5, MiniMax-M2.5-highspeed, MiniMax-M2.1
- **LM Studio**: meta-llama-3.1-8b-instruct (default, local)

## Key Dependencies

- PostgreSQL (port 5432, database `ascend_ai`) — external prerequisite
- Redis (port 6379) for chat history cache — external prerequisite
- Qdrant (port 6333) for vector embeddings — external prerequisite
- MinIO (port 9070) for document storage — external prerequisite
- AscendMemory (port 7020) for semantic memory REST API
- MCP servers: AudioScribe (7017), WeatherMCP (9998), AscendWebSearch (7021)

## Code Conventions

- Follow standard Spring Boot layered architecture: Controller → Service → Repository
- Use `@ConfigurationProperties` for external configuration binding
- Use constructor injection (no field injection)
- DTOs for API boundaries; domain models internally
- Liquibase for all database schema changes
- ADRs in `docs/architecture/decisions/` for significant architectural choices
- `ChatResponseContentResolver` handles multi-block responses from thinking models (see ADR-005)

## Relevant Skills

- `/springboot-patterns`, `/springboot-security`, `/springboot-tdd`, `/springboot-verification`
- `/java-coding-standards`, `/jpa-patterns`
- `/api-design`, `/database-migrations`
- `/docker-patterns`, `/deployment-patterns`
