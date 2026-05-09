# Document Ingestion (RAG)

AscendAI ingests Markdown, PDF, and DOCX into Qdrant via MinIO. Markdown takes a fast path; other formats route through Unstructured and Docling before embedding.

---

## Option 1 — MinIO Console (Web UI)

1. Open [http://localhost:9071](http://localhost:9071).
2. Log in with default credentials: `admin` / `password`.
3. Click **Buckets** → select `knowledge-base`.
   - If it doesn't exist, AscendAgent creates it on startup, or you can create it manually.
4. Click **Object Browser** → **Upload** and pick file(s) or folder(s).
   - **Markdown** — `.md` files (best if exported from Obsidian).
   - **Documents** — PDFs, DOCX, etc. (processed via the Unstructured API).

## Option 2 — CLI via AscendAgent

Upload files through the AscendAgent's API; the agent routes them to the correct folder (`obsidian/` or `documents/`):

```bash
curl -X POST -F "file=@notes.md" http://localhost:9917/api/ingestion/upload
```

Make sure the file exists in your current directory.

---

## What happens after upload

1. AscendAgent detects new objects in the `knowledge-base` bucket.
2. Markdown files are parsed in-process; other formats are sent to Unstructured / Docling for conversion.
3. Chunks are embedded with the configured embedding provider (LM Studio / Gemini → 768 dims, OpenAI → 1536 dims) and stored in the matching Qdrant collection (`ascendai-768` or `ascendai-1536`).
4. Ingestion state is tracked in `public.int_metadata_store` (PostgreSQL) so re-uploads are idempotent.

---

## Reset / re-ingest

To force re-processing of files, see [TROUBLESHOOTING.md → Resetting Ingestion History](TROUBLESHOOTING.md#3-resetting-ingestion-history-postgresql).
