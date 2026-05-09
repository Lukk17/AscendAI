# Troubleshooting

Operational recipes for resetting state, clearing caches, and recovering from common issues across MinIO, Qdrant, PostgreSQL, and Redis.

---

## Data and Persistence

MinIO runs as an external prerequisite. Data persistence depends on your MinIO installation (local or cloud-managed S3).

---

## 1. MinIO: "Bucket already exists" or "Access Denied"

If you need to completely reset MinIO state or delete a bucket that is stuck, you **cannot** use the Web UI in recent versions. Use the command line inside the Docker container.

**Force delete a bucket via Docker:**

1. Open a terminal.
2. Verify the running container name (usually `minio`):
   ```bash
   docker ps
   ```
3. Exec into the MinIO container:
   ```bash
   docker exec -it minio /bin/sh
   ```
4. Configure the `mc` client (aliases `local` to your server):
   ```bash
   mc alias set local http://localhost:9000 admin password
   ```
5. Force delete the bucket:
   ```bash
   mc rb --force local/knowledge-base
   ```

---

## 2. Qdrant: Managing Vector Data

The system uses Qdrant for two distinct features:

1. **RAG (AscendAgent)**: Uses `ascendai-768` (Gemini/LM Studio) or `ascendai-1536` (OpenAI) depending on active embedding dimensions.
2. **Semantic Memory (AscendMemory / Mem0)**: Uses `ascend_memory_768` (lmstudio/gemini, 768 dims) or `ascend_memory_1536` (openai, 1536 dims).

**Delete entire collection (reset memory):**

```bash
curl -X DELETE "http://localhost:6333/collections/ascendai-768"
curl -X DELETE "http://localhost:6333/collections/ascendai-1536"
curl -X DELETE "http://localhost:6333/collections/ascend_memory_768"
curl -X DELETE "http://localhost:6333/collections/ascend_memory_1536"
```

**Granular deletion (remove specific file):**

```bash
curl -X POST "http://localhost:6333/collections/ascendai/points/delete" \
     -H "Content-Type: application/json" \
     -d '{
       "filter": {
         "must": [
           { "key": "metadata.source", "match": { "value": "kierunki.md" } }
         ]
       }
     }'
```

**List all collections:**

```bash
curl http://localhost:6333/collections
```

**Visualize data (Qdrant Dashboard):**

- URL: [http://localhost:6333/dashboard](http://localhost:6333/dashboard)
- Browse collections, view stored vectors, verify ingestion visually.

---

## 3. Resetting Ingestion History (PostgreSQL)

To force re-processing of files, remove their entries from the metadata store.

- **Database**: `ascend_ai`
- **Schema**: `public`
- **Table**: `int_metadata_store`

**Option A — Clear history for a single file:**

```sql
DELETE FROM public.int_metadata_store
WHERE metadata_key LIKE '%test.md';
```

_(Keys often include prefixes like `s3-metadata` or `local-fs-metadata`.)_

**Option B — Clear ALL history (full reset):**

```sql
TRUNCATE TABLE public.int_metadata_store;
```

After running either command, restart the AscendAgent.

---

## 4. Resetting Chat History (Redis & PostgreSQL)

The AscendAgent keeps chat context in two places:

1. **Short-term (Redis)** — active context window sent to the LLM.
2. **Long-term (PostgreSQL)** — archived interactions for auditing and analytics.

**Clear active context (Redis):**

```bash
redis-cli
FLUSHALL
```

**Clear archived history (PostgreSQL):**

```sql
DELETE FROM chat_history;
```