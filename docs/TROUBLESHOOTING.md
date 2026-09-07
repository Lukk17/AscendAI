# Troubleshooting

Operational recipes for resetting state, clearing caches, and recovering from common issues across the object store,
Qdrant, PostgreSQL, and Redis.

---

### Data and persistence

The object store, Qdrant, PostgreSQL, and Redis all run as external prerequisites. Data persistence depends on how you
deployed them (native, `docker run`, managed cloud).

---

### 1. Object store: resetting the `knowledge-base` bucket

The local object store runs on `http://localhost:9070`, an S3-compatible emulator with a web UI
on `http://localhost:9071`. It answers the S3 REST API without authentication, so every recipe below is a plain `curl`.
There is no client to install and no container to shell into.

One rule applies to everything in this section. Always name the bucket literally, and only ever name a bucket this
repository owns, meaning `knowledge-base` or `e2e-fixtures`. The same object-store instance backs other projects on this
machine, so a command that sweeps buckets instead of naming one destroys data AscendAI never created.

Check the object store is up.

Bash:

```bash
curl -fsS http://localhost:9070/_floci/health
```

PowerShell:

```powershell
curl.exe -fsS http://localhost:9070/_floci/health
```

Expect HTTP 200 and a JSON body carrying `"s3":"running"`. This is the only liveness path the object store
serves.

List what the bucket currently holds. Every `<Key>` element in the returned `ListBucketResult` is one object you have to
remove before the bucket itself will go.

Bash:

```bash
curl -fsS "http://localhost:9070/knowledge-base?list-type=2"
```

PowerShell:

```powershell
curl.exe -fsS "http://localhost:9070/knowledge-base?list-type=2"
```

Narrow the listing to one folder prefix when the bucket is large. The response echoes the filter back in a `<Prefix>`
element, so you can see the filter that produced the keys.

Bash:

```bash
curl -fsS "http://localhost:9070/knowledge-base?list-type=2&prefix=documents/"
```

PowerShell:

```powershell
curl.exe -fsS "http://localhost:9070/knowledge-base?list-type=2&prefix=documents/"
```

Delete one object, using the key exactly as the listing printed it. Repeat once per key. A key that is already gone
also returns HTTP 204, so re-running the step is safe.

Bash:

```bash
curl -fsS -X DELETE "http://localhost:9070/knowledge-base/documents/pierogi-recipe.docx"
```

PowerShell:

```powershell
curl.exe -fsS -X DELETE "http://localhost:9070/knowledge-base/documents/pierogi-recipe.docx"
```

Delete the emptied bucket. S3 refuses to drop a bucket that still holds objects, so HTTP 409 with
`<Code>BucketNotEmpty</Code>` means the listing above had a key you missed.

Bash:

```bash
curl -sS -X DELETE "http://localhost:9070/knowledge-base"
```

PowerShell:

```powershell
curl.exe -sS -X DELETE "http://localhost:9070/knowledge-base"
```

Expect HTTP 204. Then restart ascend-ai-agent: `BucketInitConfig` recreates `knowledge-base` empty during startup, so you
never have to create it by hand.

Confirm the bucket came back after the restart.

Bash:

```bash
curl -fsS "http://localhost:9070/knowledge-base?list-type=2"
```

PowerShell:

```powershell
curl.exe -fsS "http://localhost:9070/knowledge-base?list-type=2"
```

Expect a `ListBucketResult` with `<KeyCount>0</KeyCount>`. HTTP 404 with `<Code>NoSuchBucket</Code>` means the agent has
not recreated it yet, which points at a failed startup rather than at the object store.

---

### 2. Qdrant: managing vector data

Qdrant holds two distinct collection groups:

- **RAG (ascend-ai-agent).** `ascendai-768` (lmstudio / gemini) or `ascendai-1536` (openai), depending on the active
  embedding provider.
- **Semantic memory (AscendMemory / mem0).** `ascend_memory_768` (lmstudio / gemini, 768 dims) or
  `ascend_memory_1536` (openai, 1536 dims).

Switching providers between dimension groups means the new collection starts empty. Re-run ingestion
(`POST /api/v1/ingestion/run?embeddingProvider=...`) to populate it.

#### Delete a whole collection

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

#### Granular deletion (one source file)

Bash:

```bash
curl -X POST "http://localhost:6333/collections/ascendai-768/points/delete" -H "Content-Type: application/json" -d '{"filter":{"must":[{"key":"metadata.source","match":{"value":"notes.md"}}]}}'
```

PowerShell:

```powershell
curl.exe -X POST "http://localhost:6333/collections/ascendai-768/points/delete" -H "Content-Type: application/json" -d '{\"filter\":{\"must\":[{\"key\":\"metadata.source\",\"match\":{\"value\":\"notes.md\"}}]}}'
```

#### List all collections

Bash:

```bash
curl http://localhost:6333/collections
```

PowerShell:

```powershell
curl.exe http://localhost:6333/collections
```

#### Visualize data (Qdrant Dashboard)

Open [http://localhost:6333/dashboard](http://localhost:6333/dashboard). Browse collections, view stored vectors,
verify ingestion visually.

---

### 3. Resetting ingestion history (PostgreSQL)

To force re-processing of files, remove their entries from the metadata store.

- **Database:** `ascend_ai`
- **Schema:** `public`
- **Table:** `int_metadata_store`

Clear history for one file:

```sql
DELETE FROM public.int_metadata_store WHERE metadata_key LIKE '%test.md';
```

Keys often include prefixes like `s3-metadata` or `local-fs-metadata`.

Clear all history (full reset):

```sql
TRUNCATE TABLE public.int_metadata_store;
```

After running either, restart ascend-ai-agent.

---

### 4. Resetting chat history (Redis + PostgreSQL)

ascend-ai-agent keeps chat context in two places:

- **Short-term (Redis).** Active context window sent to the LLM.
- **Long-term (PostgreSQL).** Archived interactions for audit and analytics.

Clear active context (Redis).

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

---

### See also

- [../README.md](../README.md). Monorepo overview, ports, prerequisites.
- [DEPLOYMENT.md](DEPLOYMENT.md). Compose recipes, image publishing.
- [INGESTION.md](INGESTION.md). Document ingestion lifecycle.
