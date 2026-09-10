# Changelog: ascend-ocr

All notable changes to this project are documented in this file. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project adheres to
[Semantic Versioning](https://semver.org/). Newest entry on top; the topmost `## [x.y.z]`
version is the current one. The release workflow reads it for the image tag and to guard
against re-publishing an already-released version, so keep it at the top and bump it
before every release. The `version` in `pyproject.toml` is a cosmetic label the release
workflow does not read; if the two ever disagree, this file wins for release purposes.

## [0.2.1]

### Changed
- The compose service sets OCR_PAGE_TIMEOUT_SECONDS to 150 beside the existing OCR_REQUEST_TIMEOUT
  of 300. Without it a one-page document kept the 120 second default budget and timed out on runs
  measured at up to 139 seconds.

### Fixed
- End-to-end spec 10 piped through jq without listing it as a prerequisite. It is listed now, with
  a version check.
- The MCP specs and templates described the session id as a UUID. The value is a 32 character
  hexadecimal id without hyphens, and the wording now says so.
- The Bruno ready request accepted an empty version string, and the Polish OCR request accepted
  any language. They now assert a non-empty version and a language equal to pl.
- The PowerShell form of the MCP specs' JSON-body curl.exe blocks failed on pwsh 7.6.5 with a
  nested brace error and HTTP 400. Those blocks pass the body single-quoted now.
- The deployment view claimed compose leaves MCP_ALLOWED_HOSTS unset. It names the three hosts
  compose sets.
- The version in pyproject.toml, AGENTS.md, the service banner and the constraints document
  lagged this changelog at 0.1.0. All four say 0.2.1, and the service banner now reads its
  version from the installed package metadata at import time instead of a hardcoded literal,
  so pyproject.toml is the only place the version lives.
- The engine-bound end-to-end specs 2, 3, 4 and 6 were allowed to interleave with other runners.
  The engine is single-threaded and a loaded host took the same fixture from 59.2 to 160.9
  seconds on 2026-09-10, past the raised per-page budget, so each of the four now runs alone with
  no runner of any suite active. The README table and each spec's Concurrency section say so.
- End-to-end spec 2 described its fixture as a single 120 point line while the response carries
  about 30 wrapped body lines. The description now matches the page-1 screenshot the fixture is.
- The unsupported-MIME Bruno request sent the text fixture with its real content type, so it
  never exercised the header lie spec 12 describes. The file part now declares image/png.

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
