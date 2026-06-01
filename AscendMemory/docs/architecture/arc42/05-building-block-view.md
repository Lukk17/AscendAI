# 5. Building Block View

---

### Package structure

```
AscendMemory/
├── src/
│   ├── main.py                        Entry point: FastAPI app factory, lifespan, warmup, /health
│   ├── api/
│   │   ├── rest/
│   │   │   └── rest_endpoints.py      REST router: /api/v1/memory/{insert,search,delete,wipe}
│   │   └── mcp/
│   │       └── mcp_server.py          FastMCP instance: memory_{insert,search,delete,wipe} tools
│   ├── config/
│   │   ├── config.py                  Settings (pydantic-settings), PROVIDER_CONFIGS dict
│   │   ├── logging_config.py          Colorlog formatter, uvicorn log config
│   │   └── startup_banner.py          ASCII banner, dependency probe, endpoint summary
│   └── service/
│       └── memory_client.py           AscendMemoryClient, per-provider singletons, monkey-patch
├── docs/
│   ├── CONFIGURATION.md               Environment-variable reference
│   └── architecture/                  This documentation tree
├── pyproject.toml                     Dependencies, dev extras
└── Dockerfile                         python:3.11-slim, port 7020
```

---

### Module responsibilities

#### `src/main.py`

Creates the FastAPI application via `create_app()`. The lifespan context starts a background warmup task
(`warmup_client`) and initialises the MCP ASGI app's own lifespan. The global `is_ready` flag is set by the warmup
task; `/health` returns `503` until it is `True`.

The MCP ASGI app is mounted last (`app.mount("/", mcp_asgi_app)`) to avoid capturing specific routes. The request
logging middleware skips `/health` to keep logs clean.

(`src/main.py:58-99`)

---

#### `src/api/rest/rest_endpoints.py`

FastAPI `APIRouter` prefixed at `/api/v1/memory`. Four handlers:

| Route | Method | Handler | Key behaviour |
| :---- | :----- | :------ | :------------ |
| `/search` | GET | `search_memory` | Delegates to `client.search()`. Returns `[]` on exception (logged). |
| `/insert` | POST | `insert_memory` | Accepts `text` or `messages`. Raises `400` on `ValueError`, `500` on other errors. |
| `/wipe` | POST | `wipe_memory` | Deletes all memories for `user_id` via `client.wipe_user()`. |
| `` (empty path) | DELETE | `delete_memory` | Deletes a single memory by `memory_id`. Raises `400` if `memory_id` is blank. |

All handlers resolve the provider via `settings.MEM0_DEFAULT_PROVIDER` when the caller omits the `provider` param.

(`src/api/rest/rest_endpoints.py`)

---

#### `src/api/mcp/mcp_server.py`

FastMCP instance named `"AscendMemory"`. Four tools mirror the REST surface exactly:

| Tool | REST equivalent |
| :--- | :-------------- |
| `memory_insert` | `POST /api/v1/memory/insert` (text-only; `messages` not exposed via MCP) |
| `memory_search` | `GET /api/v1/memory/search` |
| `memory_delete` | `DELETE /api/v1/memory` |
| `memory_wipe` | `POST /api/v1/memory/wipe` |

The MCP endpoint is at `/mcp`. The session lifecycle follows the MCP Streamable HTTP spec; a session ID is returned in
the `MCP-Session-Id` response header on `initialize`.

(`src/api/mcp/mcp_server.py`)

---

#### `src/config/config.py`

`PROVIDER_CONFIGS` is a module-level dict mapping provider name to embedding model, dimensions, Qdrant collection
name, and the `Settings` attribute names for base URL and API key. This is the single place to add a new provider.

`Settings` uses `pydantic-settings` with `env_file=".env"`. All fields have defaults; missing API keys produce a
`ValueError` at client init time (not at import time).

(`src/config/config.py`)

---

#### `src/service/memory_client.py`

`AscendMemoryClient` wraps `mem0.Memory`. Construction calls `Memory.from_config()` with the full Qdrant, LLM, and
embedder config built from `Settings` and `PROVIDER_CONFIGS`. The instance is cached in `_client_instances` by
provider name.

`get_memory_client(provider)` is the public factory. It resolves the provider name, checks the cache, and constructs
a new instance on first call. Both REST and MCP handlers call this function.

The monkey-patch on `OpenAILLM.generate_response` strips `response_format={"type":"json_object"}` for providers that
do not support it (notably LM Studio). This is applied at module import time.

`wipe_user` fetches all memories via `self.memory.get_all()` then deletes them individually. This is a workaround for
a mem0ai bug where `delete_all` wipes the entire collection.

(`src/service/memory_client.py`)
