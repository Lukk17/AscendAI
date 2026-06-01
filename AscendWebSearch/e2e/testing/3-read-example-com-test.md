# REST v2 read happy path: e2e test

## What this verifies

- `POST /api/v2/web/read` with `{"url": "https://www.example.com/"}` returns HTTP 200 and a JSON object body.
- The response object has:
  - `url` equal to `"https://www.example.com/"`.
  - `status` equal to `"success"` (the success enum value emitted by the extraction pipeline).
  - A non-empty string field carrying the extracted content (`content` or equivalent — see Expected).
- The extracted content contains the canary phrase `"Example Domain"` (the `<h1>` of `example.com`, deliberately
  stable since the IETF reserves the domain for documentation).
- The lightweight extraction tier (curl_cffi) is sufficient — `example.com` has no Cloudflare WAF, no JavaScript
  challenge, no CAPTCHA. The test does NOT require Playwright or FlareSolverr; if it falls through to those
  tiers, the test still passes provided the canary phrase is found.

## Prerequisites

Check Bruno CLI is installed.

```powershell
bru --version
```

Expect a version string.

Check the AscendWebSearch server is reachable.

```powershell
curl -fsS http://localhost:7021/health
```

Expect HTTP 200 with `{"status":"ok"}`.

Check outbound HTTPS to `example.com` works from this host (independently of the AscendWebSearch container).

```powershell
curl -fsS https://www.example.com/
```

Expect HTTP 200 with an `<h1>Example Domain</h1>` in the body. If this fails, the host cannot reach the public
internet and the test cannot pass for environmental reasons.

## Reset state

Optionally flush the Redis session-cache key for `example.com` to force a cold extraction. This is not required —
the response shape is identical for cache hits and misses — but a cold run exercises the full tiered fallback.

```powershell
docker exec ascend-redis redis-cli --scan --pattern "*example.com*" | ForEach-Object { docker exec ascend-redis redis-cli DEL $_ }
```

If you choose not to reset, document the choice under **Additional tasks I did** in the run record.

## Run

Single Bruno request.

```powershell
cd docs/api/request/AscendAI
```

```powershell
bru run "web-search/testing/extract-example-com.yml" --env ascend-local
```

## Expected

HTTP 200. The JSON body matches:

- `url` equals `"https://www.example.com/"`.
- `status` equals `"success"`.
- A content-carrying string field is present. Acceptable field names (the contract emits one of these depending
  on the extraction tier): `content`, `text`, or `markdown`. The runner accepts any string value of any of these
  fields with length ≥ 50 characters.
- The content-carrying field (whichever one is populated), when lowercased, contains the substring
  `"example domain"` (the verbatim canary phrase from the `<h1>` element).

Total call duration is typically 1–10 s for the curl_cffi tier. A duration > 60 s indicates the pipeline
escalated to Playwright or NoVNC — log it under **Additional tasks I did** but do not fail the test if the
canary phrase still resolves.

## Fixtures

None.
