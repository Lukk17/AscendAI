# Transcribe OpenAI happy path: e2e test

## What this verifies

- `POST /api/v1/transcribe/openai` with `meeting-clip.wav` (multipart-form `file`), `stream=false`, `language=en`
  returns HTTP 200.
- The response `Content-Type` header is `text/markdown` (the endpoint serves a `FileResponse` with the `.md`
  transcript on the `stream=false` happy path).
- The response body (the `.md` transcript content) contains at least one of the canary substrings `Q3`, `Acme`, `Adam`, `Friday`, or `migration` (case-insensitive). The asserted phrase is the invented sentence recorded into
  `meeting-clip.wav`; at least one distinctive word being present proves the audio bytes were actually transcribed
  through the OpenAI Whisper API rather than served from a cache or canned response.
- The request consumes paid OpenAI quota — the test is not safe to run with `OPENAI_API_KEY` unset; the endpoint
  short-circuits to HTTP 500 with `"OPENAI_API_KEY is not configured on the server."` when the key is missing.

## Prerequisites

Check Bruno CLI is installed.

```bash
bru --version
```

Expect a version string.

Check the ascend-audio-scribe server is reachable.

```bash
curl -fsS http://localhost:7017/health
```

Expect HTTP 200 with `{"status":"ok","service":"ascend-audio-scribe"}`.

Check the ascend-audio-scribe container has `OPENAI_API_KEY` configured.

```bash
docker exec ascend-audio-scribe sh -c '[ -n "$OPENAI_API_KEY" ] && echo present || echo missing'
```

Expect `present`. Never `printenv` the raw value. This check proves the variable is set without printing it. If
`missing`, set `OPENAI_API_KEY` in the host environment / `.env` and recreate the container.

Check outbound HTTPS to OpenAI works from the ascend-audio-scribe container.

```bash
docker exec ascend-audio-scribe curl -fsS -o /dev/null -w "%{http_code}\n" https://api.openai.com/v1/models
```

Expect HTTP 200 (when the key is valid) or HTTP 401 (when the key is unset/invalid — confirms egress works even if
the key check itself failed).

Check the canary fixture is present.

**PowerShell:**

```powershell
dir ascend-audio-scribe\e2e\fixtures\meeting-clip.wav
```

**Unix:**

```bash
ls -lh ascend-audio-scribe/e2e/fixtures/meeting-clip.wav
```

Expect the file to exist and be at least 1 KB. If missing, record the canary phrase per
`apps/ascend-audio-scribe/e2e/fixtures/README.md` before continuing.

## Reset state

Delete any stale `transcript_openai.md` cache entries from prior runs to keep `/tmp` clean and rule out a stale
download contaminating the assertion.

```bash
docker exec ascend-audio-scribe sh -c "rm -f /tmp/transcript_*.md"
```

## Run

Single Bruno request.

```bash
cd docs/api/request/AscendAI
```

```bash
bru run "transcribe/testing/transcribe-openai-canary.yml" --env ascend-local
```

## Expected

The Bruno call returns HTTP 200.

The response matches:

- `Content-Type` response header starts with `text/markdown`.
- `Content-Disposition` response header is `attachment; filename="transcript_openai.md"`.
- Response body length is at least 5 bytes (an empty Whisper result returns an empty string; a non-empty body proves
  the provider returned a transcription).
- Response body lowercased contains at least one of: `Q3`, `Acme`, `Adam`, `Friday`, or `migration`.

## Fixtures

- `apps/ascend-audio-scribe/e2e/fixtures/meeting-clip.wav`: 9.48 s mono audio at 24 kHz, spoken English line
  *"I think we should defer the migration to Q3 because the contract with Acme renews then. Adam, can you confirm the renewal date by Friday?"* Despite the `.wav` extension, this is a LAME-encoded MP3 elementary stream, not a RIFF WAV file. See [../fixtures/README.md](../fixtures/README.md) for the full `ffprobe` breakdown.
