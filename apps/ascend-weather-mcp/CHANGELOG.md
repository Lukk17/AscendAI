# Changelog: ascend-weather-mcp

All notable changes to this project are documented in this file. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project adheres to
[Semantic Versioning](https://semver.org/). Newest entry on top; the topmost `## [x.y.z]`
version is the current one. The release workflow reads it for the image tag and to guard
against re-publishing an already-released version, so keep it at the top and bump it
before every release. The `version` in `build.gradle.kts` is a cosmetic label the release
workflow does not read; if the two ever disagree, this file wins for release purposes.

## [0.0.2]

### Fixed
- The documentation described this server as having a single tool when it registers five, and
  called that one by a name the server has never used, so anyone following the docs would have
  failed on the first call. All five tools are now documented under their registered names.
  weather_historical has no end-to-end spec and no request in the shared collection, and the
  documentation says so rather than implying coverage that does not exist.
- Every command in the end-to-end specifications gained a Unix shell form beside the PowerShell
  one, and the requests those specs drive assert response bodies rather than only a status code.

## [0.0.1]

### Added
- Changelog introduced for this module. No prior per-version history was tracked before
  this file, so consult git history for changes before this entry. This module is a
  standalone MCP server built with Spring AI that serves current weather data to the
  ascend-agent over SSE.
