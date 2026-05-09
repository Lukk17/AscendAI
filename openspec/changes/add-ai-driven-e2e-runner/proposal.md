## Why

AscendAI ships a hand-rolled e2e suite under `AscendAgent/e2e/testing/*.md` (semantic-memory, RAG, PDF-read, image-description, weather-mcp). Today every test is run by a human who reads the markdown, pastes curls, eyeballs the response, greps `./gradlew bootRun` output for a substring, and decides "looks fine." That has three concrete failure modes:

1. **No one runs the full suite before merging.** Five capabilities × ~3 steps each × ~1 minute of attention = the suite is skipped and replaced with "I tested the bit I changed." The `fix-ascend-agent-bugs` change shipped four bugs to a user before being caught precisely because the suite wasn't being executed end-to-end.
2. **Verdicts drift.** Two humans reading the same response can disagree on whether `"the user's name appears to be Luke"` satisfies `Pass: response mentions Luke`. The judgement is implicit and unrepeatable, and there is no artifact attached to a PR that says "this run passed."
3. **No record of what was actually tested.** The current process produces zero artifacts — no captured request, no captured response body, no captured agent log slice, no verdict. A reviewer cannot tell whether a "tested locally" claim was real.

Claude (and any other LLM agent) is already capable of reading a markdown test plan, running curls in a Bash tool, tailing a log, and writing a structured summary. The missing piece is **stability**: a judge prompt that produces the same pass/fail/inconclusive verdict on the same evidence across runs and across reviewers, plus a convention that makes the existing test docs machine-executable.

This change adds an AI-driven e2e test runner: Claude reads `AscendAgent/e2e/testing/<capability>.md`, executes each step against the running stack, captures evidence, and judges each pass criterion through a tracked, version-controlled judge prompt. It produces one timestamped markdown summary per run under `AscendAgent/e2e/runs/`. The judge prompt itself is a deliverable created during implementation, not part of this propose.

## What Changes

- **Tracked judge prompt (`AscendAgent/e2e/judge-prompt.md`)**: a single prompt file that defines the rubric (PASS / FAIL / INCONCLUSIVE), the evidence schema (HTTP response, agent log slice, optional Qdrant / Postgres state), the JSON output contract, and a couple of worked examples. The prompt lives in git so updates go through PR review and a run summary records which sha was used.
- **Machine-executable convention for `AscendAgent/e2e/testing/<capability>.md`**: a shared structure — `### Pre-flight`, `### Test N — <name>`, `### Pass criteria` — with command blocks tagged `bash` and `powershell` (one of which is the canonical block). Existing files (`semantic-memory.md`, `rag.md`, `pdf-read.md`, `image-description.md`, `weather-mcp.md`) are normalized to this convention with no behavioral change.
- **Runner convention (skill or AGENTS-level instruction)**: Claude reads the doc top-to-bottom, runs each command in order, captures the response body, slices the agent log around the request timestamp, optionally queries Qdrant/Postgres for state checks, then feeds each pass criterion + evidence to the judge prompt at temperature 0. Per-step verdict is collected and written to a single output file.
- **Run output (`AscendAgent/e2e/runs/<UTC-timestamp>-<capability>.md`)**: one markdown file per run with overall verdict, per-test verdicts, evidence excerpts (truncated response / log lines), the judge model + prompt sha used, and any failure diagnostics. Old runs are kept; `.gitignore` may exclude them later but they are valid artifacts to attach to PRs.
- **Determinism + retry**: judge calls run at temperature 0 with a fixed system prompt. Non-deterministic LLM behavior is mitigated by retry-on-disagreement: if a re-run on the same evidence produces a different verdict, mark the step `INCONCLUSIVE` and surface it. Cap at 2 retries per criterion.
- **Failure semantics**: three buckets — `PASS`, `FAIL`, `INCONCLUSIVE`. Inconclusive (service down, log unreadable, response not captured, judge disagreement) is not a fail; it surfaces in a separate section of the summary so a human can investigate.
- **Cost cap**: per-run estimated cost is computed from token counts before each judge call. WARN at >$0.05; abort by default at >$0.50 (override via `--max-cost-usd`). Default judge model is a cheap one (Haiku 4.5 or Gemini Flash); per-run override is supported.
- **Local execution against a running stack**: the runner runs locally (Claude Code or sub-agent on the developer's machine). The AscendAgent stack must be reachable on its usual ports (defaults to `localhost:9917`, configurable). No assumption that the runner and the stack share a host — only that the runner can hit the agent over HTTP.

## Capabilities

### New Capabilities

- `ai-driven-e2e-runner` — Claude (or another LLM agent) can autonomously execute every test doc under `AscendAgent/e2e/testing/`, capture evidence, judge each pass criterion through a stable tracked prompt, and produce a single per-run markdown summary with PASS / FAIL / INCONCLUSIVE verdicts.

### Modified Capabilities

(none — this change is additive; existing `e2e/testing/*.md` files are normalized in shape but unchanged in intent)

## Impact

- **New files (committed)**:
  - `AscendAgent/e2e/judge-prompt.md` — tracked judge rubric, JSON schema, examples (created during implementation, not as part of this propose).
  - `AscendAgent/e2e/runs/.gitkeep` — folder placeholder for run summaries.
  - `AscendAgent/e2e/testing/CONVENTIONS.md` — short doc describing the machine-executable shape required of every test file.
  - One sample run output checked in as a regression fixture: `AscendAgent/e2e/runs/sample-semantic-memory.md`.
- **Modified files**:
  - `AscendAgent/e2e/testing/semantic-memory.md`, `rag.md`, `pdf-read.md`, `image-description.md`, `weather-mcp.md` — normalized to the convention; no test logic change.
  - `AscendAgent/e2e/testing/README.md` — adds a "Run via AI" section pointing at the runner skill / convention.
- **No application code changes**. This is a tooling + documentation layer on top of the existing manual suite.
- **No new runtime services**. The runner runs locally; no docker-compose changes.
- **Skill**: optional `.agents/skills/e2e-runner/` skill so any LLM agent (Claude Code, Kilo, OpenCode) can invoke the runner with a uniform interface. Out of scope for the spec but covered in tasks.
- **Cost**: per-run cost is bounded by the token budget cap. Default judge model (Haiku-class) keeps a full 5-capability run under ~$0.05. The cap aborts a runaway loop before it bills $1.
- **Backwards compat**: fully additive. Humans can still run the suite by hand against the same `e2e/testing/*.md` files; the convention does not change what those files mean, only their shape.
- **Out of scope (deferred)**:
  - Property-based fuzzing of e2e flows (separate change).
  - Headless CI integration / running the suite from GitHub Actions (covered by the planned `add-github-actions-pipeline` change).
  - Bruno's built-in JS-based in-request assertions — this change is about agent-orchestrated execution, not Bruno's own assertion runtime.
