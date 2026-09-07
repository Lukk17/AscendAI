# AscendMemory Configuration

*Settings bind from the environment (or a local `.env` file) into the typed `Settings` class at
[../src/config/config.py](../src/config/config.py). Missing API keys only fail when the matching provider is actually
invoked, so a single deployment can serve `provider=lmstudio`, `provider=openai`, and `provider=gemini` side by side.*

---

### Service

| Variable                 | Default                                                            | Purpose                                                                  |
| :----------------------- | :----------------------------------------------------------------- | :----------------------------------------------------------------------- |
| `API_HOST`               | `0.0.0.0`                                                          | Bind address.                                                            |
| `API_PORT`               | `7020`                                                             | Service port.                                                            |
| `LOG_LEVEL`              | `INFO`                                                             | Log level.                                                               |

---

### Embedding providers

Each provider has its own base URL and API key, so the deployment can route requests by `provider` to the matching
backend. Embeddings drive both insertion and search, so the provider must stay consistent within a user's memory
scope.

| Variable                 | Default                                                            | Purpose                                                                  |
| :----------------------- | :----------------------------------------------------------------- | :----------------------------------------------------------------------- |
| `LMSTUDIO_BASE_URL`      | `http://localhost:1234/v1`                                         | LM Studio OpenAI-compatible URL.                                         |
| `LMSTUDIO_API_KEY`       | `sk_local`                                                         | Placeholder. LM Studio does not validate.                                |
| `OPENAI_BASE_URL`        | `https://api.openai.com/v1`                                        | Real OpenAI URL.                                                         |
| `OPENAI_API_KEY`         | (empty)                                                            | Required when `provider=openai` is invoked.                              |
| `GEMINI_BASE_URL`        | `https://generativelanguage.googleapis.com/v1beta/openai/`         | Gemini OpenAI-compatible URL.                                            |
| `GEMINI_API_KEY`         | (empty)                                                            | Required when `provider=gemini` is invoked.                              |
| `MEM0_LLM_MODEL`         | `meta-llama-3.1-8b-instruct`                                       | Model used by mem0 for fact extraction.                                  |
| `MEM0_DEFAULT_PROVIDER`  | `lmstudio`                                                         | Provider used when the request omits `provider`.                         |
| `MEM0_INFER_MEMORY`      | `false`                                                            | When `true`, mem0 infers memories instead of storing raw text.           |

---

### Qdrant

| Variable                 | Default                                                            | Purpose                                                                  |
| :----------------------- | :----------------------------------------------------------------- | :----------------------------------------------------------------------- |
| `QDRANT_HOST`            | `localhost`                                                        | Use `host.docker.internal` from inside Docker, or a managed Qdrant host. |
| `QDRANT_PORT`            | `6333`                                                             | Qdrant port.                                                             |

---

### Embedding provider to Qdrant collection mapping

The service routes each request to the correct Qdrant collection based on the `provider` parameter. Providers that
share vector dimensions share the same collection.

| Provider               | Embedding model                              | Dimensions | Qdrant collection      |
| :--------------------- | :------------------------------------------- | :--------- | :--------------------- |
| `lmstudio` (default)   | `text-embedding-nomic-embed-text-v2-moe`     | 768        | `ascend_memory_768`    |
| `openai`               | `text-embedding-3-small`                     | 1536       | `ascend_memory_1536`   |
| `gemini`               | `gemini-embedding-001`                       | 768        | `ascend_memory_768`    |
