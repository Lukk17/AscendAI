# e2e testing guide

Self-contained walkthroughs that an AI agent (or a human) can execute end-to-end against a live AscendMemory
container. Each `<N>-<capability>-test.md` spec in this directory drives one memory operation through its Bruno
request, with explicit prerequisite checks, reset commands, run steps, and expected outcomes. The paired run-record
templates live in the `templates/` subdirectory; executed run records land in `runs/`.

## Format

Every `<N>-<capability>-test.md` file is the **immutable spec** for one test and uses the same fixed template.

1. **What this verifies.** Bullet list of behaviours.
2. **Prerequisites.** Concrete check commands (`curl`, `bru --version`) the runner executes before starting. Each
   command is its own code block; the prose around it states what success looks like.
3. **Reset state.** One command per code block, executed in order, to wipe state so the test is reproducible. For
   AscendMemory this means wiping the specific `user_id`(s) the test touches via
   `POST /api/v1/memory/wipe?user_id=...`. Test 1 needs no reset (it never reaches mem0).
4. **Run.** One or more numbered steps. Each step is a single Bruno CLI invocation. MCP tests have an additional
   first step: a `curl.exe` call to `/mcp` carrying the `initialize` JSON-RPC method, capturing the response's
   `Mcp-Session-Id` header so subsequent Bruno requests can inject it as `--env-var mcp_session_id=<uuid>`.
5. **Expected.** Observable-behaviour assertions verified after each step: HTTP status codes, response body fields,
   user-scope isolation visible via cross-user search. NOT log substrings.
6. **Fixtures.** Paths to local files the test reads (none for the current suite).

Each spec has a matching `<N>-<capability>-tasks.template.md` in the [templates/](templates/) subdirectory — the
**checkbox template** for a run. The runner never edits the spec or the template directly. Before starting a run, it
copies the template from `templates/` into [runs/](runs/) with a timestamped filename, ticks boxes as it progresses,
fills in `Result summary` and `Verdict`, and logs anything done outside the spec under `Additional tasks I did`. See
[runs/README.md](runs/README.md) for the full contract and naming convention.

## Bruno is the source of truth

Every test runs the matching Bruno request file under `docs/api/request/AscendAI/memory/testing/` via the Bruno CLI.

```powershell
cd docs/api/request/AscendAI
```

```powershell
bru run "memory/testing/<request>.yml" --env ascend-local
```

The request's saved default rows are what gets sent. To test an alternative payload, edit the disabled rows in the
YAML directly.

Install Bruno CLI once with `npm install -g @usebruno/cli`.

## Test order

Numbered by setup cost (lowest first). Run earliest first when stepping through; each is self-contained so any can
be run on its own.

1. [1-invalid-input-test.md](1-invalid-input-test.md). FastAPI validation rejection. **No state writes.**
2. [2-insert-and-search-test.md](2-insert-and-search-test.md). REST insert → REST search round-trip.
3. [3-wipe-user-scope-test.md](3-wipe-user-scope-test.md). Wipe one user, the other survives.
4. [4-mcp-tools-list-test.md](4-mcp-tools-list-test.md). MCP `tools/list` advertises the memory tools.
5. [5-mcp-insert-and-search-test.md](5-mcp-insert-and-search-test.md). MCP `memory_insert` → MCP `memory_search`.

## Cross-cutting conventions

Pass criteria are observable behaviour only. HTTP status, response body content, the shape and contents of the
memory list returned by `/search`. Logs are diagnostic, not authoritative. Log lines drift across versions and
aren't visible from every runner's shell. If a behaviour assertion fails, a tail of the AscendMemory log (or
`docker logs ascend-memory`) is the next diagnostic step, but not a pass criterion.

## Adding a new test

1. Add a Bruno request under `docs/api/request/AscendAI/memory/testing/<request>.yml`.
2. Create `AscendMemory/e2e/testing/<N>-<capability>-test.md` using the template above. Pick the lowest unused
   number prefix that matches its setup-cost position in the order.
3. Create `AscendMemory/e2e/testing/templates/<N>-<capability>-tasks.template.md` mirroring the spec's checkboxes.
4. Add the file to the ordered list in this README and in the capability table in the parent
   [../README.md](../README.md).
