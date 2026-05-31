# AscendAgent Configuration

*Spring Boot settings bind from [src/main/resources/application.yaml](../src/main/resources/application.yaml) and
the environment. The tables below document the runtime knobs that vary per deployment.*

---

### Providers and enabled flags

Per-request provider selection happens through the `provider` and `model` form fields on `/api/v1/ai/prompt`. The
defaults below come from [application.yaml](../src/main/resources/application.yaml) and can be overridden via the
environment.

| Provider             | Type              | Default model                 | API key env var               | Enabled env var (default `true`)  |
| :------------------- | :---------------- | :---------------------------- | :---------------------------- | :-------------------------------- |
| `lmstudio` (default) | OpenAI-compatible | `meta-llama-3.1-8b-instruct`  | Not needed                    | `LMSTUDIO_ENABLED`                |
| `openai`             | OpenAI            | `gpt-4o`                      | `OPENAI_API_KEY`              | `OPENAI_ENABLED`                  |
| `gemini`             | OpenAI-compatible | `gemini-flash-latest`         | `GEMINI_API_KEY`              | `GEMINI_ENABLED`                  |
| `anthropic`          | Anthropic native  | `claude-sonnet-4-5`           | `ASCEND_ANTHROPIC_API_KEY`    | `ANTHROPIC_ENABLED`               |
| `minimax`            | Anthropic-compat  | `MiniMax-M2.7`                | `MINIMAX_API_KEY`             | `MINIMAX_ENABLED`                 |

The Anthropic key is namespaced `ASCEND_ANTHROPIC_API_KEY` so the agent's credentials don't collide with Claude Code's
own auth (which claims `ANTHROPIC_API_KEY` on the host).

---

### Per-purpose model defaults wired in YAML

These are the model IDs referenced in [application.yaml](../src/main/resources/application.yaml) for chat,
asynchronous memory extraction, and chat-history compaction. Any other model the provider accepts works at request
time via the `model` form field; these are the shipped defaults.

| Provider    | Chat default                  | Memory extraction               | History compaction default      |
| :---------- | :---------------------------- | :------------------------------ | :------------------------------ |
| OpenAI      | `gpt-4o`                      | `gpt-4o-mini`                   | `gpt-4o-mini`                   |
| Anthropic   | `claude-sonnet-4-5`           | `claude-3-5-haiku-20241022`     | `claude-haiku-4-5`              |
| Gemini      | `gemini-flash-latest`         | `gemini-flash-lite-latest`      | `gemini-flash-lite-latest`      |
| MiniMax     | `MiniMax-M2.7`                | `MiniMax-M2.7`                  | `MiniMax-M2.7`                  |
| LM Studio   | `meta-llama-3.1-8b-instruct`  | `meta-llama-3.1-8b-instruct`    | `meta-llama-3.1-8b-instruct`    |

---

### Environment variables

| Variable                     | Required           | Description                                                                                  |
| :--------------------------- | :----------------- | :------------------------------------------------------------------------------------------- |
| `LMSTUDIO_ENABLED`           | No                 | Enable LM Studio provider (default `true`).                                                  |
| `OPENAI_ENABLED`             | No                 | Enable OpenAI provider (default `true`).                                                     |
| `OPENAI_API_KEY`             | If OpenAI enabled  | OpenAI API key from [platform.openai.com](https://platform.openai.com).                      |
| `GEMINI_ENABLED`             | No                 | Enable Gemini provider (default `true`).                                                     |
| `GEMINI_API_KEY`             | If Gemini enabled  | Gemini key from [aistudio.google.com](https://aistudio.google.com).                          |
| `ANTHROPIC_ENABLED`          | No                 | Enable Anthropic provider (default `true`).                                                  |
| `ASCEND_ANTHROPIC_API_KEY`   | If Anthropic enabled | Anthropic key from [platform.claude.com](https://platform.claude.com/settings/keys).       |
| `MINIMAX_ENABLED`            | No                 | Enable MiniMax provider (default `true`).                                                    |
| `MINIMAX_API_KEY`            | If MiniMax enabled | MiniMax API key.                                                                             |
| `OPENAI_MODEL`               | No                 | Override default OpenAI model (default `gpt-4o`).                                            |
| `GEMINI_MODEL`               | No                 | Override default Gemini model (default `gemini-flash-latest`).                               |
| `ANTHROPIC_MODEL`            | No                 | Override default Anthropic model (default `claude-sonnet-4-5`).                              |
| `MINIMAX_MODEL`              | No                 | Override default MiniMax model (default `MiniMax-M2.7`).                                     |
| `LMSTUDIO_MODEL`             | No                 | Override default LM Studio model (default `meta-llama-3.1-8b-instruct`).                     |
| `EMBEDDING_PROVIDER`         | No                 | Embedding provider: `lmstudio` (default), `openai`, or `gemini`.                             |

---

### Embedding provider routing

The embedding provider controls which service generates RAG vectors and which Qdrant collection is used. Set per
request via the `embeddingProvider` form field, falling back to the `EMBEDDING_PROVIDER` env var (default
`lmstudio`).

| Embedding provider     | Model                                       | Dimensions | Requires                          |
| :--------------------- | :------------------------------------------ | :--------- | :-------------------------------- |
| `lmstudio` (default)   | `text-embedding-nomic-embed-text-v2-moe`    | 768        | LM Studio running locally         |
| `openai`               | `text-embedding-3-small`                    | 1536       | `OPENAI_API_KEY`                  |
| `gemini`               | `gemini-embedding-001`                      | 768        | `GEMINI_API_KEY`                  |

---

### Chat-provider to embedding-provider compatibility matrix

Incompatible combinations return HTTP 400. Switching between dimension groups (768 to 1536, or back) requires
re-ingesting documents into the target Qdrant collection.

| Embedding ->      | `lmstudio` (768) | `gemini` (768) | `openai` (1536) |
| :---------------- | :--------------- | :------------- | :-------------- |
| Chat: `lmstudio`  | Yes              | Yes            | No              |
| Chat: `gemini`    | Yes              | Yes            | Yes             |
| Chat: `anthropic` | Yes              | Yes            | Yes             |
| Chat: `minimax`   | Yes              | Yes            | Yes             |
| Chat: `openai`    | No               | No             | Yes             |

---

### Per-request usage examples

```text
POST /api/v1/ai/prompt
  prompt=...
  provider=anthropic           # chat provider
  embeddingProvider=lmstudio   # embedding provider (optional)
```

```text
POST /api/v1/ingestion/run
  embeddingProvider=openai     # ingest into the 1536-dim Qdrant collection
```

---

### Core Spring Boot settings

Beyond providers, these YAML keys cover the rest of the agent's deployment surface. Override via the standard Spring
Boot env-var binding (uppercase, dots and dashes to underscores).

- **`server.port`** (`9917`). Public REST port.
- **`app.embedding.provider`**. Active embedding backend (mirrors `EMBEDDING_PROVIDER`).
- **`app.s3.endpoint`** (`http://localhost:9070`). MinIO endpoint for ingestion.
- **`app.s3.public-endpoint`**. Host-reachable MinIO URL used in presigned `sources[].downloadUrl` payloads. In
  Docker, override to `http://host.docker.internal:9070`.
- **`app.s3.bucket`** (`knowledge-base`). Ingestion bucket. Auto-created at startup if missing.
- **`spring.datasource.url`**. Postgres connection for the metadata store.
- **`app.rag.enabled`**. Toggle the retrieval-gated soft-RAG path.
- **`app.rag.similarity-threshold`**. Lower bound for injecting retrieved context.
- **`app.ingestion.auto.enabled`** (`false`). Auto-poll the MinIO bucket on a schedule. Off by default to avoid
  embedding-cost surprises.
- **`spring.ai.mcp.client.*`**. MCP server URLs for Weather, AudioScribe, AscendWebSearch.

The Qdrant collections (`ascendai-768` and `ascendai-1536`) are auto-created at startup; the active collection comes
from the chosen embedding provider's vector dimensions.
