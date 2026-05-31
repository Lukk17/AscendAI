# MCP transcribe_openai happy path: e2e test

## What this verifies

- The MCP `initialize` handshake against `POST /mcp` returns HTTP 200 with an `Mcp-Session-Id` header.
- A subsequent `tools/call` for `transcribe_openai` with `audio_uri="file:///fixtures/meeting-clip.wav"`,
  `model="whisper-1"`, `language="en"` returns HTTP 200.
- The JSON-RPC `result.content` array contains one entry of `type="text"`; the entry's `text` parses as JSON.
- The parsed JSON payload has `source="openai"`, `model="whisper-1"`, `language="en"`, and a `transcription` string
  containing at least one of the canary substrings `Q3`, `Acme`, `Adam`, `Friday`, or `migration` (case-insensitive).
- The MCP tool reaches the AudioScribe container, resolves the `file://` URI against the bind-mounted
  `/fixtures` volume, then forwards the audio bytes to the OpenAI Whisper API — proves the full MCP →
  download_service → OpenAI path works end-to-end.
- The request consumes paid OpenAI quota.

## Prerequisites

Check Bruno CLI is installed.

```powershell
bru --version
```

Expect a version string.

Check the AudioScribe server is reachable.

```powershell
curl -fsS http://localhost:7017/health
```

Expect HTTP 200 with `{"status":"ok","service":"AudioScribe"}`.

Check the AudioScribe container has `OPENAI_API_KEY` configured.

```powershell
docker exec audio-scribe printenv OPENAI_API_KEY
```

Expect a non-empty string.

Check the fixtures directory is bind-mounted into the container at `/fixtures`. The committed `docker-compose.yaml`
does NOT mount the fixtures path; create or extend `docker-compose.override.yaml` next to it before running this
test:

```yaml
services:
  audio-scribe:
    volumes:
      - D:/Development/projekty-IT/AscendAI/AudioScribe/e2e/fixtures:/fixtures:ro
```

Recreate the container with the override applied, then confirm the mount is visible:

```powershell
docker exec audio-scribe ls /fixtures/meeting-clip.wav
```

Expect the path to be listed. If the file is missing, record it per `AudioScribe/e2e/fixtures/README.md` before
continuing.

## Reset state

Delete any stale `.md` cache entries from prior runs to keep `/tmp` clean.

```powershell
docker exec audio-scribe sh -c "rm -f /tmp/transcript_*.md"
```

## Run

```powershell
cd docs/api/request/AscendAI
```

**Step 1.** Open an MCP session via the `initialize` handshake. Capture the `Mcp-Session-Id` value from the response headers.

```powershell
curl.exe -fsS -i -X POST http://localhost:7017/mcp -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"initialize\",\"params\":{\"protocolVersion\":\"2025-11-25\",\"capabilities\":{},\"clientInfo\":{\"name\":\"e2e\",\"version\":\"0.1.0\"}}}"
```

Look for `Mcp-Session-Id: <uuid>` in the response. Use that UUID as the value of the `mcp_session_id` env-var in the next step(s).

**Step 2.** Send the tool call with the captured session ID injected:

```powershell
bru run "transcribe/testing/mcp-transcribe.yml" --env ascend-local --env-var "mcp_session_id=<paste UUID from step 1>"
```

## Expected

Step 1 returns HTTP 200 with an `Mcp-Session-Id` header.

Step 2 returns HTTP 200. The JSON-RPC `result.content` array satisfies:

- Length is exactly 1.
- The first entry has `type="text"`.
- The first entry's `text` is a non-empty string that parses as JSON.

The parsed JSON object satisfies:

- `source` equals `"openai"`.
- `model` equals `"whisper-1"`.
- `language` equals `"en"`.
- `transcription` is a non-empty string.
- `transcription` lowercased contains at least one of: `Q3`, `Acme`, `Adam`, `Friday`, or `migration`.

The JSON-RPC `result.is_error` is either absent or `false` (the AudioScribe MCP wrapper sets `is_error=true` only on
the error path).

## Fixtures

- `AudioScribe/e2e/fixtures/meeting-clip.wav` — same fixture used by spec `2-transcribe-openai-test.md`. The MCP
  test references it via the in-container path `file:///fixtures/meeting-clip.wav`, which resolves to the
  bind-mounted host directory documented in **Prerequisites**.
