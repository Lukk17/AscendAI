## Context

AscendAI's e2e suite lives as five hand-rolled markdown files under `AscendAgent/e2e/testing/` (`semantic-memory.md`, `rag.md`, `pdf-read.md`, `image-description.md`, `weather-mcp.md`). Each is read by a human, who pastes curls into a terminal, eyeballs the response, greps `bootRun` logs for a substring, and decides if it passed. The README at `AscendAgent/e2e/testing/README.md` already pins the convention: `Pre-flight`, `Test N`, `Pass`. There is no executor and no recorded verdict.

LLM agents — Claude Code in particular — are already capable of doing this work step-by-step (read doc, run command, capture output, decide). What's missing is a **stable judge prompt** so two runs against the same evidence give the same verdict, and a **convention** that guarantees Claude can execute the doc without guessing what each section means.

This change designs that runner. It ships no application code; it ships a tracked judge prompt, a doc convention, a runner skill / instruction layer, and an output format.

## Goals / Non-Goals

**Goals:**
- A single tracked `judge-prompt.md` whose sha is logged on every run so verdict drift is auditable.
- A doc convention that lets any LLM agent execute the suite without ambiguity (one canonical command block per step, named pass criteria, evidence hooks).
- A per-run output artifact suitable for attaching to a PR description.
- Three-bucket verdicts (`PASS` / `FAIL` / `INCONCLUSIVE`) so a flaky environment doesn't masquerade as a fail.
- Hard cost cap so a runaway agent can't burn $50 in judge calls.
- Cheap default judge model (Haiku 4.5 / Gemini Flash) overridable per run.

**Non-Goals:**
- Property-based fuzzing. The runner executes a fixed set of human-authored steps. Fuzz testing is a separate change.
- CI integration. The runner runs locally against a developer's stack. Headless CI execution is the `add-github-actions-pipeline` change's job.
- Replacing Bruno's in-request assertions. Bruno's `tests {}` blocks remain useful for low-level contract checks; this runner operates one level above, judging end-to-end behavior.
- New application code in AscendAgent. Tooling-only change.
- A bespoke CLI binary. The runner is a skill / convention, invoked through the existing Claude Code Bash + LLM tooling. We're not shipping `ascend-e2e run`.

## Decisions

### D1 — Capability slug: `ai-driven-e2e-runner`

We confirm the proposed slug. Alternatives considered:

- `e2e-test-runner` — too generic; doesn't convey that an LLM is doing the judging.
- `ai-test-orchestrator` — overstates the scope (no scheduling, no parallelism).
- `llm-judge-suite` — misses the execution half of the work.

`ai-driven-e2e-runner` makes both halves explicit (AI orchestrates AND judges) and slots cleanly under `openspec/specs/`.

### D2 — Judge prompt is a tracked markdown file with a fixed JSON output schema

`AscendAgent/e2e/judge-prompt.md` is the single source of truth for the rubric. It is markdown so it is reviewable in a PR diff, contains worked examples humans can read, and can carry inline rationale. The runner loads it verbatim and prepends it as the system prompt of every judge call.

Output is a strict JSON object so the runner can parse without an LLM-side template hack:

```json
{
  "verdict": "PASS" | "FAIL" | "INCONCLUSIVE",
  "confidence": 0.0..1.0,
  "evidence_cited": ["short quote from response", "log line excerpt"],
  "reasoning": "one to three sentences",
  "missing_evidence": ["what would have been needed if INCONCLUSIVE"]
}
```

The judge prompt enforces this with an explicit "respond with ONLY this JSON object, nothing else" instruction and ships two worked examples (one PASS, one FAIL). Parse failure → `INCONCLUSIVE` with reason `judge_response_unparseable`.

We considered a per-capability judge prompt (one for memory, one for RAG, etc.). Rejected: each variant is a new place verdicts could drift, and the rubric is the same shape across capabilities — only the evidence varies. Single prompt, evidence varies per call.

### D3 — Doc convention (machine-executable shape for `e2e/testing/*.md`)

Every test doc under `AscendAgent/e2e/testing/` MUST have:

- `### Pre-flight` — health-check commands; failure = whole doc INCONCLUSIVE.
- `### Test N — <name>` — one heading per step, numbered from 1.
- One canonical command block per test, tagged ` ```bash`. A ` ```powershell` mirror is allowed for cross-platform users but the bash block is authoritative.
- `**Pass:**` line(s) — natural-language pass criteria. The runner extracts one criterion per sentence (or per bullet) and feeds each to the judge separately so a partial pass is detectable.

Existing files already follow this shape almost exactly (see `semantic-memory.md`); this change normalizes the few deviations (e.g. command blocks tagged ` ```sh` vs ` ```bash`, multi-criterion `Pass:` lines without bullet structure).

A new `AscendAgent/e2e/testing/CONVENTIONS.md` formalizes the shape with a do/don't list and a minimal worked example.

### D4 — Evidence collection convention

Every step's judge call receives a fixed-shape evidence bundle:

```yaml
evidence:
  request:
    method: POST
    url: http://localhost:9917/api/v1/ai/prompt
    headers: {X-User-Id: memtest-001}
    body_excerpt: "..."           # truncated to 2 KB
  response:
    status: 200
    body_excerpt: "..."           # truncated to 4 KB; "..." marker on truncation
  agent_log:
    window_seconds: 30            # T-5s before request to T+25s after
    lines: ["...", "..."]         # last 200 lines in window, full lines kept
  side_effects:                   # optional, when the test specifies state checks
    qdrant:
      collection: ascend_memory_768
      filter: {user_id: memtest-001}
      point_count: 3
    postgres:
      table: chat_history
      where: {user_id: memtest-001}
      row_count: 0
```

The runner only populates `side_effects` when the test doc's `Pass:` line names the source explicitly (e.g. "Confirm in Qdrant: ≥1 point"). Side-effect commands live in the same canonical bash block as the request — the runner does NOT invent Qdrant queries. If the doc doesn't ask for it, it isn't captured.

Log slicing is timestamp-windowed, not match-based. The runner records the local clock at request issue (T) and reads `[T-5s, T+25s]` from the agent's stdout / log file. This catches both pre-request setup logs and async post-response logs without grepping (which would risk hiding a regression that changes the log substring).

### D5 — Determinism and retry-on-disagreement

Judge calls run at `temperature=0`, `top_p=1` (where the model honors it). LLM responses are still not bit-stable across runs, so:

- Each criterion is judged once.
- If the verdict is `FAIL` or `INCONCLUSIVE`, the runner re-judges once with the same evidence.
- If the second verdict matches the first → keep it.
- If they disagree → escalate to `INCONCLUSIVE` with reason `judge_disagreement` and surface both verdicts in the run output.
- Cap is 2 judge calls per criterion (the original + one retry). No exponential backoff; we are not chasing nondeterminism, we are detecting it.

`PASS` is not retried — false positives are caught by humans noticing wrong PRs merged; false negatives waste tokens.

### D6 — Failure semantics: PASS / FAIL / INCONCLUSIVE

| Verdict | Meaning | Examples |
|---|---|---|
| `PASS` | Evidence shows the pass criterion was met. | Response status 200 + log line `Successfully inserted memory fact for user: 'memtest-001'` present. |
| `FAIL` | Evidence shows the pass criterion was NOT met. | Response status 500, or 200 but log line says `Failed to extract facts`. |
| `INCONCLUSIVE` | Evidence is incomplete, contradictory, or the runner's environment failed. | Pre-flight curl returned 502; agent log file unreadable; judge disagreement; judge response unparseable. |

`INCONCLUSIVE` is reported in a separate section of the run output. It does NOT count as a fail in the overall verdict. The overall run is `PASS` only if every criterion is `PASS`; one or more `FAIL` → overall `FAIL`; otherwise (no fails, ≥1 inconclusive) → `INCONCLUSIVE`.

This three-bucket model exists because conflating "the test failed" with "the runner couldn't tell" punishes flaky environments and erodes trust in the result.

### D7 — Cost cap

Estimated cost per judge call:

```
estimated_usd = (input_tokens * input_price + output_tokens * output_price) / 1_000_000
```

Defaults assume Haiku 4.5 pricing (~$1/M input, ~$5/M output). Per criterion the runner sends ~3 KB evidence + ~2 KB prompt + ~200 tokens output ≈ ~$0.005. A full 5-capability run at ~3 criteria each ≈ $0.075 — already over the WARN threshold, which is fine: WARN is informational.

Behavior:

- Pre-run estimate (sum across all anticipated criteria) printed at start.
- WARN at >$0.05 estimated, ask for confirmation if running interactively.
- ABORT at >$0.50 actual mid-run — runner bails after the in-flight criterion, writes a partial run output marked `ABORTED`.
- Per-run override `--max-cost-usd 1.00` raises the abort threshold for one run only (never persisted).

The cap is a runaway-loop fuse, not a budget tool. Real budgeting is the user's responsibility.

### D8 — Default judge model + per-run override

Default: Anthropic Haiku 4.5 (cheap, fast, JSON-stable in our internal usage). Override via skill arg / runner CLI:

```
--judge-model gemini-3.1-flash
--judge-model claude-haiku-4-5     # explicit default
--judge-model gpt-5-mini           # opt-in to a different vendor
```

Reason for explicit override: when the agent under test IS Claude itself (e.g. the user is testing Claude-driven prompts), using a different model family for the judge reduces the risk of correlated failure. Allow but don't force.

### D9 — Local-only execution; remote stack reachable over HTTP

The runner runs in the developer's Claude Code session (or a sub-agent invoked from it). The AscendAgent stack runs separately — could be `./gradlew bootRun` on the same machine, could be the `docker-compose up` instance, could be a remote dev box reachable over a VPN. The only contract is "the agent + memory + qdrant + postgres + redis URLs in the test doc resolve."

This means:

- The runner does NOT manage the stack lifecycle. If `localhost:9917` returns connection-refused, the run goes `INCONCLUSIVE` at pre-flight.
- The runner does NOT need to be on the same host as the agent — but if it isn't, log-slicing requires a reachable log endpoint (file path, `docker logs`, or a stdout tail). The convention is: the test doc states where logs come from. Default is `./gradlew bootRun` stdout in the same shell.
- The runner does NOT scrape Prometheus or Actuator. Side-effect checks go through the same channels a human would (HTTP API, `psql`, `redis-cli`, `curl` against Qdrant). This keeps the runner stack-agnostic.

### D10 — Versioning and audit trail

Every run output records:

- The judge prompt's git sha (computed at runner start: `git rev-parse HEAD:AscendAgent/e2e/judge-prompt.md`).
- The judge model identifier and provider.
- The runner version (skill version or commit sha).
- The test doc's git sha at run time.
- UTC timestamp of run start.

If the judge prompt is modified, every subsequent run records the new sha. A reviewer comparing two runs can see whether a verdict changed because the SUT changed or because the prompt did.

The judge prompt is updated through normal PR review. Treat it as production code: no surprise edits.

## Risks / Trade-offs

- **Judge prompt rot.** As we add capabilities, the rubric may need new evidence types or new edge cases. Mitigation: every new test doc PR also exercises the runner against it; if the judge falls over on the new evidence shape, the prompt is updated in the same PR.
- **LLM judge bias.** A judge model trained on pass-friendly RLHF may default to PASS. Mitigation: the prompt's rubric is explicit about "evidence_cited must contain a verbatim substring proving the criterion." If the judge can't quote evidence, force INCONCLUSIVE.
- **Log-slicing on Windows + Docker.** `docker logs --since` is timestamp-fuzzy on Windows hosts. Mitigation: prefer `./gradlew bootRun` stdout when both options exist; document the gotcha in CONVENTIONS.md.
- **Cost cap doesn't catch input-token bloat.** A test doc that captures a 100 KB response will balloon judge cost. Mitigation: the evidence schema truncates response/log to 4 KB / 200 lines respectively; truncation is recorded in the run output.
- **Partial truncation hides regressions.** If the diagnostic line lives at line 250 of a 200-line agent log slice, the judge can't see it. Mitigation: when truncation happens, record `evidence_truncated: true` and surface it in the run output so a human knows to widen the window.
- **Inconclusive-rate creep.** If 30% of runs come back inconclusive, the runner is failing at evidence collection, not judging. Mitigation: the run output ALWAYS lists the inconclusive reason from a closed set (`pre_flight_unreachable`, `log_unreadable`, `judge_disagreement`, `judge_unparseable`, `evidence_truncated`); a histogram of these across runs flags root causes.

## Migration Plan

Strict additive sequence:

1. Author `AscendAgent/e2e/judge-prompt.md` with rubric, JSON schema, two worked examples. Land standalone (no consumer yet).
2. Author `AscendAgent/e2e/testing/CONVENTIONS.md` with the machine-executable shape.
3. Normalize one existing test doc (`semantic-memory.md`) to the convention. Verify by hand it still reads correctly to a human.
4. Manually drive Claude Code through the runner workflow against the normalized doc, against a live local stack. Capture the output to `AscendAgent/e2e/runs/sample-semantic-memory.md` and check it in as the regression fixture.
5. Normalize the remaining four test docs in one PR.
6. Optional follow-up: package the runner workflow as a `.agents/skills/e2e-runner/` skill so any agent can invoke it identically.
7. Update `AscendAgent/e2e/testing/README.md` with a "Run via AI" section.

## Open Questions

- **Should the runner write a single combined run output across all capabilities, or one per capability?** Current design: one per capability (`<timestamp>-<capability>.md`). Combined "suite run" output is a follow-up if the per-capability files prove unwieldy.
- **Where does the judge prompt's authoring style live?** The judge prompt itself is checked in; the *meta-prompt* used to generate it (if any) is not. Recommend treating the judge prompt as hand-authored from now on — no LLM-generated rewrites without diff review.
- **Should run outputs be gitignored?** Sample fixture is checked in. Real runs are local artifacts. Recommend `.gitignore`-ing `AscendAgent/e2e/runs/*.md` except `sample-*.md` once the workflow is validated; defer this decision until after the first month of usage.
- **Skill vs CLI vs raw convention.** This change ships the raw convention (Claude reads CONVENTIONS.md and follows it). A skill is offered as a follow-up. A bespoke CLI is rejected — adds a build target for a job the LLM can already do.
