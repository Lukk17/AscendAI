# AscendAgent — e2e testing guide

Self-contained walkthroughs that an AI agent (or a human) can execute end-to-end against a live stack. Each file in this directory drives one AscendAgent capability through its Bruno request, with explicit prerequisite checks, reset commands, run steps, and expected outcomes.

## Format

Every `<N>-<feature>-test.md` file is the **immutable spec** for one test and uses the same fixed template:

1. **What this verifies** — bullet list of behaviours.
2. **Prerequisites** — concrete check commands (`curl`, `psql`, `redis-cli`, etc.) the runner executes before starting. Each command is its own code block; the prose around it states what success looks like.
3. **Reset state** — one command per code block, executed in order, to wipe state so the test is reproducible.
4. **Run** — one or more numbered steps. Each step is a single Bruno CLI invocation. Steps wait for HTTP 200 before continuing to the next.
5. **Expected** — log substrings and response shape the runner verifies after each step.
6. **Fixtures** — paths to local files the test reads.

Alongside each spec lives a `<N>-<feature>-tasks.template.md` — the **checkbox template** for a run. The runner never edits the spec or the template directly. Instead, before starting a run, it copies the template into `runs/` with a timestamped filename, ticks boxes as it progresses, fills in `Result summary` and `Verdict`, and logs anything done outside the spec under `Additional tasks I did`. See [`runs/README.md`](runs/README.md) for the full contract and naming convention.

## Bruno is the source of truth

Every test runs the matching Bruno request file under `docs/api/request/AscendAI/ascend-agent/testing/` via the Bruno CLI.

```bash
cd docs/api/request/AscendAI && bru run "ascend-agent/testing/<request>.yml" --env ascend-local
```

The request's saved default rows are what gets sent. The walkthroughs intentionally do not name the default provider / model / prompt — those live in the Bruno file. To test an alternative, edit the disabled rows in the YAML directly.

Install Bruno CLI once with `npm install -g @usebruno/cli`.

## Test order

Numbered by setup cost (lowest first). Run earliest first when stepping through; each is self-contained so any can be run on its own.

1. [`1-weather-mcp-test.md`](1-weather-mcp-test.md) — MCP tool round-trip. No state to reset.
2. [`2-image-description-test.md`](2-image-description-test.md) — image upload + vision-capable model. No state to reset.
3. [`3-summarization-test.md`](3-summarization-test.md) — inline PDF handling via PDFBox / Docling. No state to reset.
4. [`4-semantic-memory-test.md`](4-semantic-memory-test.md) — two-turn fact write + recall. Resets Redis, Postgres `chat_history`, Qdrant points.
5. [`5-rag-test.md`](5-rag-test.md) — full upload → ingest → retrieve pipeline. Resets MinIO bucket, Postgres `int_metadata_store`, Qdrant points.

## Cross-cutting conventions

All Bruno requests in this directory pin `X-User-Id: frosty`. Reset commands target that user id.

Pass criteria reference exact log substrings printed by the AscendAgent (`RAG Context Injected: YES`, `SemanticMemory: YES (N items)`, `HasImage: true`, `HasDoc: true`, `Extracted N characters from ...`). Tail the agent log while running.

## Adding a new test

1. Add a Bruno request under `docs/api/request/AscendAI/ascend-agent/testing/` with sensible default-enabled rows.
2. Create `AscendAgent/e2e/testing/<N>-<capability>-test.md` using the template above. Pick the lowest unused number prefix that matches its setup-cost position in the order.
3. Add the file to the ordered list in this README.
