# Changelog: ascend-weather-mcp

All notable changes to this project are documented in this file. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project adheres to
[Semantic Versioning](https://semver.org/). Newest entry on top; the topmost `## [x.y.z]`
version is the current one. The release workflow reads it for the image tag and to guard
against re-publishing an already-released version, so keep it at the top and bump it
before every release. The `version` in `build.gradle.kts` is a cosmetic label the release
workflow does not read; if the two ever disagree, this file wins for release purposes.

## [0.0.4] - 2026-10-01

### Fixed
- The descriptions of weather_forecast, weather_air_quality and weather_geocode, which every MCP client
  shows to its model, used en dashes in their ranges (1-16 days, 1-10 candidates) and an em dash in the
  air quality text. They use plain hyphens now. Only the punctuation changed.
- AGENTS.md named Spring Boot 3.5.4. The build uses 3.5.14, and the text says so now.
- Dashes in comments, test comments, documentation and the end-to-end specs and templates are plain
  hyphens or commas now. End-to-end spec 7 writes the US longitude band as between -95.0 and -75.0, where
  the dash read as a minus sign.
- The end-to-end README points at this module's own entry under the service suites of
  docs/E2E_RUN_SCENARIOS.md.

## [0.0.3]

### Fixed
- End-to-end spec 1 claimed a steady-state latency under 50 milliseconds. Three raw curl calls
  measured 208 to 223 milliseconds, so the spec now states the measured 210 millisecond figure
  and keeps the 500 millisecond investigate-before-pass threshold against a raw curl call.
- The PowerShell form of the MCP specs' JSON-body curl.exe blocks failed on pwsh 7.6.5 with a
  nested brace error and HTTP 400. Those blocks pass the body single-quoted now.
- The version in build.gradle.kts lagged this changelog at 0.0.1, and the advertised MCP server
  version in application.yaml was a hardcoded copy of it. The build file says 0.0.3 and the yaml
  reads the build version through the placeholder line 17 already used.
- The forecast Bruno request never checked that the first forecast date is today or tomorrow in
  UTC, which end-to-end spec 4 requires. It does now. The two current-weather requests were checked
  against spec 7 in the same pass and already asserted the country code and the coordinate bands.

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
