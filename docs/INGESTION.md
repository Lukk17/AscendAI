# Document Ingestion (RAG)

AscendAI ingests Markdown, PDF, and DOCX into Qdrant via MinIO. Markdown takes a fast path; other formats route through Unstructured and Docling before embedding.

---

## Two-step lifecycle

Ingestion is split into two stages on purpose.

1. **Upload** writes the file to MinIO under `obsidian/` (`.md`) or `documents/` (everything else). Nothing is embedded yet.
2. **Run** scans the bucket, embeds new or changed files into the matching Qdrant collection, and records state in `public.int_metadata_store` (PostgreSQL) so re-uploads are idempotent.

You trigger Run manually by default. There's also an auto-poller, but it's off out of the box (`app.ingestion.auto.enabled=false`) so the agent doesn't spend embedding tokens on every restart and so you're never surprised by background ingestion costs. Set `app.ingestion.auto.enabled=true` in `application.yaml` (or via env) to opt in.

---

## Option 1 — MinIO Console (Web UI)

1. Open [http://localhost:9071](http://localhost:9071).
2. Log in with default credentials: `admin` / `password`.
3. Click **Buckets** → select `knowledge-base`.
   - If it doesn't exist, AscendAgent creates it on startup, or you can create it manually.
4. Click **Object Browser** → **Upload** and pick file(s) or folder(s).
   - **Markdown** — `.md` files (best if exported from Obsidian).
   - **Documents** — PDFs, DOCX, etc. (processed via the Unstructured API).

Then trigger Run:

```bash
curl -X POST "http://localhost:9917/api/v1/ingestion/run?embeddingProvider=lmstudio"
```

```powershell
curl.exe -X POST "http://localhost:9917/api/v1/ingestion/run?embeddingProvider=lmstudio"
```

---

## Option 2 — CLI via AscendAgent

Upload files through the AscendAgent's API; the agent routes them to the correct folder (`obsidian/` or `documents/`).

```bash
curl -X POST -F "file=@notes.md" http://localhost:9917/api/v1/ingestion/upload
```

```powershell
curl.exe -X POST -F "file=@notes.md" http://localhost:9917/api/v1/ingestion/upload
```

Then trigger Run:

```bash
curl -X POST "http://localhost:9917/api/v1/ingestion/run?embeddingProvider=lmstudio"
```

```powershell
curl.exe -X POST "http://localhost:9917/api/v1/ingestion/run?embeddingProvider=lmstudio"
```

---

## What happens during Run

1. AscendAgent scans `knowledge-base` (optionally narrowed by `prefix=obsidian/` or `documents/`).
2. Markdown files are parsed in-process; other formats are sent to Unstructured / Docling for conversion.
3. Chunks are embedded with the requested provider (`lmstudio` and `gemini` → 768 dims, `openai` → 1536 dims) and stored in the matching Qdrant collection (`ascendai-768` or `ascendai-1536`).
4. State is recorded in `public.int_metadata_store` so an unchanged file is skipped on the next Run.

---

## Narrowing a Run with `prefix`

`POST /api/v1/ingestion/run` takes an optional `prefix` query parameter that limits the bucket scan to keys starting with that prefix.

- Omit it — scans the whole `knowledge-base` bucket (both `obsidian/` and `documents/`).
- `prefix=obsidian/` — only Markdown files (`.md` files land in this folder via upload routing).
- `prefix=documents/` — only PDFs, DOCX, and the rest.
- Any deeper prefix — e.g. `prefix=obsidian/notes/2026/` — matches that S3 path exactly. Handy for re-indexing one slice without touching the rest.

Folder names come from `app.ingestion.folders.obsidian` and `app.ingestion.folders.documents` in `application.yaml`. The upload endpoint routes `.md` to `obsidian/` and everything else to `documents/`.

---

## Auto-poller (opt-in)

If you'd rather not call Run by hand, enable the scheduler:

```yaml
app:
  ingestion:
    auto:
      enabled: true
```

It scans the bucket on a fixed interval (configurable in `application.yaml`) and ingests anything new. Off by default to keep startup fast and embedding spend predictable.

---

## Reset / re-ingest

To force re-processing of files, see [TROUBLESHOOTING.md → Resetting Ingestion History](TROUBLESHOOTING.md#3-resetting-ingestion-history-postgresql).
