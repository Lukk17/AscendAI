# Transcribe OpenAI happy path: run tasks template

Spec: [../2-transcribe-openai-test.md](../2-transcribe-openai-test.md)

Copy this file to `../runs/<UTC-timestamp>_2-transcribe-openai-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [ ] Bruno CLI present (`bru --version` returns a version)
- [ ] AudioScribe `/health` returns HTTP 200 with `{"status":"ok","service":"AudioScribe"}`
- [ ] `docker exec audio-scribe printenv OPENAI_API_KEY` returns a non-empty string
- [ ] AudioScribe container can reach `https://api.openai.com/v1/models` (HTTP 200 or 401)
- [ ] `AudioScribe/e2e/fixtures/meeting-clip.wav` exists and is at least 1 KB

### Reset state

- [ ] `docker exec audio-scribe sh -c "rm -f /tmp/transcript_*.md"` succeeds

### Run

- [ ] Send `transcribe-openai-canary.yml` via `bru run` and wait for HTTP 200

### Expected

- [ ] HTTP status code is 200
- [ ] Response `Content-Type` starts with `text/markdown`
- [ ] Response `Content-Disposition` equals `attachment; filename="transcript_openai.md"`
- [ ] Response body length ≥ 5 bytes
- [ ] Response body lowercased contains at least one of `Q3`, `Acme`, `Adam`, `Friday`, or `migration`

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
