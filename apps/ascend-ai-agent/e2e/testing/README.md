# ascend-ai-agent: e2e testing guide

Self-contained walkthroughs that an AI agent (or a human) can execute end-to-end against a live stack. Each file in
this directory drives one ascend-ai-agent capability through its Bruno request, with explicit prerequisite checks, reset
commands, run steps, and expected outcomes.

---

### Format

Every `<N>-<feature>-test.md` file is the **immutable spec** for one test and uses the same fixed template.

1. **What this verifies.** Bullet list of behaviours.
2. **Prerequisites.** Concrete check commands (`curl`, `psql`, `redis-cli`, etc.) the runner executes before
   starting. Each command is its own code block; the prose around it states what success looks like.
3. **Reset state.** One command per code block, executed in order, to wipe state so the test is reproducible. Every
   spec in this directory has this section: a run that crashed before reaching `Post-run cleanup` leaves
   `chat_history` rows, Redis keys or Qdrant points behind, and stale state changes the prompt the model sees on the
   next run. `Reset state` and `Post-run cleanup` clear the same resources; they are symmetric by construction.
4. **Run.** One or more numbered steps. Each step is a single Bruno CLI invocation. Steps wait for HTTP 200 before
   continuing to the next.
5. **Post-run cleanup.** One command per code block, removing every row, key, object and vector point the run
   created. A spec that sends even one prompt writes `chat_history` rows, a Redis `chat:` key and a Redis
   `user:<id>:instructions` key, and the agent's background semantic-memory extractor may write Qdrant points under
   `ascend_memory_*` for that user regardless of what the prompt was about, so every spec in this directory wipes
   that user's memory through `POST /api/v1/memory/wipe?user_id=...` even when the test has nothing to do with
   memory. The rule it enforces: a test leaves the system exactly as it found it. The section sits next to `Run` in
   the spec because that is where the state it names is created, but the runner executes it last, after the
   `Expected` assertions have been checked against the live state. The tasks-template ordering is the execution
   order. Run the commands whether the Run steps passed or failed.
6. **Expected.** Observable-behaviour assertions the runner verifies after each step: HTTP status codes,
   response-body shape and content, persisted state in the object store / Qdrant / Postgres, NOT log substrings. E2E specs test
   what the service *does*, not how it logs.
7. **Fixtures.** Paths to local files the test reads.

Each spec has a matching `<N>-<feature>-tasks.template.md` in the [templates/](templates/) subdirectory — the
**checkbox template** for a run. The runner never edits the spec or the template directly. Before starting a run, it
copies the template from `templates/` into [runs/](runs/) with a timestamped filename, ticks boxes as it progresses,
fills in `Result summary` and `Verdict`, and logs anything done outside the spec under `Additional tasks I did`. See
[runs/README.md](runs/README.md) for the full contract and naming convention.

---

### Bruno is the source of truth

Every test runs the matching Bruno request file under `docs/api/request/AscendAI/ascend-agent/testing/` via the
Bruno CLI.

Bash:

```bash
cd docs/api/request/AscendAI
```

```bash
bru run "ascend-agent/testing/<request>.yml" --env ascend-local
```

PowerShell:

```powershell
cd docs/api/request/AscendAI
```

```powershell
bru run "ascend-agent/testing/<request>.yml" --env ascend-local
```

The request's saved default rows are what gets sent. The walkthroughs intentionally do not name the default
provider / model / prompt. Those live in the Bruno file. To test an alternative, edit the disabled rows in the YAML
directly.

Install Bruno CLI once with `npm install -g @usebruno/cli`.

---

### Test order

Numbered by setup cost (lowest first). Run earliest first when stepping through; each is self-contained so any can
be run on its own.

1. [1-weather-mcp-test.md](1-weather-mcp-test.md). MCP tool round-trip. Resets/cleans its own `chat_history` rows,
   Redis keys and semantic-memory points.
2. [2-image-description-test.md](2-image-description-test.md). Image upload + vision-capable model. Resets/cleans
   its own `chat_history` rows, Redis keys and semantic-memory points.
3. [3-summarization-test.md](3-summarization-test.md). Inline PDF handling via PDFBox / Docling. Resets/cleans its
   own `chat_history` rows, Redis keys and semantic-memory points.
4. [4-semantic-memory-test.md](4-semantic-memory-test.md). Two-turn fact write + recall. Resets/cleans Redis,
   Postgres `chat_history`, Qdrant `ascend_memory_*` points.
5. [5-rag-test.md](5-rag-test.md). Full upload to ingest to retrieve pipeline. Resets/cleans its own object-store
   keys, Postgres `int_metadata_store`, Qdrant `ascendai-*` and `ascend_memory_*` points, `chat_history` rows,
   Redis keys.
6. [6-attach-sources-test.md](6-attach-sources-test.md). Presigned `sources[]` download URLs. Resets/cleans the same
   classes of state as test 5, scoped to its own fixtures and user id.
7. [7-rag-dedup-test.md](7-rag-dedup-test.md). Per-file `sources[]` dedup across chunks. Resets/cleans the same
   classes of state as test 5, scoped to its own fixtures and user id.
8. [8-prompt-cache-openai-test.md](8-prompt-cache-openai-test.md). OpenAI prefix-cache hit on a repeated prompt.
   Resets/cleans its own `chat_history` rows, Redis keys and semantic-memory points.
9. [9-prompt-cache-anthropic-test.md](9-prompt-cache-anthropic-test.md). Anthropic `cache_control` hit on a repeated
   prompt. Resets/cleans its own `chat_history` rows, Redis keys and semantic-memory points.
10. [10-compaction-fires-test.md](10-compaction-fires-test.md). Chat-history compaction fires past the turn-trigger
    and replaces the oldest prefix with a summary. Seeds 21 rows, resets/cleans the seeded plus post-run state.
11. [11-compaction-idempotency-test.md](11-compaction-idempotency-test.md). Compaction does not re-fire on an
    already-compacted history. Seeds the post-compaction state, resets/cleans the seeded plus post-run state.

---

### Cross-cutting conventions

Each Bruno request in this directory pins its own per-test `X-User-Id` (camelCase `frosty<TestName>Test`). Reset commands target that test's specific user id. This isolation makes tests safe to run in parallel; no cross-test chat-history pollution.

Pass criteria are observable behaviour only. HTTP status, response-body content, persisted state in backing services
(object listings, Qdrant scrolls, Postgres rows). Logs are diagnostic, not authoritative. Log lines drift across
versions and aren't visible from every runner's shell. If a behaviour assertion fails, a tail of the ascend-ai-agent log
(or `docker logs ascend-memory` etc.) is the next diagnostic step, but not a pass criterion.

---

### Adding a new test

1. Add a Bruno request under `docs/api/request/AscendAI/ascend-agent/testing/` with sensible default-enabled rows.
2. Create `apps/ascend-ai-agent/e2e/testing/<N>-<capability>-test.md` using the template above. Pick the lowest unused number
   prefix that matches its setup-cost position in the order.
3. Add the file to the ordered list in this README.
