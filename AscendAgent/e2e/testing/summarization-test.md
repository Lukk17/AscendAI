### Document Summarization — End-to-End Test

---

Verifies that a long-form document attached to a single prompt is parsed and summarized accurately by the chat model. Tests the per-prompt `document` field on `/api/v1/ai/prompt`, the same flow `pdf-read.md` uses but with a longer source and a summarization-style prompt rather than a verbatim-quote one.

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

The fixture lives at `AscendAgent/e2e/fixtures/argent-saga-chronicle.pdf`. The source markdown is at `AscendAgent/e2e/fixtures/argent-saga-chronicle.md` — convert it to PDF (any tool: Word "Save As PDF", Pandoc, browser print-to-PDF) and drop the PDF in the same folder. The content is original fictional universe content (no canon overlap), so distinctive facts in the summary prove the model read the document rather than fell back to training.

Use a chat provider strong at long-context document reading (Anthropic, Gemini, OpenAI). LM Studio's smaller local models often miss specifics in a multi-page summary.

### Test — summarize the attached PDF

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
curl -X POST http://localhost:9917/api/v1/ai/prompt -H "X-User-Id: summtest-001" -F "prompt=Summarize this saga in 5 bullet points. Include specific names, dates, and numbers from the text." -F "document=@AscendAgent/e2e/fixtures/argent-saga-chronicle.pdf" -F "provider=anthropic" -F "model=claude-sonnet-4-6"
```

**Equivalent curl** (PowerShell):

```powershell
curl.exe -X POST http://localhost:9917/api/v1/ai/prompt -H "X-User-Id: summtest-001" -F "prompt=Summarize this saga in 5 bullet points. Include specific names, dates, and numbers from the text." -F "document=@AscendAgent/e2e/fixtures/argent-saga-chronicle.pdf" -F "provider=anthropic" -F "model=claude-sonnet-4-6"
```

### Pass criteria

---

- ✅ HTTP 200 with a `content` field shaped as 5 bullets.
- ✅ The summary mentions at least three of these specific facts pulled from the source: `Aenaria Solveh`, `Halen Veyr`, `4317 P.E.`, `Heron's Tooth`, `thrall-burn`, `57 seconds`, `Concord of Mireth`, `412 A.E.`, `Vorsh-Ka the Quiet`, `81 duels`, `Iren Hask`, `498 A.E.`
- ✅ AscendAgent log shows `HasDoc: true` for this request and PDFBox / Unstructured / Docling parser activity around the same timestamp.
- ❌ If the summary is generic ("a saga about warrior orders and an alliance") with zero proper nouns from the source, the document content didn't reach the model. Try a stronger model (Claude Opus, Gemini Pro) or check the parser logs for extraction failures.

### Sanity check

---

Re-run with the same prompt but **without** the `-F "document=@..."` form field. The model should produce a generic refusal or a confused answer ("I don't have a saga to summarize"). If it produces a similar specific-sounding answer to the with-document run, something is off — possibly cached output or a misrouted parameter. The two runs should look very different.