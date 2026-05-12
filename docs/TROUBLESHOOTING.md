# Troubleshooting

Operational recipes for resetting state, clearing caches, and recovering from common issues across MinIO, Qdrant, PostgreSQL, and Redis.

---

## Data and persistence

MinIO, Qdrant, PostgreSQL, and Redis all run as external prerequisites. Data persistence depends on how you've deployed them (native, docker run, managed cloud).

---

## 1. MinIO: "Bucket already exists" or "Access Denied"

If MinIO state is stuck, the Web UI in recent versions can't force-delete a bucket. Use the `mc` CLI inside the running container.

Find the container name (usually `minio`):

```bash
docker ps
```

```powershell
docker ps
```

Open a shell inside it:

```bash
docker exec -it minio /bin/sh
```

```powershell
docker exec -it minio /bin/sh
```

Configure `mc` against your local MinIO, then force-delete the bucket. From inside the container:

```bash
mc alias set local http://localhost:9000 admin password
```

```bash
mc rb --force local/knowledge-base
```

---

## 2. Qdrant: managing vector data

Qdrant holds two distinct collection groups:

- **RAG (AscendAgent)** — `ascendai-768` (lmstudio / gemini) or `ascendai-1536` (openai), depending on the active embedding provider.
- **Semantic memory (AscendMemory / mem0)** — `ascend_memory_768` (lmstudio / gemini, 768 dims) or `ascend_memory_1536` (openai, 1536 dims).

Switching providers between dimension groups means the new collection starts empty. Re-run ingestion (`POST /api/v1/ingestion/run?embeddingProvider=...`) to populate it.

### Delete a whole collection

Bash:

```bash
curl -X DELETE "http://localhost:6333/collections/ascendai-768"
```

```bash
curl -X DELETE "http://localhost:6333/collections/ascendai-1536"
```

```bash
curl -X DELETE "http://localhost:6333/collections/ascend_memory_768"
```

```bash
curl -X DELETE "http://localhost:6333/collections/ascend_memory_1536"
```

PowerShell:

```powershell
curl.exe -X DELETE "http://localhost:6333/collections/ascendai-768"
```

```powershell
curl.exe -X DELETE "http://localhost:6333/collections/ascendai-1536"
```

```powershell
curl.exe -X DELETE "http://localhost:6333/collections/ascend_memory_768"
```

```powershell
curl.exe -X DELETE "http://localhost:6333/collections/ascend_memory_1536"
```

### Granular deletion (one source file)

Bash:

```bash
curl -X POST "http://localhost:6333/collections/ascendai-768/points/delete" -H "Content-Type: application/json" -d '{"filter":{"must":[{"key":"metadata.source","match":{"value":"notes.md"}}]}}'
```

PowerShell:

```powershell
curl.exe -X POST "http://localhost:6333/collections/ascendai-768/points/delete" -H "Content-Type: application/json" -d '{\"filter\":{\"must\":[{\"key\":\"metadata.source\",\"match\":{\"value\":\"notes.md\"}}]}}'
```

### List all collections

Bash:

```bash
curl http://localhost:6333/collections
```

PowerShell:

```powershell
curl.exe http://localhost:6333/collections
```

### Visualize data (Qdrant Dashboard)

Open [http://localhost:6333/dashboard](http://localhost:6333/dashboard). Browse collections, view stored vectors, verify ingestion visually.

---

## 3. Resetting ingestion history (PostgreSQL)

To force re-processing of files, remove their entries from the metadata store.

- Database: `ascend_ai`
- Schema: `public`
- Table: `int_metadata_store`

Clear history for one file:

```sql
DELETE FROM public.int_metadata_store WHERE metadata_key LIKE '%test.md';
```

Keys often include prefixes like `s3-metadata` or `local-fs-metadata`.

Clear all history (full reset):

```sql
TRUNCATE TABLE public.int_metadata_store;
```

After running either, restart AscendAgent.

---

## 4. Resetting chat history (Redis + PostgreSQL)

AscendAgent keeps chat context in two places:

- **Short-term (Redis)** — active context window sent to the LLM.
- **Long-term (PostgreSQL)** — archived interactions for audit and analytics.

Clear active context (Redis):

Bash:

```bash
redis-cli FLUSHALL
```

PowerShell:

```powershell
redis-cli FLUSHALL
```

Clear archived history (PostgreSQL):

```sql
DELETE FROM chat_history;
```
