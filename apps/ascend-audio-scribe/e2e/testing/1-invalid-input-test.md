# Invalid input rejection: e2e test

## What this verifies

- `POST /api/v1/transcribe/openai` with the required `file` multipart-form field missing returns HTTP 400
  (`application/problem+json`, code `validation`) with an `errors` array.
- The `errors` array has at least one entry naming `file` in its `field` path, plus `traceId` (32 lower case hex characters).
- The error short-circuits inside request validation **before** `transcribe_openai_endpoint` runs - no outbound
  HTTPS request to `api.openai.com` is made, no OpenAI quota is consumed, no `.md` file is written to the
  ascend-audio-scribe `/tmp` cache.
- `Content-Type` of the response is `application/problem+json`, NOT `text/markdown`.

## Prerequisites

Check Bruno CLI is installed.

```bash
bru --version
```

Expect a version string. If the command is not found, install it with `npm install -g @usebruno/cli`.

Check the ascend-audio-scribe server is reachable.

```bash
curl -fsS http://localhost:7017/health
```

Expect HTTP 200 with `{"status":"ok","service":"ascend-audio-scribe"}`.

## Reset state

None. This test does not write any persisted state (the request is rejected before the upload handler runs).

## Run

Single Bruno request.

```bash
cd docs/api/request/AscendAI
```

```bash
bru run "transcribe/testing/transcribe-invalid-no-file.yml" --env ascend-local
```

## Expected

The Bruno call returns HTTP 400 with `Content-Type: application/problem+json`.

The response body parses as JSON and matches:

- Has `code` equal to `"validation"`.
- Has a top-level `errors` field that is a non-empty array sorted by `field`.
- At least one element of `errors` has `field` containing the string `"file"`.
- Has `traceId` matching `^[0-9a-f]{32}$`.
- `Content-Type` response header starts with `application/problem+json`.

No call should have been made to `api.openai.com` - this is an internal property the spec does not directly assert
(the runner is black-box), but a steady-state run takes < 200 ms. A duration > 1 s suggests the request reached the
handler and an OpenAI call was attempted; investigate before declaring PASS.

## Fixtures

None.
