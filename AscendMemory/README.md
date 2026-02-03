# AscendMemory

AscendMemory is a robust, persistent memory service for the AscendAI ecosystem. It leverages `mem0ai` to provide long-term semantic memory storage and retrieval, accessible via both a REST API and an MCP (Model Context Protocol) server.

---

## Table of Contents

*   [API Documentation](#api-documentation)
*   [Prerequisites](#prerequisites)
*   [Configuration (Environment Variables)](#configuration-environment-variables)
*   [Running the Service](#running-the-service)
    *   [Standard Python App](#running-as-a-standard-python-app-without-docker)
    *   [Docker](#running-with-docker-recommended)
*   [Making API Requests](#making-api-requests)
*   [MCP Server Mode](#mcp-server-mode)
*   [Dependencies](#dependencies)

---

## API Documentation

The REST API is self-documenting. While the server is running, you can access:

*   **Swagger UI**: [http://localhost:7020/docs](http://localhost:7020/docs)
*   **Redoc**: [http://localhost:7020/redoc](http://localhost:7020/redoc)

---

## Prerequisites

*   **Python 3.11**
*   **OpenAI API Key** (for embedding generation by `mem0`)

---

## Configuration (Environment Variables)

The service is configured via environment variables. You can set them in your shell or use a `.env` file (if supported by your runner, though this project uses `pydantic-settings` which reads `.env` by default if present).

*   `OPENAI_API_KEY`: **(Required)** Your OpenAI API key. Used by `mem0` for embeddings.
*   `OPENAI_BASE_URL`: **(Required)** Base URL for the LLM provider (e.g., `http://host.docker.internal:1234/v1` for local LM Studio).
*   `MEM0_LLM_MODEL`: **(Required for Local)** Exact model ID loaded in LM Studio (e.g., `llama-3.2-1b-instruct`). Defaults to `gpt-4o` if not set.
*   `API_PORT`: **(Optional)** Port to run the server on. Default: `7020`.
*   `API_HOST`: **(Optional)** Host to bind to. Default: `0.0.0.0`.
*   `LOG_LEVEL`: **(Optional)** Logging level. Default: `INFO`.
*   `QDRANT_HOST`: Hostname of the Qdrant vector database (use `localhost` for local dev, `qdrant` for docker).
*   `QDRANT_PORT`: Port for Qdrant (default: 6333).
*   `MEM0_EMBEDDING_MODEL`: Embedding model to use (default config uses `text-embedding-nomic-embed-text-v2-moe`).

---

## Running the Service

### Running as a standard Python App (without Docker)

1.  **Install Dependencies:**
    
    ```shell
    # Create virtual environment
    python -m venv .venv
    
    # Activate
    # Windows:
    .\.venv\Scripts\activate
    # Linux/Mac:
    source .venv/bin/activate
    
    # Install dependencies
    pip install .
    ```

2.  **Run the Server:**
    
    ```shell
    # Ensure OPENAI_API_KEY and MEM0_LLM_MODEL are set
    export OPENAI_API_KEY="sk-..."
    
    python src/main.py
    ```

### Running with Docker (Recommended)

1.  **Build the Image:**
    
    ```shell
    docker build -t ascend-memory:latest .
    ```

2.  **Run the Container:**
    
    ```shell
    docker run -d \
      --name ascend-memory \
      -p 7020:7020 \
      -e OPENAI_API_KEY="sk-..." \
      -e OPENAI_BASE_URL="http://host.docker.internal:1234/v1" \
      ascend-memory:latest
    ```

---

## Making API Requests

### 1. Upsert Memory (Add/Update)

Add a new memory for a user.

**Endpoint:** `POST /api/v1/memory/upsert`

```bash
curl -X POST "http://localhost:7020/api/v1/memory/upsert" \
     -H "Content-Type: application/json" \
     -d '{
           "user_id": "testUser1",
           "text": "The user prefers dark mode in all applications.",
           "metadata": {"category": "preferences"}
         }'
```

### 2. Search Memory

Retrieve relevant memories based on a semantic query.

**Endpoint:** `GET /api/v1/memory/search`

```bash
curl "http://localhost:7020/api/v1/memory/search?user_id=testUser1&query=dark%20mode"
```

### 3. Delete Memory

Delete a specific memory by its ID.

**Endpoint:** `DELETE /api/v1/memory`

```bash
curl -X DELETE "http://localhost:7020/api/v1/memory?memory_id=abc-123-def"
```

### 4. Wipe User Memory

Delete ALL memories for a specific user.

**Endpoint:** `POST /api/v1/memory/wipe`

```bash
curl -X POST "http://localhost:7020/api/v1/memory/wipe?user_id=testUser1"
```

---

## MCP Server Mode

The service exposes an MCP (Model Context Protocol) server at the `/mcp` endpoint (mounted via HTTP Streamable).

### Tool Configuration (e.g., for Claude Desktop)

```json
{
  "mcpServers": {
    "ascend-memory": {
      "type": "sse",
      "url": "http://localhost:7020/mcp"
    }
  }
}
```

### HTTP Streamable Requirements
If you are manually invoking the MCP endpoints (e.g., using `mcp_requests.http` or curl):
1.  **Endpoints**: The standard `http_app` exposes `/sse` (for connection) and `/messages` (for requests). However, configuration may expose `/mcp` handling both.
2.  **Headers**: You **MUST** include `Accept: application/json, text/event-stream` in your `POST` requests to satisfy the server's content negotiation.

### Available Tools

*   `memory_insert(user_id, text, metadata)`: Add a memory.
*   `memory_search(user_id, query, limit)`: Search memories.
*   `memory_delete(memory_id)`: Delete a specific memory.
*   `memory_wipe(user_id)`: Wipe all user memories.

**Testing MCP:**
A complete collection of example requests is available in the file:
`AscendMemory/mcp_requests.http`

### Troubleshooting

*   **406 Not Acceptable**: Missing proper `Accept` header. Ensure specific Accept types are sent rather than `*/*`.
*   **No models loaded (LM Studio)**: Ensure `MEM0_LLM_MODEL` in `config.py` matches the exact ID of the model loaded in your LM Studio instance.
*   **PermissionError (Qdrant)**: Ensure you are connecting to an external Qdrant instance (localhost/docker) and not trying to initialize an embedded one (default behavior overridden in `memory_client.py`).

---

## Dependencies

Dependency management is handled via `pyproject.toml`.

To add a new dependency:
1.  Add it to `pyproject.toml`.
2.  Reinstall: `pip install .`
