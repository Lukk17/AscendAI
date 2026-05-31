# e2e fixtures

Small canary files used by upload-style tests. Each fixture holds distinctive content (invented proper nouns,
specific quoted phrases) so a passing test proves the transcript came from the model rather than memorised
knowledge.

## Conventions

- Short WAV clips, mono, low sample rate fine for speech.
- One or two clearly enunciated phrases the test asserts against by substring (case-insensitive).
- Keep fixtures small so upload completes in under 2 seconds.

## Per-fixture documentation

| File | Used by | Distinctive transcript |
| :--- | :--- | :--- |
| `meeting-clip.wav` | `2-transcribe-openai-test.md`, `3-transcribe-hf-test.md`, `5-mcp-transcribe-test.md` | _"I think we should defer the migration to Q3 because the contract with Acme renews then. Adam, can you confirm the renewal date by Friday?"_ Tests assert the transcript contains `Q3`, `Acme`, `Adam`, `Friday`, and `migration` (case-insensitive). Same 56880-byte file as `AscendAgent/e2e/fixtures/meeting-clip.wav`. |

## MCP fixture mount

Test 5 (the MCP `transcribe_openai` call) takes a server-side URI rather than a multipart upload. The fixture must
be visible inside the AudioScribe container. Document the mount in a `docker-compose.override.yaml` that bind-mounts
`./AudioScribe/e2e/fixtures` to `/fixtures:ro` (do NOT edit the committed `docker-compose.yaml`); test 5's Bruno
request references `file:///fixtures/meeting-clip.wav`.
