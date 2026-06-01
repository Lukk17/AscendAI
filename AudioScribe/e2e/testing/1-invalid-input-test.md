# Invalid input rejection: e2e test

## What this verifies

- `POST /api/v1/transcribe/openai` with the required `file` multipart-form field missing returns HTTP 422 (FastAPI's
  default for `RequestValidationError`) with a JSON body containing a `detail` array.
- The validation `detail` array has at least one entry naming `file` in its `loc` path (e.g. `loc: ["body", "file"]`)
  and a `type` value that identifies a missing-field error (FastAPI emits `missing` on Pydantic v2; older versions
  emit `value_error.missing`).
- The error short-circuits inside FastAPI's request parser **before** `transcribe_openai_endpoint` runs — no outbound
  HTTPS request to `api.openai.com` is made, no OpenAI quota is consumed, no `.md` file is written to the
  AudioScribe `/tmp` cache.
- `Content-Type` of the response is `application/json` (FastAPI default for validation errors), NOT `text/markdown`.

## Prerequisites

Check Bruno CLI is installed.

```powershell
bru --version
```

Expect a version string. If the command is not found, install it with `npm install -g @usebruno/cli`.

Check the AudioScribe server is reachable.

```powershell
curl -fsS http://localhost:7017/health
```

Expect HTTP 200 with `{"status":"ok","service":"AudioScribe"}`.

## Reset state

None. This test does not write any persisted state (the request is rejected before the upload handler runs).

## Run

Single Bruno request.

```powershell
cd docs/api/request/AscendAI
```

```powershell
bru run "transcribe/testing/transcribe-invalid-no-file.yml" --env ascend-local
```

## Expected

The Bruno call returns HTTP 422.

The response body parses as JSON and matches:

- Has a top-level `detail` field that is a non-empty array.
- At least one element of `detail` has `loc` containing the string `"file"`.
- At least one element of `detail` has `type` that contains the substring `"missing"` (matches both `missing` and
  `value_error.missing` shapes).
- `Content-Type` response header starts with `application/json`.

No call should have been made to `api.openai.com` — this is an internal property the spec does not directly assert
(the runner is black-box), but a steady-state run takes < 200 ms. A duration > 1 s suggests the request reached the
handler and an OpenAI call was attempted; investigate before declaring PASS.

## Fixtures

None.
