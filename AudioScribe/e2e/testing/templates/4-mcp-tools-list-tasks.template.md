# MCP tools/list contract: run tasks template

Spec: [../4-mcp-tools-list-test.md](../4-mcp-tools-list-test.md)

Copy this file to `../runs/<UTC-timestamp>_4-mcp-tools-list-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [ ] Bruno CLI present (`bru --version` returns a version)
- [ ] AudioScribe `/health` returns HTTP 200 with `{"status":"ok","service":"AudioScribe"}`

### Reset state

- [ ] None required

### Run

- [ ] Step 1: `curl.exe -fsS -i -X POST http://localhost:7017/mcp ... initialize ...` returns HTTP 200 with an `Mcp-Session-Id` header; capture the UUID
- [ ] Send `mcp-list-tools.yml` via `bru run` with `--env-var "mcp_session_id=<captured UUID>"` and wait for HTTP 200

### Expected

- [ ] Step 1 returns HTTP 200 and the `Mcp-Session-Id` header value is non-empty
- [ ] Step 2 returns HTTP 200
- [ ] `result.tools` length ≥ 5
- [ ] `result.tools` contains entries named `transcribe_local`, `transcribe_openai`, `transcribe_hf`, `transcribe_audacity`, `health`
- [ ] Every transcribe entry's `inputSchema.properties` includes `audio_uri`
- [ ] `transcribe_openai` `inputSchema.properties` includes `model` and `language`
- [ ] `transcribe_hf` `inputSchema.properties` includes `model` and `hf_provider`
- [ ] `transcribe_local` `inputSchema.properties` includes `model`, `language`, `with_timestamps`
- [ ] `transcribe_audacity` `inputSchema.properties` includes `provider`, `model`, `language`
- [ ] Every transcribe entry's `description` is a non-empty string

### Verdict

- [ ] Verdict: PASS / FAIL (delete the wrong one)

## Result summary



Input tokens: 0

Output tokens: 0

Start (UTC):

End (UTC):

Duration:

---

## Additional tasks I did

<!-- Optional. List anything outside the spec, e.g. diagnostic curls, manual log inspection, retries with different inputs. Leave empty if nothing extra. -->
