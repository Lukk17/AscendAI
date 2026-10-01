# Changelog: ascend-memory

All notable changes to this project are documented in this file. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project adheres to
[Semantic Versioning](https://semver.org/). Newest entry on top; the topmost `## [x.y.z]`
version is the current one. The release workflow reads it for the image tag and to guard
against re-publishing an already-released version, so keep it at the top and bump it
before every release. The `version` in `pyproject.toml` is a cosmetic label the release
workflow does not read; if the two ever disagree, this file wins for release purposes.

## [0.1.3] - 2026-10-01

### Changed
- OpenTelemetry goes from 1.42.1 to 1.44.0 (opentelemetry-api, opentelemetry-sdk,
  opentelemetry-exporter-otlp) and opentelemetry-instrumentation-fastapi from 0.63b1 to 0.65b0.
- httpx2 2.13.1 joins the development extras, because Starlette's test client, which the readiness tests
  use, now asks for httpx2 instead of httpx.
- The source is reformatted with ruff format at the configured 110 character line length. No behaviour
  changes.
- The test suite carries type annotations on its fixtures and tests, and patches mem0 and httpx directly
  instead of through the names the service modules import.

### Fixed
- The end-to-end prerequisites said the embedding backend could be LM Studio or OpenAI. Every insert and
  search request in the suite pins provider=openai, so the list now requires OpenAI and OPENAI_API_KEY on
  the container and says LM Studio is not needed.
- AGENTS.md gained the Linux and macOS commands beside the Windows ones, and the README gained a step that
  runs the tests with the 100 percent branch coverage gate.
- The install commands quote ".[dev]", because zsh reads an unquoted [dev] as a glob.
- Dashes in comments, docstrings, documentation, the Dockerfile, the agent skill file and the end-to-end
  specs are plain hyphens or commas now.
- The end-to-end README points at this module's own entry under the service suites of
  docs/E2E_RUN_SCENARIOS.md.

## [0.1.2]

### Fixed
- The MCP specs and templates described the session id as a UUID. The value is a 32 character
  hexadecimal id without hyphens, and the wording now says so.
- The PowerShell form of the MCP specs' JSON-body curl.exe blocks failed on pwsh 7.6.5 with a
  nested brace error and HTTP 400. Those blocks pass the body single-quoted now.
- The version in pyproject.toml and AGENTS.md lagged this changelog at 0.1.0. Both say 0.1.2.
- The MCP tools/list Bruno request only checked the four tool names, while end-to-end spec 4
  requires each tool to advertise a non-empty input schema, user_id on the three user-scoped tools
  and memory_id without user_id on memory_delete. The script asserts all of that now.

## [0.1.1]

### Fixed
- The documentation claimed three environment variables the code has never read, and named a
  Qdrant collection that exists only as an empty leftover while the live data sits in the
  dimension-suffixed collections. It now describes the provider table the code actually uses,
  which pins the embedding model, the dimension count and the collection per provider.
- Every command in the end-to-end specifications gained a Unix shell form beside the PowerShell
  one, so the runner no longer improvises a translation on each run, and the requests those specs
  drive assert response bodies rather than only a status code.

## [0.1.0]

### Added
- Changelog introduced for this module. No prior per-version history was tracked before
  this file, so consult git history for changes before this entry. This module is a
  semantic memory service exposing REST and MCP interfaces for storing, searching, and
  managing user-scoped memories, backed by mem0ai and a Qdrant vector database.
