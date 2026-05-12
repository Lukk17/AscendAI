# RAG — manual e2e test

## What this verifies

Uploaded documents (Markdown, PDF, DOCX) are ingested into MinIO and Qdrant, and a later prompt retrieves and grounds an answer in their content. Each format goes through a different parser, so all three are exercised with distinctive content. Covers:

- **Bug 7** — RAG similarity threshold at search time (the recorded regression: threshold `0.75` was too strict for OpenAI embeddings on short queries; default is now `0.5`)
- **Bug 9** — HTTP-upload deduplication (re-running ingestion doesn't duplicate points)
- **Bug 15** — ingestion controller URL prefix alignment
- **Bug 16** — folder rename `obsidian/` → `markdown/`
- **Bug 18** — multi-file ingestion upload (one request, multiple `file` parts)

> **Regression note.** With OpenAI embeddings the default similarity threshold of `0.75` produced empty retrievals for short questions — the agent log would show `RAG Context Injected: NO`. Threshold was lowered to `0.5`; verify the new default by inspecting `application.yaml` if results look thin.

## Prerequisites

- `docker compose up -d` stack up (Docling Serve 5001, Unstructured 9080)
- AscendAgent on 9917, Qdrant on 6333, MinIO on 9070
- A chat provider; embedding provider matters more here — the Bruno default is `openai` (collection `ascendai-1536`). For LM Studio / Gemini the collection is `ascendai-768`.
- A fresh `X-User-Id` per run (Bruno default is `frosty`).

## Bruno collection

Open Bruno → `docs/api/request/AscendAI/ascend-agent/testing/`. This test uses three requests:

1. `rag-ingestion-upload.yml` — uploads all three fixtures in one multipart POST (one `file` part per fixture, already wired in the file). Verifies Bug 18.
2. `rag-ingestion-run.yml` — scans the bucket and embeds new files. The two `prefix=` rows are **disabled by default** so the request sends without a `prefix` query param — the endpoint then scans the entire bucket (both `markdown/` and `documents/`) in one call.
3. `rag-prompt.yml` — asks a question that should hit RAG. Template — three alternative `prompt=` rows, one per fixture. Enable exactly one prompt at a time and re-send for each question.

### `rag-ingestion-run.yml` — parameters to enable

- `embeddingProvider`: `openai` (default — the only enabled row)
- Leave both `prefix=documents/` and `prefix=markdown/` disabled so the default no-prefix scan runs against the whole bucket.

If you want to scope an ingest to one folder only, toggle exactly one `prefix=` row on. The endpoint takes a single prefix per call — sending two prefix rows simultaneously is not supported.

### `rag-prompt.yml` — three sub-scenarios

The file holds three `prompt=` rows. Enable one at a time:

- **Scenario 1 (markdown):** `What is the Ascend canary phrase?`
- **Scenario 2 (PDF):** `What was the retail price of bananas in Poland in October 2026?`
- **Scenario 3 (DOCX):** `How long should I rest the pierogi dough according to Babcia Helena's recipe?`

Keep `provider` / `model` / `embeddingProvider` consistent across all three. Default is `minimax` + `MiniMax-M2.7` + `openai` embeddings.

## Steps

1. Send `rag-ingestion-upload.yml` once. Expect a 200 with three uploaded paths under `markdown/` and `documents/`.
2. Send `rag-ingestion-run.yml` once (no `prefix` enabled — full bucket scan). Expect `processed >= 3` (one markdown + one PDF + one DOCX).
3. Send `rag-prompt.yml` three times, one `prompt=` row enabled per send.
4. Watch the AscendAgent log throughout.

## Expected

For each of the three recall prompts:

- HTTP 200.
- `content` cites the relevant doc:
  - Scenario 1 — response contains `PURPLE-MOOSE-42`.
  - Scenario 2 — response contains `6.49 PLN`.
  - Scenario 3 — response mentions `30 minutes` (the rest time from Babcia Helena's recipe).
- Agent log shows `RAG Context Injected: YES (N chunks)` with N ≥ 1 — NOT `NO`. A `NO` here is the Bug 7 regression: lower the threshold or re-check the embedding provider matches across upload+prompt.
- Re-running the ingestion step does NOT duplicate Qdrant points (Bug 9): inspect the collection size in Qdrant dashboard, run `/ingestion/run` again, confirm the count is unchanged.

## Bugs this covers

Bugs 7, 9, 15, 16, 18 (see list above).

## Fixtures

- `AscendAgent/e2e/fixtures/markdown-canary.md` — one-line canary file `The Ascend canary phrase is PURPLE-MOOSE-42.`
- `AscendAgent/e2e/fixtures/banana-price-poland.pdf` — one-line price quote referencing `6.49 PLN`
- `AscendAgent/e2e/fixtures/pierogi-recipe.docx` — Babcia Helena's pierogi recipe with a 30-minute dough rest
