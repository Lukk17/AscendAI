### RAG — End-to-End Test

---

Verifies that uploaded documents (Markdown, PDF, DOCX) are ingested into Qdrant and that a later prompt retrieves and grounds an answer in their content. Each format goes through a different parser, so all three are tested independently with distinctive content.

### Pre-flight

---

Bash:

```bash
curl http://localhost:9917/
```

```bash
curl http://localhost:6333/collections
```

```bash
curl http://localhost:9070/minio/health/live
```

PowerShell:

```powershell
curl.exe http://localhost:9917/
```

```powershell
curl.exe http://localhost:6333/collections
```

```powershell
curl.exe http://localhost:9070/minio/health/live
```

Active Qdrant collection depends on the embedding provider: `ascendai-768` for `lmstudio` / `gemini`, `ascendai-1536` for `openai`. Examples below assume `lmstudio`. Use a fresh `X-User-Id` such as `ragtest-001`. Ingestion is a two-step flow — upload writes to MinIO, then a separate `/run` call scans the bucket and embeds new files. See [`docs/INGESTION.md`](../../../docs/INGESTION.md) for the lifecycle.

### Fixtures

---

The three fixtures live under `AscendAgent/e2e/fixtures/` and each holds different domain content so the tests verify retrieval independently:

- `markdown-canary.md` — a one-line canary file containing `The Ascend canary phrase is PURPLE-MOOSE-42.` Tests assert the model recalls this exact phrase from RAG, which proves real retrieval rather than a guess.
- `banana-price-poland.pdf` — a one-line price quote ("retail price of bananas in Poland in October 2026 was 6.49 PLN per kilogram...").
- `pierogi-recipe.docx` — Babcia Helena's pierogi recipe.

### Test 1 — Markdown ingest + recall

---

Upload (Bash):

```bash
curl -X POST http://localhost:9917/api/v1/ingestion/upload -F "file=@AscendAgent/e2e/fixtures/markdown-canary.md"
```

Upload (PowerShell):

```powershell
curl.exe -X POST http://localhost:9917/api/v1/ingestion/upload -F "file=@AscendAgent/e2e/fixtures/markdown-canary.md"
```

Run ingestion (Bash):

```bash
curl -X POST "http://localhost:9917/api/v1/ingestion/run?embeddingProvider=lmstudio"
```

Run ingestion (PowerShell):

```powershell
curl.exe -X POST "http://localhost:9917/api/v1/ingestion/run?embeddingProvider=lmstudio"
```

Recall via prompt (Bash):

```bash
curl -X POST http://localhost:9917/api/v1/ai/prompt -H "X-User-Id: ragtest-001" -F "prompt=What is the Ascend canary phrase?" -F "provider=lmstudio" -F "embeddingProvider=lmstudio"
```

Recall via prompt (PowerShell):

```powershell
curl.exe -X POST http://localhost:9917/api/v1/ai/prompt -H "X-User-Id: ragtest-001" -F "prompt=What is the Ascend canary phrase?" -F "provider=lmstudio" -F "embeddingProvider=lmstudio"
```

✅ **Pass:** Upload returns `File uploaded to: markdown/markdown-canary.md`. The `/run` response shows `processed >= 1`. The recall response contains `PURPLE-MOOSE-42`. Agent log shows the RAG retrieval log line referencing `markdown/markdown-canary.md`.

### Test 2 — PDF ingest + recall

---

Upload (Bash):

```bash
curl -X POST http://localhost:9917/api/v1/ingestion/upload -F "file=@AscendAgent/e2e/fixtures/banana-price-poland.pdf"
```

Upload (PowerShell):

```powershell
curl.exe -X POST http://localhost:9917/api/v1/ingestion/upload -F "file=@AscendAgent/e2e/fixtures/banana-price-poland.pdf"
```

Run ingestion (same `/run` call as Test 1 — it scans the whole bucket).

Recall via prompt (Bash):

```bash
curl -X POST http://localhost:9917/api/v1/ai/prompt -H "X-User-Id: ragtest-001" -F "prompt=What was the retail price of bananas in Poland in October 2026?" -F "provider=lmstudio" -F "embeddingProvider=lmstudio"
```

Recall via prompt (PowerShell):

```powershell
curl.exe -X POST http://localhost:9917/api/v1/ai/prompt -H "X-User-Id: ragtest-001" -F "prompt=What was the retail price of bananas in Poland in October 2026?" -F "provider=lmstudio" -F "embeddingProvider=lmstudio"
```

✅ **Pass:** Upload returns `File uploaded to: documents/banana-price-poland.pdf`. The recall response mentions `6.49 PLN`. PDF goes through Unstructured / Docling, so the agent log shows parser activity for this file. If the answer is generic ("around 5–7 PLN"), retrieval failed and the model fell back to training estimation.

### Test 3 — DOCX ingest + recall

---

Upload (Bash):

```bash
curl -X POST http://localhost:9917/api/v1/ingestion/upload -F "file=@AscendAgent/e2e/fixtures/pierogi-recipe.docx"
```

Upload (PowerShell):

```powershell
curl.exe -X POST http://localhost:9917/api/v1/ingestion/upload -F "file=@AscendAgent/e2e/fixtures/pierogi-recipe.docx"
```

Run ingestion (same `/run` call as before).

Recall via prompt (Bash):

```bash
curl -X POST http://localhost:9917/api/v1/ai/prompt -H "X-User-Id: ragtest-001" -F "prompt=How long should I rest the pierogi dough according to Babcia Helena's recipe?" -F "provider=lmstudio" -F "embeddingProvider=lmstudio"
```

Recall via prompt (PowerShell):

```powershell
curl.exe -X POST http://localhost:9917/api/v1/ai/prompt -H "X-User-Id: ragtest-001" -F "prompt=How long should I rest the pierogi dough according to Babcia Helena's recipe?" -F "provider=lmstudio" -F "embeddingProvider=lmstudio"
```

✅ **Pass:** Upload returns `File uploaded to: documents/pierogi-recipe.docx`. The recall response mentions `30 minutes` (the rest time from the recipe). Agent log shows DOCX parsing via Unstructured/Docling.
