# Document Summarization — manual e2e test

## What this verifies

A long-form document attached to a single prompt is parsed (PDFBox / Docling / Unstructured) and summarized accurately by the chat model. Covers:

- **Bug 3** — Docling endpoint path (the PDF flow only works when the agent calls the correct Docling URL)
- **Bug 8** — ingestion-upload security & limits (implicit; the per-prompt `document` field shares the same upload sanitization)
- **Bug 17** — RAG/memory-first system prompt: the summary must ground in the attached doc and not hallucinate from training

This test absorbs the previous `pdf-read.md` walkthrough — both exercised the per-prompt `document` field on `/api/v1/ai/prompt`.

## Prerequisites

- `docker compose up -d` stack up (Docling Serve on 5001, Unstructured on 9080)
- AscendAgent on port 9917
- A chat provider strong at long-context document reading (Anthropic claude-sonnet-4-6 / claude-opus-4-6, OpenAI gpt-5.1 / gpt-4o, or Gemini 2.5+). Small local LM Studio models often miss specifics in a multi-page summary.

## Bruno collection

Open Bruno → `docs/api/request/AscendAI/ascend-agent/testing/` → `doc-summarization-prompt.yml`.

The file is a template — multiple `provider=` / `model=` rows are saved against the same field names. Enable exactly one provider/model pair before sending.

For this test enable:

- `document`: file → `AscendAgent/e2e/fixtures/argent-saga-chronicle.pdf`
- `prompt`: `Summarize the key points in this document`
- `provider`: `anthropic` (toggle on; the file defaults to `minimax` which is fine for a quick run but Claude / GPT give richer summaries)
- `model`: `claude-sonnet-4-6`
- `embeddingProvider`: `openai`

Header `X-User-Id: frosty` is already pinned.

If the PDF doesn't exist, the source markdown is at `AscendAgent/e2e/fixtures/argent-saga-chronicle.md` — convert it to PDF (Word "Save As PDF", Pandoc, or browser print-to-PDF) and drop the result next to it.

## Steps

1. Confirm Docling Serve responds: `GET http://localhost:5001/health`.
2. Send the Bruno request.
3. Inspect the response and the AscendAgent log for parser activity.

## Expected

- HTTP 200; `content` is a coherent summary that quotes specific facts from the source, not generic prose. Look for at least three of: `Aenaria Solveh`, `Halen Veyr`, `4317 P.E.`, `Heron's Tooth`, `thrall-burn`, `57 seconds`, `Concord of Mireth`, `412 A.E.`, `Vorsh-Ka the Quiet`, `81 duels`, `Iren Hask`, `498 A.E.`
- Agent log shows `HasDoc: true` for this request and PDFBox / Unstructured / Docling parser activity at the same timestamp. No 404 against Docling (regression check for Bug 3).
- If the summary is generic ("a saga about warrior orders") with zero proper nouns from the source, the document text didn't reach the model. Try Claude Opus or Gemini Pro, then check parser logs for extraction failures.

Sanity check: re-run the same prompt without the `document` field (disable that row in Bruno). The model should refuse or ask for the doc. If the second run produces a similar specific-sounding answer, something is misrouted.

## Bugs this covers

- **Bug 3** — Docling endpoint path fix
- **Bug 8** — upload limits / sanitization shared with `/ingestion/upload`
- **Bug 17** — memory-first system prompt; summary must be grounded in the attached doc

## Fixtures

- `AscendAgent/e2e/fixtures/argent-saga-chronicle.pdf` (with `.md` source alongside for regeneration)
