# ai-driven-e2e-runner Specification

## Purpose

Defines the contract that lets an AI agent (or a human) execute the AscendAgent's capability-level e2e suite end-to-end against a live stack, capture per-run evidence, and emit reviewable PASS/FAIL verdicts as committed markdown artifacts. Pass criteria are observable behavior — HTTP status, response-body content, persisted state in MinIO / Qdrant / Postgres — never log substrings.

## Requirements

### Requirement: Numbered immutable specs under `AscendAgent/e2e/testing/`

The system SHALL ship one capability spec per testable behavior under `AscendAgent/e2e/testing/`, named `<N>-<feature>-test.md`. The number prefix orders specs by setup cost (smallest first). Each spec is immutable across runs — the runner never edits it. Every spec follows the fixed template: **What this verifies / Prerequisites / Reset state / Run / Expected / Fixtures**.

#### Scenario: Specs are number-prefixed and immutable

- **WHEN** a contributor adds a new capability test
- **THEN** they create `<N>-<feature>-test.md` with the next unused number matching its setup cost
- **AND** they do NOT modify the file once specs and templates for prior tests have been published

#### Scenario: Every spec follows the fixed template

- **WHEN** a runner reads any `<N>-<feature>-test.md`
- **THEN** it finds the six sections in order: What this verifies, Prerequisites, Reset state, Run, Expected, Fixtures
- **AND** each Prerequisites and Reset-state command is in its own fenced code block with prose around it stating the success criterion

### Requirement: Sidecar tasks-template per spec

For every spec the system SHALL ship a paired `<N>-<feature>-tasks.template.md` file that lists each prerequisite check, reset command, run step, expected check, and verdict as a markdown checkbox. The template is immutable — runners never edit it in place. At the bottom the template carries a **Result summary** section ending with `Input tokens:`, `Output tokens:`, `Start (UTC):`, `End (UTC):`, `Duration:` fields the runner fills in, plus an **Additional tasks I did** section for out-of-spec work.

#### Scenario: Template mirrors its spec one-to-one

- **WHEN** a contributor adds `<N>-<feature>-test.md`
- **THEN** they also add `<N>-<feature>-tasks.template.md` with checkboxes covering every prerequisite, reset command, run step, and expected check in the spec
- **AND** the template includes the Result summary block with Input tokens / Output tokens / Start (UTC) / End (UTC) / Duration / Verdict / Additional tasks I did

### Requirement: Per-run records under `runs/` with timestamped filenames

For each execution the runner SHALL copy the matching template to `AscendAgent/e2e/testing/runs/<UTC-timestamp>_<N>-<feature>-tasks.md` (ISO 8601 with colons replaced by hyphens, e.g. `2026-05-12T17-23-36`). All five tests of one sweep SHALL share the same timestamp so a sweep groups by filename. Run records are gitignored by default; operators MAY force-add specific runs as audit artifacts.

#### Scenario: Sweep groups by shared timestamp

- **WHEN** a runner starts a full-suite sweep at UTC `2026-05-12T17:23:36`
- **THEN** each of the five test run records is named `2026-05-12T17-23-36_<N>-<feature>-tasks.md`
- **AND** every record uses the same timestamp prefix

#### Scenario: Runs are ignored by default

- **WHEN** a runner produces a new run record
- **THEN** `git status` does not list it as untracked because `AscendAgent/e2e/testing/runs/*` is gitignored (with `!.../runs/README.md` exception)
- **AND** the operator MAY `git add -f` a specific run record to ship it as an audit example

### Requirement: Behavior-only pass criteria — no log assertions

Every spec's **Expected** section SHALL assert only observable behavior — HTTP status codes, response-body content matches, persisted state in MinIO / Qdrant / Postgres / Redis. The spec SHALL NOT include assertions of the form "AscendAgent log shows ..." or any log-substring check. Log lines are diagnostic for triage, not pass criteria.

#### Scenario: Expected section names no log substrings

- **WHEN** a contributor opens any `<N>-<feature>-test.md`
- **THEN** the Expected section's assertions reference only HTTP status, response body fields, MinIO / Qdrant / Postgres state, or fixture content
- **AND** no assertion uses the form "log contains" or names an exact log-format string

### Requirement: Bruno CLI is the canonical invocation

The runner SHALL execute each test's HTTP request via the Bruno CLI (`bru run "ascend-agent/testing/<request>.yml" --env ascend-local`) against the collection root at `docs/api/request/AscendAI/`. The Bruno request file is the single source of truth for default provider, model, embedding provider, prompt text, and file attachments. Specs SHALL NOT duplicate these defaults — they refer to "the request's Bruno defaults".

#### Scenario: Spec does not override Bruno defaults

- **WHEN** a runner reads a Run step
- **THEN** the step is a single `bru run "..." --env ascend-local` invocation with no inline provider / model / prompt overrides
- **AND** changing the default in the Bruno file does NOT require any spec edit

### Requirement: Reset commands use `docker exec` when host CLIs are unavailable

When a reset step needs a CLI not guaranteed on the host (`redis-cli`, `psql`, `mc`), the spec SHALL invoke it via `docker exec <container> <cmd>` so the runner can execute the step on any host that has Docker installed without installing additional client tooling. Credentials needed inside containers SHALL be sourced from container env vars (e.g. `$MINIO_ROOT_USER`, `$MINIO_ROOT_PASSWORD`) via `docker exec <container> sh -c '...'` rather than hardcoded in the spec.

#### Scenario: MinIO alias uses container env vars

- **WHEN** a spec needs to register a MinIO `mc` alias
- **THEN** the command is `docker exec minio sh -c 'mc alias set local http://localhost:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD"'`
- **AND** the spec does NOT hardcode credential values inline; they live in `docker-compose.yaml` as the single source of truth

#### Scenario: Redis and Postgres resets run inside their containers

- **WHEN** a spec wipes Redis chat history or Postgres tables for a user
- **THEN** the commands are `docker exec redis redis-cli ...` and `docker exec postgres psql -U postgres -d ascend_ai -c '...'`
- **AND** the spec does NOT require the host shell to have `redis-cli` or `psql` installed

### Requirement: Async-write tolerance where applicable

Where the system writes asynchronously after an HTTP response returns (e.g. Mem0 writes to Qdrant async after `/api/v1/memory/insert`), the spec SHALL include an explicit short wait (`sleep 5` or equivalent) between the trigger and the verification step that reads the persisted state. The wait SHALL be commented in prose so a runner understands why.

#### Scenario: Semantic-memory spec waits before scrolling Qdrant

- **WHEN** the save turn returns HTTP 200
- **THEN** the spec instructs the runner to `sleep 5` before issuing the Qdrant scroll to verify the persisted points
- **AND** the prose explains the wait by naming the async write path

### Requirement: Run record captures token usage and total wall-clock duration

Each run record SHALL include, under **Result summary**, fields for `Input tokens` (prompt tokens consumed by the AI runner across the full test), `Output tokens` (completion tokens generated), `Start (UTC)` (ISO 8601 instant before the first prerequisite check), `End (UTC)` (instant after the last verification step), and `Duration` (HH:MM:SS = End − Start). Duration SHALL reflect total per-test wall-clock — prerequisites + reset + run + verify — not just the Bruno request duration.

#### Scenario: Duration captures the full test, not the Bruno call

- **WHEN** a Bruno call takes 5 seconds but the full test (prereqs + reset + Bruno + verification) takes 3 minutes
- **THEN** the run record's Duration field reads `00:03:00` or thereabouts, NOT `00:00:05`
- **AND** the runner records Start before any prerequisite check and End after the last verification

### Requirement: Sweep runs against a live stack the runner does not manage

The runner SHALL execute against a stack that is already running (`docker compose up -d` for backing services, `./gradlew bootRun` for the AscendAgent on host, or both fully containerized). The runner SHALL NOT start, stop, or recreate any container. Prerequisite check commands verify reachability; if any check fails the test halts and the run record's Verdict is FAIL with the failure recorded under Result summary.

#### Scenario: Pre-flight unreachable halts the run

- **WHEN** a prerequisite check (e.g. `curl http://localhost:9917/actuator/health`) fails
- **THEN** the runner stops the test and writes the failure into Result summary
- **AND** the runner does NOT attempt to start or restart any service

### Requirement: Standardized capability matrix

The five canonical capability tests SHALL be `1-weather-mcp-test.md` (MCP tool invocation), `2-image-description-test.md` (vision-capable model accepts an attached image), `3-summarization-test.md` (PDF parsed page-by-page through Docling and summarized from real content), `4-semantic-memory-test.md` (a fact stated in turn 1 is recalled in turn 2 from Qdrant via AscendMemory after chat history wipe), `5-rag-test.md` (Markdown / PDF / DOCX uploaded to MinIO, ingested into Qdrant, and surfaced in a later prompt with grounded citations).

#### Scenario: Capability matrix is documented in the e2e README

- **WHEN** a contributor opens `AscendAgent/e2e/README.md`
- **THEN** the capability table lists exactly these five entries with links to spec and template files
- **AND** "what it proves" describes the observable behavior each test exercises
