### PDF Read — End-to-End Test

Verifies that a PDF attached to a single prompt is parsed and used as context for that turn (per-prompt `document`, not RAG ingestion).

#### Pre-flight

```bash
curl http://localhost:9917/   # AscendAgent
```

Have any short PDF on disk. Easiest: a one-page invoice, receipt, or a quickly-generated PDF whose body contains a sentinel phrase like `PDF-CANARY-42` so you can prove the model read the file (not made it up).

#### Test — Prompt with attached PDF

```bash
curl -X POST http://localhost:9917/api/v1/ai/prompt \
  -H "X-User-Id: pdftest-001" \
  -F "prompt=Quote the canary phrase from this PDF verbatim." \
  -F "document=@/path/to/canary.pdf" \
  -F "provider=anthropic" -F "model=claude-sonnet-4-6"
```

Use a chat provider strong at long-context document reading (Anthropic / Gemini / OpenAI). LM Studio's small local models often can't quote verbatim.

**Pass:**
- HTTP 200; response `content` contains `PDF-CANARY-42`.
- AscendAgent log shows the request had `HasDoc: true` and the document was extracted (look for PDFBox / parser log lines around the request).
