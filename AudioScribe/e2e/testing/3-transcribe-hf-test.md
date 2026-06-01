# Transcribe Hugging Face happy path: e2e test

## What this verifies

- `POST /api/v1/transcribe/hf` with `meeting-clip.wav` (multipart-form `file`), `stream=false`, default `model`
  (`openai/whisper-large-v3`) and `hf_provider` (`hf-inference`) returns HTTP 200.
- The response `Content-Type` header is `text/markdown` (the endpoint serves a `FileResponse` with the `.md`
  transcript on the `stream=false` happy path).
- The response body (the `.md` transcript content) contains at least one of the canary substrings `Q3`, `Acme`, `Adam`, `Friday`, or `migration` (case-insensitive). The asserted phrase is the invented sentence recorded into
  `meeting-clip.wav`; at least one distinctive word being present proves the audio bytes were actually transcribed
  through the Hugging Face Inference API.
- The request consumes Hugging Face inference quota — the test is not safe to run with `HF_TOKEN` unset; the endpoint
  short-circuits to HTTP 500 with `"HF_TOKEN is not configured on the server."` when the token is missing.

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

Check the AudioScribe container has `HF_TOKEN` configured.

```powershell
docker exec audio-scribe printenv HF_TOKEN
```

Expect a non-empty string. If empty, set `HF_TOKEN` in the host environment / `.env` and recreate the container.

Check outbound HTTPS to the Hugging Face Inference API works from the AudioScribe container.

```powershell
docker exec audio-scribe curl -fsS -o NUL -w "%{http_code}\n" https://router.huggingface.co/hf-inference
```

Expect HTTP 200 (root marketing page) or HTTP 401 (depending on the endpoint Hugging Face is currently serving on
the root — confirms egress works).

Check the canary fixture is present.

```powershell
dir AudioScribe\e2e\fixtures\meeting-clip.wav
```

Expect the file to exist and be at least 1 KB. If missing, record the canary phrase per
`AudioScribe/e2e/fixtures/README.md` before continuing.

## Reset state

Delete any stale `transcript_hf.md` cache entries from prior runs to keep `/tmp` clean and rule out a stale download
contaminating the assertion.

```powershell
docker exec audio-scribe sh -c "rm -f /tmp/transcript_*.md"
```

## Run

Single Bruno request.

```powershell
cd docs/api/request/AscendAI
```

```powershell
bru run "transcribe/testing/transcribe-hf-canary.yml" --env ascend-local
```

## Expected

The Bruno call returns HTTP 200.

The response matches:

- `Content-Type` response header starts with `text/markdown`.
- `Content-Disposition` response header is `attachment; filename="transcript_hf.md"`.
- Response body length is at least 5 bytes.
- Response body lowercased contains at least one of: `Q3`, `Acme`, `Adam`, `Friday`, or `migration`.

## Fixtures

- `AudioScribe/e2e/fixtures/meeting-clip.wav` — ≤ 5 s mono WAV at 16 kHz, spoken English line
  *"I think we should defer the migration to Q3 because the contract with Acme renews then. Adam, can you confirm the renewal date by Friday?"*
