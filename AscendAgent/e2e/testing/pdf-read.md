### PDF Read — End-to-End Test

---

Verifies that a PDF attached to a single prompt is parsed and used as context for that turn (per-prompt `document` field, not the RAG ingestion path).

### Pre-flight

---

Bash:

```bash
curl http://localhost:9917/
```

PowerShell:

```powershell
curl.exe http://localhost:9917/
```

The fixture lives at `AscendAgent/e2e/fixtures/banana-price-poland.pdf`. Its body contains a sentinel phrase the model couldn't have seen in training. Use a chat provider strong at long-context document reading (Anthropic, Gemini, OpenAI). LM Studio's small local models often can't quote verbatim.

### Test — prompt with attached PDF

---

**Bruno request:** `docs/api/request/AscendAI/ascend-agent/testing/doc-summarization-prompt.yml`

**Bruno CLI** (Bash):

```bash
bru run docs/api/request/AscendAI/ascend-agent/testing/doc-summarization-prompt.yml --env ascend-local
```

**Bruno CLI** (PowerShell):

```powershell
bru run docs/api/request/AscendAI/ascend-agent/testing/doc-summarization-prompt.yml --env ascend-local
```

**Equivalent curl** (Bash):

```bash
curl -X POST http://localhost:9917/api/v1/ai/prompt -H "X-User-Id: pdftest-001" -F "prompt=Quote the canary phrase from this PDF verbatim." -F "document=@AscendAgent/e2e/fixtures/banana-price-poland.pdf" -F "provider=anthropic" -F "model=claude-sonnet-4-6"
```

**Equivalent curl** (PowerShell):

```powershell
curl.exe -X POST http://localhost:9917/api/v1/ai/prompt -H "X-User-Id: pdftest-001" -F "prompt=Quote the canary phrase from this PDF verbatim." -F "document=@AscendAgent/e2e/fixtures/banana-price-poland.pdf" -F "provider=anthropic" -F "model=claude-sonnet-4-6"
```

### Pass criteria

---

- ✅ HTTP 200 with a `content` field that contains the sentinel phrase from the PDF.
- ✅ AscendAgent log shows `HasDoc: true` for this request and PDFBox / Unstructured parser activity around the same timestamp.
- ❌ If `content` summarises in general terms but doesn't quote the sentinel, the document text didn't reach the model. Try a stronger model (Claude Opus, Gemini Pro) or check the parser logs for extraction failures.
