# ADR-004: Audacity zip-slip + ffmpeg argv guard

**Date**: 2026-06-01
**Status**: Accepted

---

## Context

Audacity projects arrive as user-supplied `.zip` files (`.aup` XML + `_data/` directory of tracks). Two attack
vectors were unguarded:

1. **Zip slip**: `zipfile.ZipFile.extractall()` writes each member to its declared path. A malicious zip with
   members like `../../../etc/cron.d/payload`, absolute Windows paths, or symlinks could overwrite arbitrary host
   files.
2. **ffmpeg argv injection**: track filenames extracted from the zip are passed positionally to `subprocess.run`. A
   filename starting with `-` is interpreted by ffmpeg as a flag — and ffmpeg supports `http://`, `concat:`, `lavfi`
   protocols that turn into SSRF / arbitrary-command vectors.

Plus `subprocess.run` calls had no `timeout=`, so a wedged ffmpeg (corrupt input, network mount stall) could block
the worker thread indefinitely.

---

## Decision

`audacity_parser._safe_zip_extract` replaces `extractall()`:

- Iterates `zip_ref.infolist()` and resolves each member's target via `(root / member.filename).resolve()`. Rejects
  any target whose `is_relative_to(root)` is False.
- Sums uncompressed sizes against `settings.MAX_ZIP_UNCOMPRESSED_BYTES` (5 GiB) while iterating; trips
  `FileSizeExceededError` early.
- Members whose basename starts with `-` are renamed to `_dash_<uuid>.<ext>` before write, so ffmpeg can never see a
  flag-shaped argv. Directory entries are dirified-and-validated separately. Symlinks and drive-letter paths are
  rejected.

`_run_subprocess` wraps every ffmpeg / ffprobe call with `timeout=settings.FFMPEG_TIMEOUT_SECONDS` (default 180 s)
and records outcome in `FFMPEG_INVOCATIONS_TOTAL{binary, outcome=success|timeout|error}` Prometheus counter. Untrusted
XML is parsed with `defusedxml.ElementTree.parse` rather than the stdlib (billion-laughs / XXE defence).

(`src/transcription/audacity_parser.py`)

---

## Alternatives Considered

### Alternative 1: Continue using `extractall()` + trust input

- **Pros**: Less code.
- **Cons**: Zip slip is a published OWASP attack class. Any vetting we offload to "trust the upload" is misplaced.

### Alternative 2: Use a sandboxing tool (firejail, gVisor)

- **Pros**: Defence in depth.
- **Cons**: Not portable to the docker-compose deployment model used here.

---

## Consequences

### Positive

- Zip slip class eliminated.
- ffmpeg argv injection eliminated (filenames are renamed before subprocess call).
- Hung ffmpeg can't pin a worker thread forever.
- XXE / billion-laughs class eliminated by `defusedxml`.
- Observability: every ffmpeg invocation is counted with its outcome.

### Negative

- Slightly slower extraction (per-member validation vs single `extractall` call).
- The cap on uncompressed size means a legitimately huge multi-hour Audacity project might be rejected; the 5 GiB
  cap matches the user's stated preference and is configurable.
