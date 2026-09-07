# 7. Deployment View

---

### Local development

```
Host machine
├── LM Studio  :1234   (embedding model: text-embedding-nomic-embed-text-v2-moe)
├── Qdrant     :6333   (external prerequisite, run separately)
└── AscendMemory :7020
    uvicorn src.main:app --host 0.0.0.0 --port 7020 --reload
```

Install dependencies:

```bash
pip install -e .[dev]
```

Run the server:

```bash
uvicorn src.main:app --host 0.0.0.0 --port 7020 --reload
```

The `.env` file (not committed) overrides any `Settings` default. At minimum, `QDRANT_HOST` must point to the running
Qdrant instance when Qdrant is on a different host.

---

### Docker

Build:

```bash
docker build -t ascend-memory:latest .
```

The image is `python:3.11-slim`. `src/` is copied first, then `pyproject.toml`, then `pip install .`. The container
listens on `0.0.0.0:7020` via `uvicorn src.main:app`.

(`Dockerfile:1-27`)

---

### Docker Compose (monorepo)

AscendMemory is declared in the monorepo root `docker-compose.yaml` under service `ascend-memory`. It connects to the
shared Qdrant container on the compose network. The relevant env vars to set in the compose file or a `.env`:

| Variable | Compose-typical value |
| :------- | :-------------------- |
| `QDRANT_HOST` | `qdrant` (service name on the compose network) |
| `QDRANT_PORT` | `6333` |
| `LMSTUDIO_BASE_URL` | `http://host.docker.internal:1234/v1` |

---

### Port map

| Endpoint | Port | Protocol |
| :------- | :--- | :------- |
| REST API | 7020 | HTTP |
| MCP (Streamable HTTP) | 7020 | HTTP (same port, path `/mcp`) |
| Health check | 7020 | HTTP `GET /health` |

---

### External prerequisites

| Service | Default address | Required? |
| :------ | :-------------- | :-------- |
| Qdrant  | `localhost:6333` | Yes. Without Qdrant the warmup probe never succeeds and `/health` stays `503`. |
| Embedding provider | `localhost:1234` (LM Studio default) | Yes for the default `lmstudio` provider. Other providers need their respective API keys set. |
