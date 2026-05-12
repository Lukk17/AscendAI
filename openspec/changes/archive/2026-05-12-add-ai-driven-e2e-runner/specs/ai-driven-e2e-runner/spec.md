## ADDED Requirements

### Requirement: Tracked judge prompt with fixed JSON output schema

A single tracked file `AscendAgent/e2e/judge-prompt.md` SHALL define the rubric (`PASS` / `FAIL` / `INCONCLUSIVE`), the evidence-citation rule (every PASS verdict must cite a verbatim substring from the supplied response or log), and a strict JSON output schema. The runner SHALL prepend this file verbatim as the judge model's system prompt on every judge call. Updates to the rubric SHALL go through normal PR review and SHALL NOT happen mid-run.

#### Scenario: Judge prompt is loaded verbatim from disk

- **WHEN** the runner starts a session
- **THEN** it reads `AscendAgent/e2e/judge-prompt.md` once at startup
- **AND** it computes the file's git sha (via `git rev-parse HEAD:AscendAgent/e2e/judge-prompt.md`)
- **AND** it uses the file's text verbatim as the judge model's system prompt for every subsequent judge call in the session

#### Scenario: Judge response is strict JSON

- **WHEN** the judge model returns a response
- **THEN** the runner parses it as JSON with required keys `verdict`, `confidence`, `evidence_cited`, `reasoning`, `missing_evidence`
- **AND** if parsing fails, the runner records the criterion as `INCONCLUSIVE` with reason `judge_unparseable`
- **AND** the runner does NOT retry parse failures with a different prompt

### Requirement: Machine-executable convention for `e2e/testing/*.md`

Every test doc under `AscendAgent/e2e/testing/` SHALL conform to a shared shape so any LLM agent can execute it without ambiguity. Required headings: `### Pre-flight`, `### Test N — <name>` (numbered from 1), `**Pass:**` (with one criterion per bullet or sentence). Each test SHALL have one canonical `bash`-tagged command block; an additional `powershell` mirror is allowed but the bash block is authoritative. The convention is documented in `AscendAgent/e2e/testing/CONVENTIONS.md`.

#### Scenario: Runner extracts pre-flight, tests, and pass criteria

- **WHEN** the runner reads `AscendAgent/e2e/testing/semantic-memory.md`
- **THEN** it identifies the `### Pre-flight` section and extracts every bash command from it
- **AND** it identifies each `### Test N — <name>` block in numeric order
- **AND** it extracts the canonical bash block from each test
- **AND** it extracts each pass criterion as a separate item (bullet OR sentence) for independent judgement

#### Scenario: Doc that violates the convention surfaces a usable error

- **WHEN** a test doc is missing `### Pre-flight` or has zero `### Test N — ...` headings
- **THEN** the runner records the run as `INCONCLUSIVE` overall with reason `doc_convention_violation`
- **AND** the run output names the missing section so the doc can be fixed

### Requirement: Fixed-shape evidence bundle per judge call

For each pass criterion, the runner SHALL build an evidence bundle containing the HTTP request (method, URL, headers, body excerpt truncated to 2 KB), the HTTP response (status, body excerpt truncated to 4 KB), and a timestamp-windowed agent log slice covering `[T-5s, T+25s]` capped at 200 lines. Side-effect blocks (Qdrant, Postgres, Redis state) SHALL be populated only when the test doc's pass criterion explicitly names that source — the runner SHALL NOT invent state queries.

#### Scenario: Log slice is timestamp-windowed, not match-based

- **WHEN** the runner issues a request at time T
- **THEN** the agent log lines included in the evidence bundle are exactly those with timestamps in `[T-5s, T+25s]`
- **AND** if more than 200 lines fall in that window, the bundle keeps the last 200 and records `evidence_truncated: true`

#### Scenario: Side-effect block populated only when the test asks

- **WHEN** a test's pass criterion mentions "Confirm in Qdrant" or "Verify in Postgres"
- **THEN** the runner runs the corresponding bash block (curl to Qdrant, psql query) and stores the result in `evidence.side_effects`
- **WHEN** a test does not mention a side-effect source
- **THEN** the runner does NOT query Qdrant / Postgres / Redis on its own

### Requirement: Determinism via temperature 0 with retry-on-disagreement

Judge calls SHALL run at `temperature=0` and `top_p=1` (where the model honors it). Each criterion SHALL be judged once. `FAIL` and `INCONCLUSIVE` verdicts SHALL be re-judged exactly once with the same evidence; if the second verdict matches the first, the runner keeps it; if they disagree, the criterion is marked `INCONCLUSIVE` with reason `judge_disagreement` and both verdicts SHALL appear in the run output. `PASS` verdicts SHALL NOT be retried.

#### Scenario: Stable PASS is kept on first call

- **WHEN** the judge returns `PASS` on a criterion
- **THEN** the runner records the verdict and moves on without retry

#### Scenario: Disagreement on retry escalates to INCONCLUSIVE

- **WHEN** the first judge call returns `FAIL`
- **AND** the retry returns `PASS` (or `INCONCLUSIVE`)
- **THEN** the criterion is recorded as `INCONCLUSIVE` with reason `judge_disagreement`
- **AND** both verdicts (`FAIL` then `PASS`) are quoted in the run output

### Requirement: Three-bucket failure semantics — PASS / FAIL / INCONCLUSIVE

The runner SHALL classify every criterion into one of three buckets. `PASS` means evidence shows the criterion was met. `FAIL` means evidence shows it was NOT met. `INCONCLUSIVE` means evidence was incomplete, contradictory, or the runner's environment failed (closed set of reasons: `pre_flight_unreachable`, `log_unreadable`, `judge_disagreement`, `judge_unparseable`, `evidence_truncated`, `doc_convention_violation`). Overall run verdict SHALL be `PASS` only when every criterion is `PASS`; one or more `FAIL` SHALL produce overall `FAIL`; otherwise (no fails, ≥1 inconclusive) overall SHALL be `INCONCLUSIVE`.

#### Scenario: One inconclusive does not turn a passing run into a fail

- **WHEN** a 3-test run produces `PASS`, `PASS`, `INCONCLUSIVE`
- **THEN** the overall verdict is `INCONCLUSIVE`
- **AND** the run output lists the inconclusive criterion separately so a human can investigate

#### Scenario: Pre-flight unreachable fails the whole doc as INCONCLUSIVE

- **WHEN** any pre-flight curl returns connection-refused or non-2xx
- **THEN** the runner does NOT proceed to the test blocks
- **AND** the overall verdict is `INCONCLUSIVE` with reason `pre_flight_unreachable`

### Requirement: Cost cap with WARN and ABORT thresholds

The runner SHALL compute an estimated cost per judge call from token counts and per-model pricing, sum across all anticipated criteria at run start, and apply two thresholds. WARN at estimated > $0.05 (informational; interactive runs ask for confirmation). ABORT at actual > $0.50 mid-run; the runner SHALL stop after the in-flight criterion, write a partial run output marked `ABORTED`, and exit non-zero. A per-run override `--max-cost-usd <n>` SHALL raise the abort threshold for one run only.

#### Scenario: Pre-run cost estimate is printed

- **WHEN** the runner starts a session
- **THEN** it prints `[e2e-runner] estimated cost: $X.XX across N criteria` before any judge call

#### Scenario: ABORT mid-run produces a partial run output

- **WHEN** actual cost crosses $0.50 during a run
- **THEN** the runner finishes the in-flight criterion's judge call
- **AND** it writes the partial output with `aborted: true` in the YAML frontmatter
- **AND** any criteria not yet executed are listed as `aborted_before_execution`

### Requirement: Default judge model with per-run override

Default judge model SHALL be Anthropic Haiku 4.5. The runner SHALL accept `--judge-model <id>` to override per run. Supported alternates SHALL include at minimum `gemini-3.1-flash` and `gpt-5-mini` so the judge family can differ from the model under test (avoiding correlated failure when the agent under test is Claude itself).

#### Scenario: Default model when no flag is passed

- **WHEN** the runner is invoked without `--judge-model`
- **THEN** judge calls go to `claude-haiku-4-5`
- **AND** the run output's frontmatter records `judge_model: claude-haiku-4-5`

#### Scenario: Override sticks for one run only

- **WHEN** the runner is invoked with `--judge-model gemini-3.1-flash`
- **THEN** every judge call in that run goes to Gemini Flash
- **AND** the next run without the flag reverts to Haiku

### Requirement: Local-only execution against a reachable stack

The runner SHALL run locally (Claude Code session or sub-agent on the developer's machine). The runner SHALL NOT manage the stack lifecycle (no `docker compose up`, no `./gradlew bootRun`). The only contract is that the URLs named in the test doc resolve over HTTP from the runner's host. If the stack is unreachable, the run SHALL be `INCONCLUSIVE` at pre-flight, never `FAIL`.

#### Scenario: Stack down at runner start

- **WHEN** the runner attempts pre-flight against a stopped AscendAgent
- **THEN** the curl to `localhost:9917/` fails with connection-refused
- **AND** the runner records overall verdict `INCONCLUSIVE` with reason `pre_flight_unreachable`
- **AND** the runner does NOT attempt to start the stack itself

### Requirement: Run output records auditability metadata

Each run SHALL produce one markdown file at `AscendAgent/e2e/runs/<UTC-yyyymmdd-hhmmss>-<capability>.md` with YAML frontmatter recording: `judge_prompt_sha`, `judge_model`, `runner_version`, `test_doc_sha`, `started_at_utc`, `finished_at_utc`, `overall_verdict`, `aborted` (boolean). The body SHALL contain per-test sections with verdict, evidence_cited quotes, judge reasoning, and (if any inconclusive) a separate "Inconclusive" section listing each inconclusive criterion with its reason.

#### Scenario: Run output frontmatter is complete

- **WHEN** a run completes
- **THEN** the output file's YAML frontmatter contains all eight fields above
- **AND** `judge_prompt_sha` matches `git rev-parse HEAD:AscendAgent/e2e/judge-prompt.md` at run start

#### Scenario: Inconclusive criteria surface separately from passes and fails

- **WHEN** a run has at least one `INCONCLUSIVE` criterion
- **THEN** the run output contains an `## Inconclusive` section listing each one with its closed-set reason code
- **AND** the inconclusive criteria are NOT listed under PASS or FAIL sections