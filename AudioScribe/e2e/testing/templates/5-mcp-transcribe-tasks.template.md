# MCP transcribe_openai happy path: run tasks template

Spec: [../5-mcp-transcribe-test.md](../5-mcp-transcribe-test.md)

Copy this file to `../runs/<UTC-timestamp>_5-mcp-transcribe-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [ ] Bruno CLI present (`bru --version` returns a version)
- [ ] AudioScribe `/health` returns HTTP 200 with `{"status":"ok","service":"AudioScribe"}`
- [ ] `docker exec audio-scribe printenv OPENAI_API_KEY` returns a non-empty string
- [ ] `docker-compose.override.yaml` bind-mounts `AudioScribe/e2e/fixtures` to `/fixtures:ro` and the container is recreated
- [ ] `docker exec audio-scribe ls /fixtures/meeting-clip.wav` succeeds

### Reset state

- [ ] `docker exec audio-scribe sh -c "rm -f /tmp/transcript_*.md"` succeeds

### Run

- [ ] Step 1: `curl.exe -fsS -i -X POST http://localhost:7017/mcp ... initialize ...` returns HTTP 200 with an `Mcp-Session-Id` header; capture the UUID
- [ ] Send `mcp-transcribe.yml` via `bru run` with `--env-var "mcp_session_id=<captured UUID>"` and wait for HTTP 200

### Expected

- [ ] Step 1 returns HTTP 200 and the `Mcp-Session-Id` header value is non-empty
- [ ] Step 2 returns HTTP 200
- [ ] `result.content` array length is exactly 1
- [ ] `result.content[0].type` equals `"text"`
- [ ] `result.content[0].text` is a non-empty string that parses as JSON
- [ ] Parsed JSON has `source="openai"`
- [ ] Parsed JSON has `model="whisper-1"`
- [ ] Parsed JSON has `language="en"`
- [ ] Parsed JSON `transcription` is a non-empty string
- [ ] Parsed JSON `transcription` lowercased contains at least one of `Q3`, `Acme`, `Adam`, `Friday`, or `migration`
- [ ] `result.is_error` is absent or `false`

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
