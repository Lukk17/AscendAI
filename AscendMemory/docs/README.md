# AscendMemory

*Semantic memory service: store, search, and manage user-scoped memories via REST and MCP.*

---

### What it is

AscendMemory provides a persistent, searchable memory layer for the AscendAI platform. Callers submit raw text or
conversation messages; the service embeds them with a configurable provider, stores the vectors in Qdrant, and returns
ranked matches on demand. The same four operations (insert, search, delete, wipe) are available over both a REST API
(`/api/v1/memory/`) and a FastMCP-over-Streamable-HTTP endpoint (`/mcp`).

The primary consumer is AscendAgent, which calls the REST API asynchronously after each chat turn to persist facts
extracted from the user's input. The MCP surface exists so that any MCP-capable agent can use memory directly without
an HTTP client.

---

### Quick start

Install dependencies:

```bash
pip install -e .[dev]
```

Start the server on port 7020:

```bash
uvicorn src.main:app --host 0.0.0.0 --port 7020 --reload
```

Build and run with Docker:

```bash
docker build -t ascend-memory:latest .
```

---

### External prerequisites

| Service | Default address | Purpose |
| :------ | :-------------- | :------ |
| Qdrant  | `localhost:6333` | Vector storage for embeddings |
| LM Studio (or OpenAI / Gemini) | `localhost:1234` | Embedding model |

The service starts and serves `/health` before the connection to Qdrant is established. The `/health` endpoint returns
`503` until the background warmup probe (retrying up to 60 times at 5-second intervals) confirms Qdrant is reachable.

---

### Docs map

| Document | Purpose |
| :------- | :------ |
| [docs/CONFIGURATION.md](CONFIGURATION.md) | Full environment-variable reference, provider-to-collection mapping |
| [docs/architecture/README.md](architecture/README.md) | Architecture index with reading paths, chapter summary, ADR table |
| [docs/architecture/arc42/](architecture/arc42/) | 12-chapter arc42 documentation |
| [docs/architecture/decisions/](architecture/decisions/) | Architecture Decision Records |
| [docs/architecture/diagrams/](architecture/diagrams/) | C4 container diagram |
