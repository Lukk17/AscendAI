# AscendAgent: end-to-end test suite

The manual / AI-runnable e2e suite for AscendAgent. Each test exercises one capability end-to-end against a live
stack and asserts only **observable behaviour**. HTTP status codes, response-body content, persisted state in MinIO,
Qdrant, and Postgres. Logs are diagnostic, not pass criteria.

---

### What's here

```text
AscendAgent/e2e/
├── README.md                            # this file
├── fixtures/                            # canary inputs (.md, .pdf, .docx, .png, .wav)
└── testing/                             # numbered specs + sidecar templates + run records
    ├── README.md
    ├── 1-weather-mcp-test.md            # spec (immutable)
    ├── 1-weather-mcp-tasks.template.md  # run-record template (immutable)
    ├── 2-image-description-test.md
    ├── 2-image-description-tasks.template.md
    ├── 3-summarization-test.md
    ├── 3-summarization-tasks.template.md
    ├── 4-semantic-memory-test.md
    ├── 4-semantic-memory-tasks.template.md
    ├── 5-rag-test.md
    ├── 5-rag-tasks.template.md
    ├── 6-attach-sources-test.md
    ├── 6-attach-sources-tasks.template.md
    ├── 7-rag-dedup-test.md
    ├── 7-rag-dedup-tasks.template.md
    ├── 8-prompt-cache-openai-test.md
    ├── 8-prompt-cache-openai-tasks.template.md
    ├── 9-prompt-cache-anthropic-test.md
    ├── 9-prompt-cache-anthropic-tasks.template.md
    ├── 10-compaction-fires-test.md
    ├── 10-compaction-fires-tasks.template.md
    ├── 11-compaction-idempotency-test.md
    ├── 11-compaction-idempotency-tasks.template.md
    └── runs/
        ├── README.md
        └── <UTC-timestamp>_<N>-<feature>-tasks.md   # one per executed test (gitignored)
```

Tests are number-prefixed by setup cost. `1` needs the least, `11` the most. Each spec has a paired tasks template
that the runner copies into [testing/runs/](testing/runs/) with a sweep timestamp, ticks off checkbox by checkbox as
it executes, and fills with results, token usage, and wall-clock time.

The Bruno collection isn't here. It lives at the **repo root** under `docs/api/request/AscendAI/` (collection root)
so it stays a portable API client artifact. Each spec references the matching Bruno request file under
`docs/api/request/AscendAI/ascend-agent/testing/`.

---

### How a test runs (flow)

```mermaid
flowchart LR
    Runner[AI runner or human] -->|copy template| Record[(runs/&lt;ts&gt;_N-&lt;feature&gt;-tasks.md)]
    Runner -->|bru run| Req[(Bruno request<br/>docs/api/request/AscendAI/...)]
    Req -->|HTTP| Agent[AscendAgent :9917]
    Fixture[(fixtures/canary.*)] -.uploaded as multipart.-> Agent

    subgraph Backends
        AM[AscendMemory :7020]
        QD[(Qdrant :6333)]
        S3[(MinIO :9070)]
        MCP[MCP servers<br/>Audio · Web · Weather · OCR]
    end

    Agent --> AM
    Agent --> QD
    Agent --> S3
    Agent --> MCP

    Agent -->|response JSON| Verify{Behavior assertions}
    Verify -->|HTTP status<br/>response content<br/>Qdrant scroll<br/>MinIO ls<br/>Postgres rows| Result[✅ / ❌]
    Result --> Record
```

Every spec follows the same template:

1. **What this verifies.** Bullet list of behaviours.
2. **Prerequisites.** Concrete check commands (`curl`, `docker exec redis redis-cli ping`, etc.), each in its own
   code block with prose stating the success criterion.
3. **Reset state.** One command per code block, in order, to wipe state so the run is reproducible.
4. **Run.** One or more numbered Bruno CLI invocations. Multi-step tests tell the runner to wait for HTTP 200 before
   continuing.
5. **Expected.** Observable behaviour only: HTTP status, response content, MinIO listings, Qdrant scrolls, Postgres
   rows. No log substrings.
6. **Fixtures.** Paths to local files the test reads.

The paired `<N>-<feature>-tasks.template.md` is the runner's checklist for one execution: prerequisites, reset
state, run steps, expected, verdict, plus **Result summary** (with **Input tokens**, **Output tokens**, **Time**
fields) and **Additional tasks I did** (anything done outside the spec). The runner copies the template into
[testing/runs/](testing/runs/) as `<UTC-timestamp>_<N>-<feature>-tasks.md` and fills it in.

---

### Prerequisites before any test

1. External infra running: PostgreSQL `:5432`, Redis `:6379`, Qdrant `:6333`, MinIO `:9070`.
2. Compose stack up: `docker compose up -d --build` (brings up AscendMemory, AscendWebSearch, AudioScribe, PaddleOCR,
   WeatherMCP, support services).
3. AscendAgent running on the host: `cd AscendAgent && ./gradlew bootRun`.

If the AscendAgent startup banner shows any `[FAILED]` rows under `External dependencies`, fix that first. Each
individual spec also has explicit prereq checks the runner executes before starting.

---

### Running tests

Install the Bruno CLI once.

Bash:

```bash
npm install -g @usebruno/cli
```

PowerShell:

```powershell
npm install -g @usebruno/cli
```

Run one capability.

Bash:

```bash
cd docs/api/request/AscendAI && bru run "ascend-agent/testing/weather-mcp-prompt.yml" --env ascend-local
```

PowerShell:

```powershell
cd docs/api/request/AscendAI
```

```powershell
bru run "ascend-agent/testing/weather-mcp-prompt.yml" --env ascend-local
```

Run the whole suite (Bruno's directory mode).

Bash:

```bash
cd docs/api/request/AscendAI && bru run "ascend-agent/testing" --env ascend-local
```

PowerShell:

```powershell
cd docs/api/request/AscendAI
```

```powershell
bru run "ascend-agent/testing" --env ascend-local
```

Or follow a spec end-to-end manually: read `<N>-<feature>-test.md`, copy its template to
`runs/<UTC-timestamp>_<N>-<feature>-tasks.md`, work through the checkboxes.

---

### Fixtures

[fixtures/](fixtures/) holds small canary files used by the upload-style tests. Each fixture holds distinctive
content (no overlap with model training) so a passing test proves the answer came from retrieval or the attached
document rather than memorised knowledge.

| File                                                       | Used by                                | Distinctive content                                                       |
| :--------------------------------------------------------- | :------------------------------------- | :------------------------------------------------------------------------ |
| `markdown-canary.md`                                       | RAG (test 5)                           | One-line canary phrase the model can't possibly know.                     |
| `banana-price-poland.pdf`                                  | RAG (test 5)                           | Specific recent retail price.                                             |
| `pierogi-recipe.docx`                                      | RAG (test 5), attach-sources (test 6)  | Recipe with a distinctive rest time.                                      |
| `dedup-pierogi-helena.md`                                  | RAG dedup (test 7)                     | Babcia Helena's pierogi recipe (HELENA-DEDUP-CANARY).                     |
| `dedup-pierogi-grandma.md`                                 | RAG dedup (test 7)                     | Grandma Maria's pierogi recipe (GRANDMA-DEDUP-CANARY).                    |
| `argent-saga-chronicle.pdf`                                | Summarization (test 3)                 | Fictional saga with unique proper nouns.                                  |
| `image.png`                                                | Image description (test 2)             | Recognisable subject the model can describe.                              |
| `meeting-clip.wav`                                         | (future audio test)                    | Short meeting recording.                                                  |
| `compaction-seeds/seed-compaction-fires.{sql,redis}`       | Compaction fires (test 10)             | 21-row deterministic chat history with sprinkled facts.                   |
| `compaction-seeds/seed-compaction-idempotency.{sql,redis}` | Compaction idempotency (test 11)       | 1 summary row + 8 raw turns, mimicking post-compaction state.             |

---

### Capability tests

Numbered by setup cost. Easiest first.

| #  | Spec                                                                                            | Template                                                                                                              | What it proves                                                                                                          |
| :- | :---------------------------------------------------------------------------------------------- | :-------------------------------------------------------------------------------------------------------------------- | :---------------------------------------------------------------------------------------------------------------------- |
| 1  | [testing/1-weather-mcp-test.md](testing/1-weather-mcp-test.md)                                  | [testing/1-weather-mcp-tasks.template.md](testing/1-weather-mcp-tasks.template.md)                                    | The agent discovers and invokes the WeatherMCP tool.                                                                    |
| 2  | [testing/2-image-description-test.md](testing/2-image-description-test.md)                      | [testing/2-image-description-tasks.template.md](testing/2-image-description-tasks.template.md)                        | An attached image reaches a vision-capable model and is described accurately.                                           |
| 3  | [testing/3-summarization-test.md](testing/3-summarization-test.md)                              | [testing/3-summarization-tasks.template.md](testing/3-summarization-tasks.template.md)                                | A PDF attached inline is parsed page by page through Docling and summarised from real content.                          |
| 4  | [testing/4-semantic-memory-test.md](testing/4-semantic-memory-test.md)                          | [testing/4-semantic-memory-tasks.template.md](testing/4-semantic-memory-tasks.template.md)                            | A fact stated in turn 1 is recalled in turn 2 from Qdrant via AscendMemory, after chat history is wiped.                |
| 5  | [testing/5-rag-test.md](testing/5-rag-test.md)                                                  | [testing/5-rag-tasks.template.md](testing/5-rag-tasks.template.md)                                                    | Uploaded `.md`, `.pdf`, `.docx` ingest into Qdrant and surface in a later prompt with grounded citations.               |
| 6  | [testing/6-attach-sources-test.md](testing/6-attach-sources-test.md)                            | [testing/6-attach-sources-tasks.template.md](testing/6-attach-sources-tasks.template.md)                              | `attachSources=true` returns a presigned MinIO URL that resolves with HTTP 200 and uses `localhost:9070`.               |
| 7  | [testing/7-rag-dedup-test.md](testing/7-rag-dedup-test.md)                                      | [testing/7-rag-dedup-tasks.template.md](testing/7-rag-dedup-tasks.template.md)                                        | Multiple chunks across 2 source files collapse into exactly 2 unique entries in `sources[]` (dedup by `(bucket, key)`). |
| 8  | [testing/8-prompt-cache-openai-test.md](testing/8-prompt-cache-openai-test.md)                  | [testing/8-prompt-cache-openai-tasks.template.md](testing/8-prompt-cache-openai-tasks.template.md)                    | Two consecutive identical prompts on `provider=openai` produce a cache hit on call 2 (`cachedTokens > 0`).              |
| 9  | [testing/9-prompt-cache-anthropic-test.md](testing/9-prompt-cache-anthropic-test.md)            | [testing/9-prompt-cache-anthropic-tasks.template.md](testing/9-prompt-cache-anthropic-tasks.template.md)              | Two consecutive identical prompts on `provider=anthropic` produce native `cache_control` cache write on call 1 and cache read on call 2. |
| 10 | [testing/10-compaction-fires-test.md](testing/10-compaction-fires-test.md)                      | [testing/10-compaction-fires-tasks.template.md](testing/10-compaction-fires-tasks.template.md)                        | After SQL + Redis seed of 21 rows + 1 prompt, async compaction replaces the prefix with exactly 9 rows: 1 `[Conversation summary]` + 8 raw. |
| 11 | [testing/11-compaction-idempotency-test.md](testing/11-compaction-idempotency-test.md)          | [testing/11-compaction-idempotency-tasks.template.md](testing/11-compaction-idempotency-tasks.template.md)            | After seed of 1 summary + 8 raw rows, sending 1 more prompt does NOT re-fire compaction (row count goes 9 to 11, no new summary). |

---

### Adding a new capability test

1. Add the Bruno request(s) under `docs/api/request/AscendAI/ascend-agent/testing/<capability>.yml` with sensible
   default-enabled rows.
2. If the test needs a fixture, drop the canary file in [fixtures/](fixtures/) (keep it small and uniquely
   identifiable).
3. Pick the next number prefix that matches the test's setup cost.
4. Write `testing/<N>-<capability>-test.md` using the template structure (**What this verifies / Prerequisites /
   Reset state / Run / Expected / Fixtures**). Assert behaviour, not logs.
5. Write `testing/<N>-<capability>-tasks.template.md` mirroring the spec's checkboxes, with `## Result summary`
   containing the **Input tokens / Output tokens / Time** fields at the bottom.
6. Add a row to the capability table above.
