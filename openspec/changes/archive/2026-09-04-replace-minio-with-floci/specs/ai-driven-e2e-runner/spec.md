# ai-driven-e2e-runner Delta Specification

## REMOVED Requirements

### Requirement: Reset commands use `docker exec` when host CLIs are unavailable

**Reason**: The requirement folded the object store in with Redis and Postgres and mandated `docker exec` plus the `mc` client for all three, with a scenario whose expected output was the literal command `docker exec minio sh -c 'mc alias set local http://localhost:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD"'`. The object store is now Floci, running in a compose project owned by a different repository. There is no container named `minio`, no `mc` binary, and no `MINIO_ROOT_USER` environment variable to source, so every step written to this contract fails. The Redis and Postgres half of the requirement is still correct and carries over unchanged into its replacement.

**Migration**: Replaced by "Reset commands use the host-published endpoint, or `docker exec` when a host CLI is unavailable" below. Redis and Postgres reset steps are unaffected and need no edit. Object-store steps move from `docker exec minio mc ...` to `curl` against `http://localhost:9070`, and the precondition health probe moves from `/minio/health/live` to `/_floci/health`.

## ADDED Requirements

### Requirement: Reset commands use the host-published endpoint, or `docker exec` when a host CLI is unavailable

When a reset step needs a CLI not guaranteed on the host (`redis-cli`, `psql`), the spec SHALL invoke it via `docker exec <container> <cmd>` so the runner can execute the step on any host that has Docker installed without installing additional client tooling. Credentials needed inside containers SHALL be sourced from container env vars via `docker exec <container> sh -c '...'` rather than hardcoded in the spec.

Object-store reset steps SHALL NOT use `docker exec`, and SHALL NOT assume any client binary. The object store is an S3-compatible endpoint published on the host at `http://localhost:9070` by a compose project this repository does not own, so neither its container name nor any client installed inside it is a stable contract. Reset, seed, and cleanup steps against it SHALL be plain HTTP requests to that endpoint using `curl`, which every runner host already has because the suite depends on it for health probes. Object-store health SHALL be probed at `GET http://localhost:9070/_floci/health`, whose JSON body reports per-service status including `"s3":"running"`.

Every destructive object-store step SHALL name the bucket it acts on literally. Deleting an object, emptying a prefix, and deleting a whole bucket are all permitted, provided the bucket named in the command is one this repository owns, meaning `knowledge-base` or `e2e-fixtures`. A step SHALL NOT issue any destructive operation that is not scoped to such a literal bucket name, which rules out wildcards, "delete every bucket", and any reset that lists the endpoint's buckets and removes what it finds. The reason is scope rather than destructiveness: the endpoint is shared with another repository's local development stack, so an unscoped command reaches buckets this repository never created.

#### Scenario: Object-store cleanup deletes one object over HTTP

- **WHEN** a spec needs to remove a single ingested document before a run
- **THEN** the command is a single `curl` issuing `DELETE http://localhost:9070/knowledge-base/documents/<key>`
- **AND** the spec does NOT require `mc`, the AWS CLI, or any container name

#### Scenario: Object-store precondition check targets the Floci health endpoint

- **WHEN** a spec's precondition step verifies the object store is up
- **THEN** the command is `curl -fsS http://localhost:9070/_floci/health`
- **AND** the spec does NOT reference `/minio/health/live`

#### Scenario: Reset never destroys a foreign bucket

- **WHEN** a contributor reads every reset and cleanup step across the e2e suite
- **THEN** every destructive step names its bucket literally, and that name is `knowledge-base` or `e2e-fixtures`
- **AND** no step lists the endpoint's buckets and deletes what it finds, and no step uses a wildcard in place of a bucket name

#### Scenario: Redis and Postgres resets run inside their containers

- **WHEN** a spec wipes Redis chat history or Postgres tables for a user
- **THEN** the commands are `docker exec redis redis-cli ...` and `docker exec postgres psql -U postgres -d ascend_ai -c '...'`
- **AND** the spec does NOT require the host shell to have `redis-cli` or `psql` installed

## MODIFIED Requirements

### Requirement: Behavior-only pass criteria — no log assertions

Every spec's **Expected** section SHALL assert only observable behavior, meaning HTTP status codes, response-body content matches, and persisted state in the S3-compatible object store / Qdrant / Postgres / Redis. The spec SHALL NOT include assertions of the form "AscendAgent log shows ..." or any log-substring check. Log lines are diagnostic for triage, not pass criteria.

#### Scenario: Expected section names no log substrings

- **WHEN** a contributor opens any `<N>-<feature>-test.md`
- **THEN** the Expected section's assertions reference only HTTP status, response body fields, object-store / Qdrant / Postgres state, or fixture content
- **AND** no assertion uses the form "log contains" or names an exact log-format string

### Requirement: Standardized capability matrix

The five canonical capability tests SHALL be `1-weather-mcp-test.md` (MCP tool invocation), `2-image-description-test.md` (vision-capable model accepts an attached image), `3-summarization-test.md` (PDF parsed page-by-page through Docling and summarized from real content), `4-semantic-memory-test.md` (a fact stated in turn 1 is recalled in turn 2 from Qdrant via AscendMemory after chat history wipe), `5-rag-test.md` (Markdown / PDF / DOCX uploaded to the object store, ingested into Qdrant, and surfaced in a later prompt with grounded citations).

#### Scenario: Capability matrix is documented in the e2e README

- **WHEN** a contributor opens `AscendAgent/e2e/README.md`
- **THEN** the capability table lists exactly these five entries with links to spec and template files
- **AND** "what it proves" describes the observable behavior each test exercises
