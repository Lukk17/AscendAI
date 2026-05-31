# Invalid input rejection: e2e test

## What this verifies

- `GET /api/v1/web/search` with a blank `query` parameter (`query=   `) returns HTTP 400 and a JSON body whose
  `detail` field describes the empty-query failure.
- `GET /api/v1/web/search` with a missing `query` parameter (`query` omitted entirely) returns HTTP 422 — FastAPI's
  default validation error for a missing required query-string parameter.
- `GET /api/v1/web/search` with a `query` longer than 500 characters returns HTTP 400 and the `detail` field
  mentions the maximum-length constraint.
- All three rejections short-circuit inside the FastAPI route before any SearXNG call is made — **no outbound
  HTTPS to SearXNG or to the public internet is required** to make this test pass.

## Prerequisites

Check Bruno CLI is installed.

```powershell
bru --version
```

Expect a version string. If the command is not found, install it with `npm install -g @usebruno/cli`.

Check the AscendWebSearch server is reachable.

```powershell
curl -fsS http://localhost:7021/health
```

Expect HTTP 200 with `{"status":"ok"}`.

## Reset state

None. This test does not write persisted state and is read-only against SearXNG (which it should never reach).

## Run

Send three Bruno requests in sequence. Each must complete before the next begins.

```powershell
cd docs/api/request/AscendAI
```

```powershell
bru run "web-search/testing/search-blank-query.yml" --env ascend-local
```

```powershell
bru run "web-search/testing/search-missing-query.yml" --env ascend-local
```

```powershell
bru run "web-search/testing/search-overlong-query.yml" --env ascend-local
```

## Expected

The three calls return:

- `search-blank-query.yml` — HTTP 400. The JSON body has a `detail` field equal to `"query must not be empty"`.
- `search-missing-query.yml` — HTTP 422 (FastAPI default for a missing required query parameter). The JSON body
  has a top-level `detail` array; at least one entry has `type` equal to `"missing"` and `loc` containing
  `"query"`.
- `search-overlong-query.yml` — HTTP 400. The JSON body's `detail` field contains the substring
  `"query exceeds maximum length"`.

Per-call duration is small (< 200 ms each) because no upstream is contacted. A duration > 2 s suggests the
validator was bypassed and SearXNG was actually called; investigate before declaring PASS.

## Fixtures

None.
