# MCP tools/list contract: e2e test

## What this verifies

- The MCP `initialize` handshake against `POST /mcp` returns HTTP 200 with an `Mcp-Session-Id` header containing a
  non-empty UUID.
- A subsequent `tools/list` JSON-RPC call with the captured `Mcp-Session-Id` returns HTTP 200.
- The JSON-RPC `result.tools` array advertises **at least** the four transcribe tools (`transcribe_local`,
  `transcribe_openai`, `transcribe_hf`, `transcribe_audacity`) plus `health`.
- Each transcribe tool's `inputSchema.properties` advertises `audio_uri` as a required parameter.
- `transcribe_local` and `transcribe_audacity` also advertise `model`, `language` (optional).
- `transcribe_openai` advertises `model`, `language` (optional).
- `transcribe_hf` advertises `model`, `hf_provider` (optional).
- No external API (OpenAI, Hugging Face) is invoked. `tools/list` is a pure protocol probe — running the test
  without `OPENAI_API_KEY` / `HF_TOKEN` still passes; the tool definitions are advertised regardless of which
  providers are configured.

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

## Reset state

None. `tools/list` is read-only and writes no persisted state.

## Run

```powershell
cd docs/api/request/AscendAI
```

**Step 1.** Open an MCP session via the `initialize` handshake. Capture the `Mcp-Session-Id` value from the response headers.

```powershell
curl.exe -fsS -i -X POST http://localhost:7017/mcp -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"initialize\",\"params\":{\"protocolVersion\":\"2025-11-25\",\"capabilities\":{},\"clientInfo\":{\"name\":\"e2e\",\"version\":\"0.1.0\"}}}"
```

Look for `Mcp-Session-Id: <uuid>` in the response. Use that UUID as the value of the `mcp_session_id` env-var in the next step(s).

**Step 2.** Send the tool call(s) with the captured session ID injected:

```powershell
bru run "transcribe/testing/mcp-list-tools.yml" --env ascend-local --env-var "mcp_session_id=<paste UUID from step 1>"
```

## Expected

Step 1 returns HTTP 200. The response carries an `Mcp-Session-Id` header whose value is a non-empty string (FastMCP
emits a UUID).

Step 2 returns HTTP 200. The JSON-RPC `result.tools` array satisfies:

- Length is at least 5.
- Contains entries with `name` equal to each of `transcribe_local`, `transcribe_openai`, `transcribe_hf`,
  `transcribe_audacity`, `health`.
- Every transcribe entry's `inputSchema.properties` includes `audio_uri`.
- `transcribe_openai` entry's `inputSchema.properties` includes `model` and `language`.
- `transcribe_hf` entry's `inputSchema.properties` includes `model` and `hf_provider`.
- `transcribe_local` entry's `inputSchema.properties` includes `model`, `language`, `with_timestamps`.
- `transcribe_audacity` entry's `inputSchema.properties` includes `provider`, `model`, `language`.
- Every transcribe entry's `description` is a non-empty string.

## Fixtures

None.
