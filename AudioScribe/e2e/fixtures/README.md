# e2e fixtures

Small canary files used by upload-style tests. Each fixture holds distinctive content (invented proper nouns,
specific quoted phrases) so a passing test proves the transcript came from the model rather than memorised
knowledge.

## Conventions

- Short audio clips, mono, low sample rate fine for speech. The file extension doesn't need to match the actual
  codec: providers transcode regardless.
- One or two clearly enunciated phrases the test asserts against by substring (case-insensitive).
- Keep fixtures small so upload completes in under 2 seconds.

## Per-fixture documentation

| File | Used by | Distinctive transcript |
| :--- | :--- | :--- |
| `meeting-clip.wav` | `2-transcribe-openai-test.md`, `3-transcribe-hf-test.md`, `5-mcp-transcribe-test.md` | _"I think we should defer the migration to Q3 because the contract with Acme renews then. Adam, can you confirm the renewal date by Friday?"_ Tests assert the transcript contains `Q3`, `Acme`, `Adam`, `Friday`, and `migration` (case-insensitive). 56880 bytes, same file as `AscendAgent/e2e/fixtures/meeting-clip.wav`. Despite the `.wav` extension, `ffprobe` shows it is actually a LAME-encoded MP3 elementary stream (starts with the MPEG sync word `0xfff3`, no RIFF header): mono, 24 kHz, 9.48 seconds, not the 16 kHz / ≤5 s mono WAV the specs used to claim. Both providers transcode it without issue. |

## MCP fixture delivery

Test 5 (the MCP `transcribe_openai` call) takes a server-side URI rather than a multipart upload. It uses no bind
mount. The runner uploads the fixture from the host during the spec's Reset state step, with a plain `PUT` against
the object store's S3 endpoint on port 9070, into the `e2e-fixtures` bucket under the key `meeting-clip.wav`. The
bucket is created by the same step and is never deleted by the spec.

Test 5's Bruno request (`transcribe/testing/mcp-transcribe.yml`) then passes
`audio_uri="http://host.docker.internal:9070/e2e-fixtures/meeting-clip.wav"`. AudioScribe's `download_service`
follows that URL back out to the host-published object store and pulls the bytes itself, so the fixture never has to
be visible on the container filesystem.
