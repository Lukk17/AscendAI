# MCP transcribe_openai happy path: run tasks template

Spec: [../5-mcp-transcribe-test.md](../5-mcp-transcribe-test.md)

Copy this file to `../runs/<UTC-timestamp>_5-mcp-transcribe-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [ ] Bruno CLI present (`bru --version` returns a version)
- [ ] ascend-audio-scribe `/health` returns HTTP 200 with `{"status":"ok","service":"ascend-audio-scribe"}`
- [ ] `docker exec ascend-audio-scribe sh -c '[ -n "$OPENAI_API_KEY" ] && echo present || echo missing'` prints `present`
- [ ] `apps/ascend-audio-scribe/e2e/fixtures/meeting-clip.wav` exists on the host
- [ ] Object store `curl.exe -fsS http://localhost:9070/_floci/health` returns HTTP 200 with `"s3":"running"`

### Reset state

- [ ] `curl.exe -sS -o NUL -w "%{http_code}\n" -X PUT "http://localhost:9070/e2e-fixtures"` prints `200`
- [ ] `curl.exe -fsS -X DELETE "http://localhost:9070/e2e-fixtures/meeting-clip.wav"` returned HTTP 204 (object cleared)
- [ ] `curl.exe -sS -o NUL -w "%{http_code}\n" -X PUT -H "Content-Type: audio/mpeg" --data-binary "@apps/ascend-audio-scribe/e2e/fixtures/meeting-clip.wav" "http://localhost:9070/e2e-fixtures/meeting-clip.wav"` prints `200`
- [ ] `curl.exe -fsS "http://localhost:9070/e2e-fixtures?list-type=2&prefix=meeting-clip"` carries `<Key>meeting-clip.wav</Key>` with `<Size>56880</Size>`
- [ ] `docker exec ascend-audio-scribe sh -c "rm -f /tmp/transcript_*.md"` succeeds

### Run

- [ ] Step 1: `curl.exe -fsS -i -X POST http://localhost:7017/mcp ... initialize ...` returns HTTP 200 with an `Mcp-Session-Id` header, capture the session id (32 character hexadecimal session id without hyphens)
- [ ] Send `mcp-transcribe.yml` via `bru run` with `--env-var "mcp_session_id=<captured session id>"` and wait for HTTP 200

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
- [ ] `result.isError` is absent or `false`

### Post-run cleanup

Run regardless of the Run-step verdict; the delete is idempotent.

- [ ] `curl.exe -fsS -X DELETE "http://localhost:9070/e2e-fixtures/meeting-clip.wav"` returned HTTP 204
- [ ] The `e2e-fixtures` bucket itself was left in place

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
