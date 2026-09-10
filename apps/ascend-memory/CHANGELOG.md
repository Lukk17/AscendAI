# Changelog: ascend-memory

All notable changes to this project are documented in this file. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project adheres to
[Semantic Versioning](https://semver.org/). Newest entry on top; the topmost `## [x.y.z]`
version is the current one. The release workflow reads it for the image tag and to guard
against re-publishing an already-released version, so keep it at the top and bump it
before every release. The `version` in `pyproject.toml` is a cosmetic label the release
workflow does not read; if the two ever disagree, this file wins for release purposes.

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
