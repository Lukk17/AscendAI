# AGENTS.md — AscendMemory

## Project Overview

AscendMemory is a semantic memory service that provides REST API and MCP server interfaces for storing, searching, and managing user-scoped memories. It uses mem0ai for memory operations backed by Qdrant vector database.

## Tech Stack

- **Language**: Python 3.11
- **Framework**: FastAPI + Uvicorn, FastMCP
- **Version**: 0.1.0
- **Docker Base**: `python:3.11-slim`

## Build & Run Commands

```bash
# Install dependencies
pip install -e .[dev]

# Run the server (port 7020)
uvicorn src.main:app --host 0.0.0.0 --port 7020 --reload

# Run tests
pytest

# Docker
docker build -t ascend-memory:latest .
```

## Architecture

**Dual API surface**:
- REST API: CRUD endpoints for memory operations under `/api/v1/memory/`
- MCP Server: FastMCP tools exposed via Streamable HTTP

**Key Endpoints**:
- `POST /api/v1/memory/insert` — Store a new memory
- `GET /api/v1/memory/search` — Semantic search across memories
- `DELETE /api/v1/memory` — Delete specific memory
- `POST /api/v1/memory/wipe` — Wipe all memories for a user

**Core Dependencies**:
- mem0ai (1.0.3) — Memory management library
- Qdrant (port 6333) — Vector database backend
- OpenAI-compatible API for embeddings (LM Studio or OpenAI)

## Environment Variables

- `OPENAI_API_KEY` — API key for embedding model
- `OPENAI_BASE_URL` — Embedding API endpoint (default: LM Studio at `http://host.docker.internal:1234/v1`)
- `API_PORT` — Service port (default: 7020)
- `QDRANT_HOST` / `QDRANT_PORT` — Qdrant connection
- `MEM0_EMBEDDING_MODEL` — Embedding model name (default: `text-embedding-nomic-embed-text-v2-moe`)
- `MEM0_COLLECTION_NAME` — Qdrant collection (default: `ascend_memory`)
- `MEM0_EMBEDDING_DIMS` — Embedding dimensions (default: 768)
- `MEM0_INFER_MEMORY` — Enable memory inference (default: false)

## Code Conventions

- Absolute imports from `src`
- Type hints (PEP 484) on all function signatures
- Pydantic models for request/response validation
- Async/await for I/O-bound operations
- User-scoped memory operations (all operations require a user_id)

## Relevant Skills

- `/python-patterns`, `/python-testing`
- `/api-design`, `/docker-patterns`
