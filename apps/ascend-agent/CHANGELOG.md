# Changelog: ascend-agent

All notable changes to this project are documented in this file. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project adheres to
[Semantic Versioning](https://semver.org/). Newest entry on top; the topmost `## [x.y.z]`
version is the current one. The release workflow reads it for the image tag and to guard
against re-publishing an already-released version, so keep it at the top and bump it
before every release. The `version` in `build.gradle.kts` is a cosmetic label the release
workflow does not read; if the two ever disagree, this file wins for release purposes.

## [0.1.0]

### Fixed
- Tool discovery over the Model Context Protocol ran every registered client through a single
  stream, so the first client holding a session its server no longer recognised aborted discovery
  for all of them and the caller got an unexplained internal error. On a stack left idle for hours
  that cost one failed request per registered server before anything worked. Discovery now runs
  each client in isolation, reconnects and retries once when one fails, and drops that one
  server's tools with a warning instead of failing the whole request. A server that is genuinely
  down now costs you its tools rather than your prompt.
- The client that calls ascend-ocr sent the requested language as a query parameter. It now sends
  it in the multipart body, which is what the OCR contract always said. This half has to ship with
  the ascend-ocr fix in 0.2.0, since either one alone leaves the language silently ignored.

### Changed
- The module answers to one name. Its compose service, container, hostname and directory are all
  ascend-agent now, and the published image is lukk17/ascend-ai-ascend-agent. Anything pinned to
  the older names has to be updated. The Java package was deliberately left alone, because
  renaming a package is a source refactor with a different risk profile and nobody asked for one.

## [0.0.1]

### Added
- Changelog introduced for this module. No prior per-version history was tracked before
  this file, so consult git history for changes before this entry. This module is the
  central Spring Boot API gateway for the AscendAI platform: it routes prompts to
  multiple AI providers with per-request model selection, runs a Soft-RAG pipeline with
  thresholded retrieval, integrates external tools via MCP, and manages chat history
  across Redis and PostgreSQL.
