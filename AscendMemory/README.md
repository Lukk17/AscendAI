# AscendMemory

A persistent semantic memory service for the AscendAI ecosystem. It uses `mem0ai` for long-term memory storage and
retrieval, exposed as both a REST API and an MCP (Model Context Protocol) server on the same port.

---

### Table of Contents

- [API Documentation](#api-documentation)
- [Agent Skill](#agent-skill)
- [Prerequisites](#prerequisites)
- [Configuration](#configuration)
- [Running the Service](#running-the-service)
- [Making API Requests](#making-api-requests)
- [MCP Server Mode](#mcp-server-mode)
- [Troubleshooting](#troubleshooting)
- [Dependencies](#dependencies)
- [Docs map](#docs-map)

---

### API Documentation

The REST API is self-documenting. While the server is running:

- **Swagger UI**: [http://localhost:7020/docs](http://localhost:7020/docs)
- **Redoc**: [http://localhost:7020/redoc](http://localhost:7020/redoc)

---

### Agent Skill

A drop-in skill ships at [skills/ascend-memory/SKILL.md](skills/ascend-memory/SKILL.md). Copy
[skills/ascend-memory/](skills/ascend-memory/) into your agent's skills folder (`.claude/skills/`, `.agents/skills/`,
`.opencode/skills/`, etc.) and the agent will pick it up automatically.

The skill teaches the agent when to search memory before answering, when to insert new memories, how to scope every
call by `user_id`, and when destructive operations like `/wipe` are appropriate. Base URL is left out (varies per
environment); the agent runtime is expected to provide it.

When you change endpoint shapes here, update the SKILL.md so downstream agents stay accurate.

---

### Prerequisites

- **Python 3.11**
- **Qdrant** running on `6333` (local or managed)
- **OpenAI API key** (only when invoking `provider=openai`, for embedding generation by `mem0`)

---

### Configuration

Settings live in [src/config/config.py](src/config/config.py) (pydantic-settings, reads `.env` automatically).
Each embedding provider has its own base URL and API key, so a single deployment can serve `provider=lmstudio`,
`provider=openai`, and `provider=gemini` simultaneously, each routed to its real endpoint.

| Variable                 | Default                                                            | Purpose                                                                  |
| :----------------------- | :----------------------------------------------------------------- | :----------------------------------------------------------------------- |
| `LMSTUDIO_BASE_URL`      | `http://localhost:1234/v1`                                         | LM Studio OpenAI-compatible URL                                          |
| `LMSTUDIO_API_KEY`       | `sk_local`                                                         | Placeholder (LM Studio doesn't validate)                                 |
| `OPENAI_BASE_URL`        | `https://api.openai.com/v1`                                        | Real OpenAI URL                                                          |
| `OPENAI_API_KEY`         | (empty)                                                            | Required when `provider=openai` is invoked                               |
| `GEMINI_BASE_URL`        | `https://generativelanguage.googleapis.com/v1beta/openai/`         | Gemini OpenAI-compatible URL                                             |
| `GEMINI_API_KEY`         | (empty)                                                            | Required when `provider=gemini` is invoked                               |
| `MEM0_LLM_MODEL`         | `meta-llama-3.1-8b-instruct`                                       | Model used by mem0 for fact extraction                                   |
| `MEM0_DEFAULT_PROVIDER`  | `lmstudio`                                                         | Provider used when the request omits `provider`                          |
| `MEM0_INFER_MEMORY`      | `false`                                                            | When `true`, mem0 infers memories instead of storing raw text            |
| `API_PORT`               | `7020`                                                             | Service port                                                             |
| `API_HOST`               | `0.0.0.0`                                                          | Bind address                                                             |
| `LOG_LEVEL`              | `INFO`                                                             | Log level                                                                |
| `QDRANT_HOST`            | `localhost`                                                        | `host.docker.internal` from inside Docker, or your managed Qdrant host   |
| `QDRANT_PORT`            | `6333`                                                             | Qdrant port                                                              |

Missing API keys only fail when the corresponding provider is actually invoked. Run with just the keys you need.

#### Embedding Provider to Qdrant Collection mapping

The service routes each request to the correct Qdrant collection based on the `provider` parameter:

| Provider               | Embedding model                              | Dimensions | Qdrant collection      |
| :--------------------- | :------------------------------------------- | :--------- | :--------------------- |
| `lmstudio` (default)   | `text-embedding-nomic-embed-text-v2-moe`     | 768        | `ascend_memory_768`    |
| `openai`               | `text-embedding-3-small`                     | 1536       | `ascend_memory_1536`   |
| `gemini`               | `gemini-embedding-001`                       | 768        | `ascend_memory_768`    |

Providers sharing the same dimensions (`lmstudio` and `gemini`) share the same Qdrant collection.

---

### Running the Service

#### As a standard Python app

**1. Create a virtual environment.**

Bash:

```bash
python3 -m venv .venv
```

PowerShell:

```powershell
python -m venv .venv
```

**2. Activate it.**

Bash:

```bash
source .venv/bin/activate
```

PowerShell:

```powershell
.\.venv\Scripts\activate
```

**3. Install dependencies.** The `-e` flag installs in editable mode so source edits show up without reinstall.

Bash:

```bash
pip install -e .[dev]
```

PowerShell:

```powershell
pip install -e .[dev]
```

**4. Run the server.** Defaults in [src/config/config.py](src/config/config.py) point at local LM Studio. Override
through env vars for any other provider.

Bash:

```bash
export OPENAI_API_KEY="sk-..."
```

```bash
export OPENAI_BASE_URL="http://localhost:1234/v1"
```

```bash
python src/main.py
```

PowerShell:

```powershell
$env:OPENAI_API_KEY="sk-..."
```

```powershell
$env:OPENAI_BASE_URL="http://localhost:1234/v1"
```

```powershell
python src/main.py
```

#### With Docker (recommended)

**1. Build the image.**

Bash:

```bash
docker build -t ascend-memory:latest .
```

PowerShell:

```powershell
docker build -t ascend-memory:latest .
```

**2. Run the container.**

Bash:

```bash
docker run -d --name ascend-memory -p 7020:7020 -e OPENAI_API_KEY="sk-..." -e OPENAI_BASE_URL="http://host.docker.internal:1234/v1" ascend-memory:latest
```

PowerShell:

```powershell
docker run -d --name ascend-memory -p 7020:7020 -e OPENAI_API_KEY="sk-..." -e OPENAI_BASE_URL="http://host.docker.internal:1234/v1" ascend-memory:latest
```

**3. Tag and push to a registry (optional).**

Bash:

```bash
docker tag ascend-memory:latest lukk17/ascend-memory:v0.0.1
```

```bash
docker push lukk17/ascend-memory:v0.0.1
```

```bash
docker tag ascend-memory:latest lukk17/ascend-memory:latest
```

```bash
docker push lukk17/ascend-memory:latest
```

PowerShell:

```powershell
docker tag ascend-memory:latest lukk17/ascend-memory:v0.0.1
```

```powershell
docker push lukk17/ascend-memory:v0.0.1
```

```powershell
docker tag ascend-memory:latest lukk17/ascend-memory:latest
```

```powershell
docker push lukk17/ascend-memory:latest
```

---

### Making API Requests

#### 1. Insert memory

Inserts a new memory, or infers one from chat messages when `MEM0_INFER_MEMORY=true`.

**Endpoint:** `POST /api/v1/memory/insert`

Bash:

```bash
curl -X POST "http://localhost:7020/api/v1/memory/insert" -H "Content-Type: application/json" -d '{"user_id":"testUser1","text":"The user prefers dark mode in all applications.","provider":"lmstudio","metadata":{"category":"preferences"}}'
```

PowerShell:

```powershell
Invoke-RestMethod -Uri http://localhost:7020/api/v1/memory/insert -Method Post -ContentType "application/json" -Body '{"user_id":"testUser1","text":"The user prefers dark mode in all applications.","provider":"lmstudio","metadata":{"category":"preferences"}}'
```

The `provider` field is optional. Omitting it uses the `MEM0_DEFAULT_PROVIDER` setting.

#### 2. Search memory

Retrieve relevant memories based on a semantic query.

**Endpoint:** `GET /api/v1/memory/search`

Bash:

```bash
curl "http://localhost:7020/api/v1/memory/search?user_id=testUser1&query=dark%20mode&provider=lmstudio"
```

PowerShell:

```powershell
Invoke-RestMethod -Uri "http://localhost:7020/api/v1/memory/search?user_id=testUser1&query=dark%20mode&provider=lmstudio"
```

The `provider` query param is optional.

#### 3. Delete memory

Delete a specific memory by its ID.

**Endpoint:** `DELETE /api/v1/memory`

Bash:

```bash
curl -X DELETE "http://localhost:7020/api/v1/memory?memory_id=abc-123-def"
```

PowerShell:

```powershell
Invoke-RestMethod -Uri "http://localhost:7020/api/v1/memory?memory_id=abc-123-def" -Method Delete
```

#### 4. Wipe user memory

Delete ALL memories for a specific user.

**Endpoint:** `POST /api/v1/memory/wipe`

Bash:

```bash
curl -X POST "http://localhost:7020/api/v1/memory/wipe?user_id=testUser1"
```

PowerShell:

```powershell
Invoke-RestMethod -Uri "http://localhost:7020/api/v1/memory/wipe?user_id=testUser1" -Method Post
```

---

### MCP Server Mode

The service exposes an MCP server at `/mcp` (mounted via HTTP Streamable).

#### Tool configuration (e.g. for Claude Desktop)

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

#### HTTP Streamable requirements

When invoking the MCP endpoints manually (e.g. via [mcp_requests.http](mcp_requests.http) or curl):

1. **Endpoints.** The standard `http_app` exposes `/sse` (for connection) and `/messages` (for requests).
   Configuration may expose `/mcp` handling both.
2. **Headers.** You MUST include `Accept: application/json, text/event-stream` in `POST` requests to satisfy the
   server's content negotiation.

#### Available tools

- `memory_insert(user_id, text, provider?, metadata?)`. Add a memory. `provider` selects the embedding provider and
  collection (default: `MEM0_DEFAULT_PROVIDER`).
- `memory_search(user_id, query, limit?, provider?)`. Search memories.
- `memory_delete(memory_id, provider?)`. Delete a specific memory.
- `memory_wipe(user_id, provider?)`. Wipe all user memories.

#### Testing MCP

A collection of example requests lives at [mcp_requests.http](mcp_requests.http) (use the VS Code REST Client
extension).

---

### Startup readiness banner

On startup, [src/config/startup_banner.py](src/config/startup_banner.py) emits a single multi-line INFO log entry
with an ANSI Shadow `ASCEND MEMORY` banner, access URLs, the active embedding provider, a 2 s Qdrant probe, and the
list of observability and REST endpoints. Shared convention with every other long-running service in the repo. See
[.agents/skills/coding-standards/SKILL.md](../.agents/skills/coding-standards/SKILL.md).

---

### Troubleshooting

- **406 Not Acceptable.** Missing proper `Accept` header. Send specific Accept types instead of `*/*`.
- **No models loaded (LM Studio).** Ensure `MEM0_LLM_MODEL` matches the exact ID of the model loaded in your LM
  Studio instance.
- **PermissionError (Qdrant).** Ensure you're connecting to an external Qdrant instance (localhost or Docker)
  and not trying to initialise an embedded one (default behaviour overridden in
  [src/service/memory_client.py](src/service/memory_client.py)).

#### Reinstalling Python dependencies

Terminal in your activated virtual environment. Lists installed packages, uninstalls them, removes the list, then
reinstalls.

Bash:

```bash
pip freeze > uninstall.txt
```

```bash
pip uninstall -y -r uninstall.txt
```

```bash
rm uninstall.txt
```

```bash
pip install -e .[dev]
```

PowerShell:

```powershell
pip freeze > uninstall.txt
```

```powershell
pip uninstall -y -r uninstall.txt
```

```powershell
Remove-Item uninstall.txt
```

```powershell
pip install -e .[dev]
```

---

### Dependencies

Dependency management lives in [pyproject.toml](pyproject.toml). Add a new dependency there, then reinstall with
`pip install -e .[dev]`.

---

### Docs map

| File                                                                       | What's in it                                                        |
| :------------------------------------------------------------------------- | :------------------------------------------------------------------ |
| [AGENTS.md](AGENTS.md)                                                     | Module-level instructions for AI coding agents.                     |
| [src/config/config.py](src/config/config.py)                               | Settings, provider routing, defaults.                               |
| [src/service/memory_client.py](src/service/memory_client.py)               | mem0 client wiring, per-provider routing.                           |
| [src/api/rest/rest_endpoints.py](src/api/rest/rest_endpoints.py)           | REST endpoints under `/api/v1/memory/*`.                            |
| [src/api/mcp/mcp_server.py](src/api/mcp/mcp_server.py)                     | FastMCP tool definitions.                                           |
| [mcp_requests.http](mcp_requests.http)                                     | Example MCP requests for the VS Code REST Client extension.         |
| [skills/ascend-memory/SKILL.md](skills/ascend-memory/SKILL.md)             | Drop-in agent skill for downstream agents.                          |
| [../README.md](../README.md)                                               | Monorepo overview, architecture, ports.                             |
| [../docs/architecture/README.md](../docs/architecture/README.md)           | Monorepo architecture, ADRs.                                        |
