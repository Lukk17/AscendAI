# Changelog: ascend-ocr

All notable changes to this project are documented in this file. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project adheres to
[Semantic Versioning](https://semver.org/). Newest entry on top; the topmost `## [x.y.z]`
version is the current one. The release workflow reads it for the image tag and to guard
against re-publishing an already-released version, so keep it at the top and bump it
before every release. The `version` in `pyproject.toml` is a cosmetic label the release
workflow does not read; if the two ever disagree, this file wins for release purposes.

## [0.2.0]

### Fixed
- The upload endpoint declared its language parameter without a form marker, so the web framework
  treated it as a query parameter and silently discarded the multipart field every documented
  client sends. Every request ran the English model whatever language it asked for. The parameter
  now reads the form body, which is what this module's contract always specified. The MCP tool
  surface takes its arguments from the request body and was never affected.

### Changed
- ENGINE_CACHE_MAX_SIZE now defaults to 2 rather than 8, matching the two language models the
  image actually ships. That takes roughly a gigabyte off the worst-case memory estimate for
  capacity nothing could use. A workload alternating a third language now pays an engine load on
  each switch instead of keeping that engine resident.

## [0.1.0]

### Added
- Changelog introduced for this module. No prior per-version history was tracked before
  this file, so consult git history for changes before this entry. This module wraps the
  PaddleOCR library behind a FastAPI REST API and a FastMCP server for multi-language
  text extraction from images and PDFs.
