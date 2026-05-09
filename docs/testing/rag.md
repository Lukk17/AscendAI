### RAG — End-to-End Test

Verifies that an uploaded document is ingested into Qdrant and that a later prompt retrieves and uses its content.

#### Pre-flight

```bash
curl http://localhost:9917/                  # AscendAgent
curl http://localhost:6333/collections       # Qdrant
curl http://localhost:9070/minio/health/live # MinIO
```

Active Qdrant collection depends on the embedding provider — `ascend_memory_768` for `lmstudio` / `gemini`, `ascend_memory_1536` for `openai`. Examples below assume `lmstudio`.

Use a fresh `X-User-Id` (e.g. `ragtest-001`).

#### Test 1 — Upload + ingest

Create a small Markdown file with a unique sentinel phrase the model can't know otherwise:

```bash
echo "The Ascend canary phrase is PURPLE-MOOSE-42." > /tmp/canary.md
```

Upload and run ingestion:

```bash
curl -X POST http://localhost:9917/api/ingestion/upload \
  -F "file=@/tmp/canary.md"

curl -X POST "http://localhost:9917/api/ingestion/run?prefix=obsidian/&embeddingProvider=lmstudio"
```

**Pass:** Upload returns `File uploaded to: obsidian/canary.md`. The `/run` response JSON shows `processed >= 1`. AscendAgent log includes `Ingested: obsidian/canary.md`.

#### Test 2 — Retrieve via prompt

```bash
curl -X POST http://localhost:9917/api/v1/ai/prompt \
  -H "X-User-Id: ragtest-001" \
  -F "prompt=What is the Ascend canary phrase?" \
  -F "provider=lmstudio" -F "embeddingProvider=lmstudio"
```

**Pass:** Response `content` contains `PURPLE-MOOSE-42`. AscendAgent log shows similarity-search hits being injected into the prompt context (look for the RAG retrieval log line referencing `obsidian/canary.md` or the embedded chunk).
