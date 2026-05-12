# AscendMemory

AscendMemory is a robust, persistent memory service for the AscendAI ecosystem. It leverages `mem0ai` to provide long-term semantic memory storage and retrieval, accessible via both a REST API and an MCP (Model Context Protocol) server.

---

## Table of Contents

*   [API Documentation](#api-documentation)
*   [Agent Skill](#agent-skill)
*   [Prerequisites](#prerequisites)
*   [Configuration (Environment Variables)](#configuration-environment-variables)
*   [Running the Service](#running-the-service)
    *   [Standard Python App](#running-as-a-standard-python-app-without-docker)
    *   [Docker](#running-with-docker-recommended)
*   [Making API Requests](#making-api-requests)
*   [MCP Server Mode](#mcp-server-mode)
*   [Troubleshooting](#troubleshooting)
*   [Dependencies](#dependencies)

---

## API Documentation

The REST API is self-documenting. While the server is running, you can access:

*   **Swagger UI**: [http://localhost:7020/docs](http://localhost:7020/docs)
*   **Redoc**: [http://localhost:7020/redoc](http://localhost:7020/redoc)

---

## Agent Skill

A drop-in skill is shipped at [`skills/ascend-memory/SKILL.md`](skills/ascend-memory/SKILL.md). Copy the `skills/ascend-memory/` directory into your agent's skills folder (`.claude/skills/`, `.agents/skills/`, `.kilocode/skills/`, etc.) and the agent will pick it up automatically.

The skill teaches the agent when to search memory before answering, when to insert new memories, how to scope every call by `user_id`, and when destructive operations like `/wipe` are appropriate. Base URL is left out (varies per environment) — the agent runtime is expected to provide it.

When you change endpoint shapes here, update the SKILL.md so downstream agents stay accurate.

---

## Prerequisites

*   **Python 3.11**
*   **OpenAI API Key** (for embedding generation by `mem0`)

---

## Configuration (Environment Variables)

The service is configured via environment variables. You can set them in your shell or use a `.env` file (if supported by your runner, though this project uses `pydantic-settings` which reads `.env` by default if present).

Each embedding provider has its own base URL and API key, so a single deployment can serve `provider=lmstudio`, `provider=openai`, and `provider=gemini` simultaneously, each routed to its real endpoint.

*   `LMSTUDIO_BASE_URL`: LM Studio OpenAI-compatible URL. Default: `http://localhost:1234/v1`.
*   `LMSTUDIO_API_KEY`: Placeholder key (LM Studio doesn't validate). Default: `sk_local`.
*   `OPENAI_BASE_URL`: Real OpenAI URL. Default: `https://api.openai.com/v1`.
*   `OPENAI_API_KEY`: Real OpenAI key. Required when `provider=openai` is invoked.
*   `GEMINI_BASE_URL`: Gemini OpenAI-compatible URL. Default: `https://generativelanguage.googleapis.com/v1beta/openai/`.
*   `GEMINI_API_KEY`: Gemini key. Required when `provider=gemini` is invoked.
*   `MEM0_LLM_MODEL`: Model ID for fact extraction. Default: `meta-llama-3.1-8b-instruct`.
*   `MEM0_DEFAULT_PROVIDER`: Provider used when the request omits `provider`. Default: `lmstudio`.
*   `MEM0_INFER_MEMORY`: If `true`, mem0 infers memories from chat messages instead of storing the raw text. Default: `false`.
*   `API_PORT`: Default `7020`.
*   `API_HOST`: Default `0.0.0.0`.
*   `LOG_LEVEL`: Default `INFO`.
*   `QDRANT_HOST`: `localhost` for native, `host.docker.internal` from inside Docker, or your managed Qdrant host.
*   `QDRANT_PORT`: Default `6333`.

Missing API keys only fail when the corresponding provider is actually invoked, so you can run with just the keys you need.

### Embedding Provider → Qdrant Collection Mapping

The service routes each request to the correct Qdrant collection based on the `provider` parameter:

| Provider | Embedding Model | Dimensions | Qdrant Collection |
|---|---|---|---|
| `lmstudio` (default) | `text-embedding-nomic-embed-text-v2-moe` | 768 | `ascend_memory_768` |
| `openai` | `text-embedding-3-small` | 1536 | `ascend_memory_1536` |
| `gemini` | `gemini-embedding-001` | 768 | `ascend_memory_768` |

Providers sharing the same dimensions (`lmstudio` and `gemini`) share the same Qdrant collection.

---

## Running the Service

### Running as a standard Python App (without Docker)

1.  **Create virtual environment**

    Linux/MacOS:
    ```shell
    python3 -m venv .venv
    ```

    Windows:
    ```powershell
    python -m venv .venv
    ```

2.  **Activate virtual environment**

    Linux/MacOS:
    ```shell
    source .venv/bin/activate
    ```

    Windows:
    ```powershell
    .\.venv\Scripts\activate
    ```

3.  **Install dependencies**

    ```shell
    pip install -e .[dev]
    ```
    *The `-e` flag stands for "editable". It allows you to modify the source code and see changes immediately without reinstalling the package.*

4.  **Run the Server**

    For local usage (e.g., with LM Studio), ensure the following are set:
    *   `OPENAI_API_KEY`: (Required)
    *   `OPENAI_BASE_URL`: (e.g., `http://localhost:1234/v1`)
    *   `MEM0_LLM_MODEL`: (e.g., `llama-3.2-1b-instruct`)

    **Note:** For local development, you can alternatively modify the default values directly in `src/core/config.py`.

    *Exporting variables (optional if set in system/config.py):*

    Linux/MacOS:
    ```shell
    export OPENAI_API_KEY="sk-..."
    export OPENAI_BASE_URL="http://localhost:1234/v1"
    export MEM0_LLM_MODEL="llama-3.2-1b-instruct"
    ```

    ```shell
    python src/main.py
    ```

    Windows:
    ```powershell
    $env:OPENAI_API_KEY="sk-..."
    $env:OPENAI_BASE_URL="http://localhost:1234/v1"
    $env:MEM0_LLM_MODEL="llama-3.2-1b-instruct"
    ```

    ```powershell
    python src/main.py
    ```

### Running with Docker (Recommended)

1.  **Build the Image**

    ```shell
    docker build -t ascend-memory:latest .
    ```

2.  **Run the Container**

    Linux/MacOS:
    ```shell
    docker run -d \
      --name ascend-memory \
      -p 7020:7020 \
      -e OPENAI_API_KEY="sk-..." \
      -e OPENAI_BASE_URL="http://host.docker.internal:1234/v1" \
      ascend-memory:latest
    ```

    Windows:
    ```powershell
    docker run -d `
      --name ascend-memory `
      -p 7020:7020 `
      -e OPENAI_API_KEY="sk-..." `
      -e OPENAI_BASE_URL="http://host.docker.internal:1234/v1" `
      ascend-memory:latest
    ```

3.  **Tagging and Pushing to Registry**

    Tag with a specific version (e.g., v0.0.1):

    ```shell
    docker tag ascend-ai-ascend-memory:latest lukk17/ascend-memory:v0.0.1
    ```

    Tag with latest:

    ```shell
    docker tag ascend-ai-ascend-memory:latest lukk17/ascend-memory:latest
    ```

    Push specific version:

    ```shell
    docker push lukk17/ascend-memory:v0.0.1
    ```

    Push latest:

    ```shell
    docker push lukk17/ascend-memory:latest
    ```

---

## Making API Requests

### 1. Insert Memory (Add)
Inserts a new memory or infers one from messages.

**Endpoint:** `POST /api/v1/memory/insert`

**Example:**
```bash
curl -X POST "http://localhost:7020/api/v1/memory/insert" \
     -H "Content-Type: application/json" \
     -d '{
           "user_id": "testUser1",
           "text": "The user prefers dark mode in all applications.",
           "provider": "lmstudio",
           "metadata": {"category": "preferences"}
         }'
```

The `provider` field is optional — omitting it uses the `MEM0_DEFAULT_PROVIDER` setting.

### 2. Search Memory

Retrieve relevant memories based on a semantic query.

**Endpoint:** `GET /api/v1/memory/search`

```bash
curl "http://localhost:7020/api/v1/memory/search?user_id=testUser1&query=dark%20mode&provider=lmstudio"
```

The `provider` query param is optional.

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

*   `memory_insert(user_id, text, provider?, metadata?)`: Add a memory. `provider` selects the embedding provider/collection (default: `MEM0_DEFAULT_PROVIDER`).
*   `memory_search(user_id, query, limit?, provider?)`: Search memories.
*   `memory_delete(memory_id, provider?)`: Delete a specific memory.
*   `memory_wipe(user_id, provider?)`: Wipe all user memories.

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

### Reinstalling python dependencies
Terminal in your activated virtual environment.

This creates a list of everything that's currently installed, uninstalls it, and then deletes the list file.

```shell
pip freeze > uninstall.txt
```

```shell
pip uninstall -y -r uninstall.txt
```

```shell
del uninstall.txt
```

Then reinstall:
```shell
pip install -e .[dev]
```
