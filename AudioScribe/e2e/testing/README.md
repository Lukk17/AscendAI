# e2e testing guide

Self-contained walkthroughs that an AI agent (or a human) can execute end-to-end against a live AudioScribe container.
Each `<N>-<capability>-test.md` spec in this directory drives one AudioScribe capability through its Bruno request,
with explicit prerequisite checks, reset commands, run steps, and expected outcomes. The paired run-record templates
live in the `templates/` subdirectory; executed run records land in `runs/`.

## Format

Every `<N>-<capability>-test.md` file is the **immutable spec** for one test and uses the same fixed template.

1. **What this verifies.** Bullet list of behaviours.
2. **Prerequisites.** Concrete check commands (`curl`, `bru --version`, `docker exec ... printenv`) the runner
   executes before starting. Each command is its own code block; the prose around it states what success looks like.
3. **Reset state.** One command per code block, executed in order, to wipe state so the test is reproducible. Tests
   that write to the `/tmp` transcript-download cache delete those files before starting; tests with no persisted
   state document "None".
4. **Run.** One or more numbered steps. Each step is a single Bruno CLI invocation (REST tests) or a `curl`
   `initialize` handshake followed by a `bru run` `tools/call` (MCP tests). Steps wait for HTTP 200 before continuing.
5. **Expected.** Observable-behaviour assertions verified after each step: HTTP status codes, `Content-Type` header,
   response body content (canary phrase substring on normalised lowercase output for transcribe tests, FastAPI
   validation-error shape for the invalid-input test, JSON-RPC `result` payload shape for MCP tests). NOT log
   substrings.
6. **Fixtures.** Paths to local canary audio files under `../fixtures/` that the test uploads.

Each spec has a matching `<N>-<capability>-tasks.template.md` in the [templates/](templates/) subdirectory — the
**checkbox template** for a run. The runner never edits the spec or the template directly. Before starting a run, it
copies the template from `templates/` into [runs/](runs/) with a timestamped filename, ticks boxes as it progresses,
fills in `Result summary` and `Verdict`, and logs anything done outside the spec under `Additional tasks I did`. See
[runs/README.md](runs/README.md) for the full runner contract.

## Bruno is the source of truth

Every test runs the matching Bruno request file under `docs/api/request/AscendAI/transcribe/testing/` via the Bruno
CLI.

```powershell
cd docs/api/request/AscendAI
```

```powershell
bru run "transcribe/testing/<request>.yml" --env ascend-local
```

The request's saved default rows are what gets sent. To test an alternative payload, edit the disabled rows in the
YAML directly.

Install Bruno CLI once with `npm install -g @usebruno/cli`.

## Test order

Numbered by setup cost (lowest first). Run earliest first when stepping through; each is self-contained so any can
be run on its own.

1. [1-invalid-input-test.md](1-invalid-input-test.md). FastAPI validation-error short-circuit. **No external API
   egress.**
2. [2-transcribe-openai-test.md](2-transcribe-openai-test.md). Canary phrase round-trip through the OpenAI Whisper
   API.
3. [3-transcribe-hf-test.md](3-transcribe-hf-test.md). Canary phrase round-trip through the Hugging Face Inference
   API.
4. [4-mcp-tools-list-test.md](4-mcp-tools-list-test.md). MCP `tools/list` advertises the documented transcribe tool
   set.
5. [5-mcp-transcribe-test.md](5-mcp-transcribe-test.md). MCP `tools/call` `transcribe_openai` against a `file://`
   URI. **Requires a fixtures bind-mount.**

## Cross-cutting conventions

Pass criteria are observable behaviour only. HTTP status, `Content-Type` header, response body content (substring
match for the canary phrase on the transcribe tests, FastAPI validation-error shape for the invalid-input test,
JSON-RPC `result` payload for MCP tests). Logs are diagnostic, not authoritative. Log lines drift across versions
and aren't visible from every runner's shell. If a behaviour assertion fails, a tail of the AudioScribe log (or
`docker logs audio-scribe`) is the next diagnostic step, but not a pass criterion.

The canary substring assertion is **case-insensitive** and is performed on the normalised lowercase response body.
Whisper and HF may capitalise differently, drop articles, or punctuate inconsistently across runs; the substring
check tolerates that.

## Adding a new test

1. Add a Bruno request under `docs/api/request/AscendAI/transcribe/testing/<request>.yml`.
2. Create `AudioScribe/e2e/testing/<N>-<capability>-test.md` using the template above. Pick the lowest unused number
   prefix that matches its setup-cost position in the order.
3. Create `AudioScribe/e2e/testing/templates/<N>-<capability>-tasks.template.md` mirroring the spec's checkboxes.
4. Add the file to the ordered list in this README and in the capability table in the parent
   [../README.md](../README.md).
