# Changelog: ascend-audio-scribe

All notable changes to this project are documented in this file. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project adheres to
[Semantic Versioning](https://semver.org/). Newest entry on top; the topmost `## [x.y.z]`
version is the current one. The release workflow reads it for the image tag and to guard
against re-publishing an already-released version, so keep it at the top and bump it
before every release. The `version` in `pyproject.toml` is a cosmetic label the release
workflow does not read; if the two ever disagree, this file wins for release purposes.

## [0.9.2]

### Fixed
- An upstream provider failure, such as a gateway timeout from the hosted inference endpoint, was
  answered with 400 as though the caller had sent a bad request. Both hosted providers now answer
  502 through a dedicated upstream exception.
- The egress probe in end-to-end spec 2 told the runner to expect 200 from a request that carries
  no key and therefore always answers 401. The prose now says 401, that the probe proves egress
  only, and that the key itself is proven by the run step.
- The PowerShell form of the MCP specs' JSON-body curl.exe blocks failed on pwsh 7.6.5 with a
  nested brace error and HTTP 400. Those blocks pass the body single-quoted now.
- The three transcribe Bruno requests asserted JSON keys on the markdown file the endpoints
  return. They assert the markdown attachment contract now.
- The three transcribe Bruno requests sent an accept header of application/json while the
  endpoints answer text/markdown. The header now asks for text/markdown.
- The version in pyproject.toml and the FastAPI application lagged this changelog at 0.9.0. Both
  say 0.9.2, and the FastAPI application now reads its version from the installed package
  metadata at import time instead of a hardcoded literal, so pyproject.toml is the only place
  the version lives.
- The egress probe in end-to-end spec 2 still passed -f to curl, which turns the 401 the prose
  expects into exit code 22 and hides the status. The probe drops -f and prints the status.

## [0.9.1]

### Fixed
- Every command in the end-to-end specifications gained a Unix shell form beside the PowerShell
  one, so the runner no longer improvises a translation on each run, and the requests those specs
  drive assert response bodies rather than only a status code.
- The readme pointed at a hand-maintained request file that has been removed. It points at the
  shared Bruno collection that replaced it.
- The Hugging Face transcription path read its token from the raw environment variable while the
  guard that checks that path read the settings object. A token supplied through .env passed the
  guard and then failed at the call. Both now read the settings object, making the credential one
  source of truth, and a token in .env works end to end.

## [0.9.0]

### Added
- Changelog introduced for this module. No prior per-version history was tracked before
  this file, so consult git history for changes before this entry. This module is a
  speech-to-text microservice that selects a transcription backend per request (local
  faster-whisper, the OpenAI API, or Hugging Face Inference), including multi-track
  Audacity project transcription with speaker-tagged chronological merging.
