# MCP transcribe_openai happy path: e2e test

## What this verifies

- The MCP `initialize` handshake against `POST /mcp` returns HTTP 200 with an `Mcp-Session-Id` header.
- A subsequent `tools/call` for `transcribe_openai` with `audio_uri="http://host.docker.internal:9070/e2e-fixtures/meeting-clip.wav"`,
  `model="whisper-1"`, `language="en"` returns HTTP 200.
- The JSON-RPC `result.content` array contains one entry of `type="text"`; the entry's `text` parses as JSON.
- The parsed JSON payload has `source="openai"`, `model="whisper-1"`, `language="en"`, and a `transcription` string
  containing at least one of the canary substrings `Q3`, `Acme`, `Adam`, `Friday`, or `migration` (case-insensitive).
- The MCP tool reaches the AudioScribe container, follows the docker-internal `http://minio:9000/...` URL to pull
  the audio bytes via its `download_service`, then forwards them to the OpenAI Whisper API — proves the full
  MCP → download_service → OpenAI path works end-to-end without any host-side file mount.
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

Check the fixture exists on the host.

```powershell
Test-Path AudioScribe/e2e/fixtures/meeting-clip.wav
```

Expect `True`.

Check MinIO is reachable on the host.

```powershell
curl -fsS http://localhost:9070/minio/health/live
```

Expect HTTP 200.

Check the MinIO `mc` client is available inside the `minio` container.

```powershell
docker exec minio mc --version
```

Expect a version string.

## Reset state

Register the MinIO alias inside the `minio` container (idempotent). Credentials are the single source of truth in
`docker-compose.yaml` under the `minio` service env (`MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD`). The command below
runs through `sh -c` so the env vars expand *inside* the container.

```powershell
docker exec minio sh -c 'mc alias set local http://localhost:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD"'
```

Create the dedicated `e2e-fixtures` bucket (idempotent).

```powershell
docker exec minio mc mb --ignore-existing local/e2e-fixtures
```

Open the bucket for anonymous downloads so AudioScribe can fetch the URL without an auth header.

```powershell
docker exec minio mc anonymous set download local/e2e-fixtures
```

Drop only this test's fixture from MinIO so re-upload is clean.

```powershell
docker exec minio mc rm --force local/e2e-fixtures/meeting-clip.wav
```

Copy the fixture from the host into the `minio` container.

```powershell
docker cp AudioScribe/e2e/fixtures/meeting-clip.wav minio:/tmp/meeting-clip.wav
```

Upload the fixture into the bucket.

```powershell
docker exec minio mc cp /tmp/meeting-clip.wav local/e2e-fixtures/meeting-clip.wav
```

Verify the object lands in the bucket.

```powershell
docker exec minio mc ls local/e2e-fixtures/meeting-clip.wav
```

Expect a single-line listing showing the object name.

Delete any stale `.md` cache entries from prior runs to keep `/tmp` clean inside the AudioScribe container.

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
  test references it via the docker-internal URL `http://host.docker.internal:9070/e2e-fixtures/meeting-clip.wav`, which
  AudioScribe's `download_service` resolves over HTTP using the docker-compose network.

## Concurrency

- **Mutates:** MinIO bucket `e2e-fixtures` (object key `meeting-clip.wav`); MinIO anonymous-download policy on the
  `e2e-fixtures` bucket; AudioScribe container `/tmp/transcript_*.md` cache entries.
- **Conflicts with:** any future test that also writes `e2e-fixtures/meeting-clip.wav` — none currently exist.
