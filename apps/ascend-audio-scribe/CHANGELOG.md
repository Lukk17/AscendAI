# Changelog — ascend-audio-scribe

All notable changes to this project are documented in this file. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project adheres to
[Semantic Versioning](https://semver.org/). Newest entry on top; the topmost `## [x.y.z]`
version is the current one. The release workflow reads it for the image tag and to guard
against re-publishing an already-released version, so keep it at the top and bump it
before every release. The `version` in `pyproject.toml` is a cosmetic label the release
workflow does not read; if the two ever disagree, this file wins for release purposes.

## [0.9.0]

### Added
- Changelog introduced for this module. No prior per-version history was tracked before
  this file, so consult git history for changes before this entry. This module is a
  speech-to-text microservice that selects a transcription backend per request (local
  faster-whisper, the OpenAI API, or Hugging Face Inference), including multi-track
  Audacity project transcription with speaker-tagged chronological merging.
