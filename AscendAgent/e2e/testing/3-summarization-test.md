# Document summarization — e2e test

## What this verifies

- A PDF attached inline on the prompt endpoint is parsed page by page through the document pipeline (PDFBox → Docling).
- Extracted text is injected into the prompt under `<document_context>`.
- The chat model returns a summary grounded in real content from the source document, with specific proper nouns and facts.

## Prerequisites

Check Bruno CLI is installed.

```bash
bru --version
```

Expect a version string. If the command is not found, install it with `npm install -g @usebruno/cli`.

Check the AscendAgent health endpoint.

```bash
curl -fsS http://localhost:9917/actuator/health
```

Expect HTTP 200 with `{"status":"UP"}`.

Check Docling Serve is reachable from the host.

```bash
curl -fsS http://localhost:5001/health
```

Expect HTTP 200.

Check the fixture PDF exists.

```bash
ls AscendAgent/e2e/fixtures/argent-saga-chronicle.pdf
```

Expect the file path to print.

## Reset state

None. The document is sent inline with the prompt; nothing is persisted between runs.

## Run

Send the Bruno request and wait for the response before moving to the Expected section. The request may take 30–90 seconds because each PDF page is sent to Docling.

```bash
cd docs/api/request/AscendAI && bru run "ascend-agent/testing/doc-summarization-prompt.yml" --env ascend-local
```

## Expected

The Bruno output shows HTTP 200 and a response body whose `content` is a coherent summary that quotes specific facts from the source document. For `argent-saga-chronicle.pdf` look for at least three of: `Aenaria Solveh`, `Halen Veyr`, `4317 P.E.`, `Heron's Tooth`, `thrall-burn`, `57 seconds`, `Concord of Mireth`, `412 A.E.`, `Vorsh-Ka the Quiet`, `81 duels`, `Iren Hask`, `498 A.E.`.

The AscendAgent log shows `HasDoc: true` for the matching request id.

The AscendAgent log shows `[DocumentRouter] PDF <name> has <N> pages` and one `[DocumentRouter] Page i/N ... Routing to Docling` line per page.

The AscendAgent log shows `[DocumentRouter] Dispatching <N> pages of <name> in parallel (parallelism=<n>)`.

The AscendAgent log shows one `[DoclingClient] Extracted <chars> characters from <page>.pdf` line per page, each with a non-zero char count.

The AscendAgent log contains no HTTP 404 or 422 responses from Docling for this request.

## Fixtures

- `AscendAgent/e2e/fixtures/argent-saga-chronicle.pdf` (with the `.md` source alongside for regeneration).
