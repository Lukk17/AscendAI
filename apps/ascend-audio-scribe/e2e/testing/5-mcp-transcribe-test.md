# MCP transcribe_openai happy path: e2e test

## What this verifies

- The MCP `initialize` handshake against `POST /mcp` returns HTTP 200 with an `Mcp-Session-Id` header.
- A subsequent `tools/call` for `transcribe_openai` with `audio_uri="http://host.docker.internal:9070/e2e-fixtures/meeting-clip.wav"`,
  `model="whisper-1"`, `language="en"` returns HTTP 200.
- The JSON-RPC `result.content` array contains one entry of `type="text"`; the entry's `text` parses as JSON.
- The parsed JSON payload has `source="openai"`, `model="whisper-1"`, `language="en"`, and a `transcription` string
  containing at least one of the canary substrings `Q3`, `Acme`, `Adam`, `Friday`, or `migration` (case-insensitive).
- The MCP tool reaches the ascend-audio-scribe container, follows the `http://host.docker.internal:9070/...` URL back out to
  the host-published object store to pull the audio bytes via its `download_service`, then forwards them to the
  OpenAI Whisper API. Proves the full MCP to download_service to OpenAI path works end-to-end without any host-side
  file mount.
- The request consumes paid OpenAI quota.

## Prerequisites

Check Bruno CLI is installed.

```powershell
bru --version
```

Expect a version string.

Check the ascend-audio-scribe server is reachable.

```powershell
curl -fsS http://localhost:7017/health
```

Expect HTTP 200 with `{"status":"ok","service":"ascend-audio-scribe"}`.

Check the ascend-audio-scribe container has `OPENAI_API_KEY` configured.

```powershell
docker exec ascend-audio-scribe sh -c '[ -n "$OPENAI_API_KEY" ] && echo present || echo missing'
```

Expect `present`. Never `printenv` the raw value. This check proves the variable is set without printing it.

Check the fixture exists on the host.

```powershell
Test-Path apps/ascend-audio-scribe/e2e/fixtures/meeting-clip.wav
```

Expect `True`.

Check the object store is reachable on the host. It serves the S3 API on port 9070 without authentication, so
this spec needs no client, no credentials, and no container name.

```powershell
curl.exe -fsS http://localhost:9070/_floci/health
```

Expect HTTP 200 with `"s3":"running"` in the JSON body.

## Reset state

Every command below names the `e2e-fixtures` bucket literally. That bucket belongs to this repository. Never issue a
command that sweeps buckets instead of naming one, because the same object store also backs other projects on this
machine.

Create the dedicated `e2e-fixtures` bucket. The call is idempotent: an existing bucket answers HTTP 200 exactly like a
freshly created one.

```powershell
curl.exe -sS -o NUL -w "%{http_code}\n" -X PUT "http://localhost:9070/e2e-fixtures"
```

Expect `200`.

Drop only this test's fixture so the re-upload is clean. A key that is already gone also returns HTTP 204, so the step
is safe to re-run.

```powershell
curl.exe -fsS -X DELETE "http://localhost:9070/e2e-fixtures/meeting-clip.wav"
```

Upload the fixture straight from the host. No client and no intermediate container copy: the S3 endpoint takes the
bytes on a plain `PUT`.

```powershell
curl.exe -sS -o NUL -w "%{http_code}\n" -X PUT -H "Content-Type: audio/mpeg" --data-binary "@apps/ascend-audio-scribe/e2e/fixtures/meeting-clip.wav" "http://localhost:9070/e2e-fixtures/meeting-clip.wav"
```

Expect `200`.

Verify the object lands in the bucket.

```powershell
curl.exe -fsS "http://localhost:9070/e2e-fixtures?list-type=2&prefix=meeting-clip"
```

Expect a `ListBucketResult` carrying `<Key>meeting-clip.wav</Key>` with a `<Size>` of `56880`.

Delete any stale `.md` cache entries from prior runs to keep `/tmp` clean inside the ascend-audio-scribe container.

```powershell
docker exec ascend-audio-scribe sh -c "rm -f /tmp/transcript_*.md"
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

## Post-run cleanup

Drop the fixture this spec uploaded, so the bucket is left exactly as the spec found it. Run it regardless of whether
the Run step passed or failed. The command names the `e2e-fixtures` bucket literally and one key, and a key that is
already gone also returns HTTP 204, so the step is safe to re-run.

```powershell
curl.exe -fsS -X DELETE "http://localhost:9070/e2e-fixtures/meeting-clip.wav"
```

Leave the bucket itself in place. This spec creates it only if absent, and other specs seed their own fixtures into
it, so deleting the bucket would break them.

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

The JSON-RPC `result.isError` is either absent or `false` (the ascend-audio-scribe MCP wrapper sets `isError=true` only on
the error path).

## Fixtures

- `apps/ascend-audio-scribe/e2e/fixtures/meeting-clip.wav` — same fixture used by spec `2-transcribe-openai-test.md`. The MCP
  test references it via `http://host.docker.internal:9070/e2e-fixtures/meeting-clip.wav`, which ascend-audio-scribe's
  `download_service` resolves back out to the host-published object store.

## Concurrency

- **Mutates:** object-store bucket `e2e-fixtures` (object key `meeting-clip.wav`); ascend-audio-scribe container
  `/tmp/transcript_*.md` cache entries. `Reset state` uploads the object key and `Post-run cleanup` deletes it again,
  so the spec leaves no object behind. The bucket itself is created if absent and is never deleted, because other
  specs seed their own fixtures into it.
- **Conflicts with:** any future test that also writes `e2e-fixtures/meeting-clip.wav` — none currently exist.
