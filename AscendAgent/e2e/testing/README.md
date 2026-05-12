# AscendAgent — manual e2e testing guide

Short, focused walkthroughs a tester (human or AI agent) runs against a live stack (AscendAgent + AscendMemory + Qdrant + Redis + the relevant MCP servers). Each walkthrough is one capability, pinned to a Bruno collection in `docs/api/request/AscendAI/ascend-agent/`.

## Bruno is the source of truth

Each `-test.md` file drives its scenario through a Bruno request, not curl. **Important convention:** several Bruno requests in the collection are **templates** — they save multiple alternative values against the same form-field name (e.g. several `prompt=`, `provider=`, `model=`, `embeddingProvider=` rows for one request). Bruno toggles each row on/off via a disabled flag.

Before sending a request you (human or AI) must:

1. Open the request in Bruno.
2. Enable exactly the rows the walkthrough lists for the scenario you're running.
3. Disable everything else for that field.
4. Send.

If you don't do this, you'll send multiple values for the same field name and the agent will either reject the request or pick one non-deterministically. The walkthroughs spell out the exact rows to enable.

## Test order

Run the tests in this order — earliest are the fastest / fewest moving parts, latest need the most setup.

1. [`weather-mcp-test.md`](weather-mcp-test.md) — MCP tool round-trip; fastest smoke test.
2. [`image-description-test.md`](image-description-test.md) — image upload + vision-capability gate (allow-path and deny-path).
3. [`summarization-test.md`](summarization-test.md) — inline document handling via Docling/Unstructured/PDFBox. Subsumes the old `pdf-read.md`.
4. [`semantic-memory-test.md`](semantic-memory-test.md) — two-turn write + recall through AscendMemory → Qdrant.
5. [`rag-test.md`](rag-test.md) — full ingest pipeline (MinIO + Qdrant) for three file formats plus threshold-tuned retrieval. Most setup.

`pdf-read.md` was removed — its scenario was a strict subset of `summarization-test.md` (per-prompt `document` field, same code path).

## Cross-cutting conventions

- Pin a fresh `X-User-Id` per run so prior state can't pollute results. Bruno files default to `frosty`; wipe that user's data in Qdrant / Redis / Postgres between runs, or change the header.
- Pass criteria reference exact log substrings (`RAG Context Injected: YES`, `SemanticMemory: YES (N items)`, `HasImage: true`, `HasDoc: true`) — `grep` them in `./gradlew bootRun` output during the run.
- Each walkthrough lists which bugs from `openspec/changes/fix-ascend-agent-bugs/tasks.md` it covers. Functionality is the primary subject; bug numbers map the walkthrough back to the regression history.

## Adding a new test

1. Add a Bruno request under `docs/api/request/AscendAI/ascend-agent/testing/`.
2. Create `AscendAgent/e2e/testing/<capability>-test.md` mirroring the existing structure: **What this verifies / Prerequisites / Bruno collection / Steps / Expected / Bugs this covers / Fixtures**.
3. Add the file to the ordered list above.
