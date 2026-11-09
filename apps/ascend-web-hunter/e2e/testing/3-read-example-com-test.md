# REST v2 read happy path: e2e test

## What this verifies

- `POST /api/v2/web/read` with `{"url": "https://www.example.com/"}` returns HTTP 200 and a JSON object body.
- The response object has:
  - `url` equal to `"https://www.example.com/"`.
  - `status` equal to `"success"` (the success enum value emitted by the extraction pipeline).
  - A non-empty string field carrying the extracted content (`content` or equivalent - see Expected).
- The extracted content contains the canary phrase `"this domain is for use in documentation examples"` (the
  body paragraph of `example.com`; the former `<h1>Example Domain</h1>` no longer exists upstream, only
  `<title>` plus the paragraph).
- The first tier, `1-beautifulsoup` (a plain HTTP fetch, no browser), is sufficient. `example.com` is served
  through Cloudflare but answers without a challenge page, and the service judges it not a wall, so a cold read
  answers `mode` `"1-beautifulsoup"`. The test
  does NOT require Playwright or any heavier tier. If the read climbs to one of those tiers, the test still passes
  provided the canary phrase is found.

## Prerequisites

Check Bruno CLI is installed.

```bash
bru --version
```

Expect a version string.

Check the ascend-web-hunter server is reachable.

```bash
curl -fsS http://127.0.0.1:7021/health
```

Expect HTTP 200 with `status` `ok`, `service` `ascend-web-hunter` and a non-empty `version`.

Check outbound HTTPS to `example.com` works from this host (independently of the ascend-web-hunter container).

```bash
curl -fsS https://www.example.com/
```

Expect HTTP 200 with a body containing `"This domain is for use in documentation examples"`. If this fails, the host cannot reach the public
internet and the test cannot pass for environmental reasons.

## Reset state

Optionally force a cold extraction. This is not required, because the response shape is identical for a cached and
a fresh read, but a cold run exercises the tier ladder from its first tier. Two kinds of state can make the read
skip the cold path: the in-process read cache (entries live `READ_CACHE_TTL_SECONDS`, 300 s, and Redis cannot reach
them) and the remembered tier in Redis under `tier_memory:example.com`. Both are keyed by the registrable domain
`example.com`, which `www.example.com` resolves to.

Clear the read cache for the domain. The call also deletes `session:example.com:default` if one exists.

PowerShell:

```powershell
curl.exe -fsS -X POST http://127.0.0.1:7021/api/v2/web/session/clear -H "Content-Type: application/json" -d '{"url":"https://www.example.com/","profile":"default"}'
```

Unix:

```bash
curl -fsS -X POST http://127.0.0.1:7021/api/v2/web/session/clear -H "Content-Type: application/json" -d '{"url":"https://www.example.com/","profile":"default"}'
```

Expect HTTP 200 with `status` `"cleared"`. `cleared_cache_entries` is the number of cached reads removed, `0` on a
cold service.

Delete the remembered tier.

```bash
docker exec redis redis-cli DEL tier_memory:example.com
```

Expect `1` when a tier was remembered, `0` otherwise. Both are fine.

If you choose not to reset, document the choice under **Additional tasks I did** in the run record.

## Run

Single Bruno request. From the repository root:

```bash
cd docs/api/request/AscendAI
```

```bash
bru run "web-hunter/testing/extract-example-com.yml" --env ascend-local
```

## Expected

HTTP 200. The JSON body matches:

- `url` equals `"https://www.example.com/"`.
- `status` equals `"success"`.
- A content-carrying string field is present. Acceptable field names (the contract emits one of these depending
  on the extraction tier): `content`, `text`, or `markdown`. The runner accepts any string value of any of these
  fields with length ≥ 50 characters.
- The content-carrying field (whichever one is populated), when lowercased, contains the substring
  `"this domain is for use in documentation examples"` (the verbatim canary phrase from the page's body
  paragraph).

- `mode` names the tier that answered. A cold read answers `"1-beautifulsoup"`. Another tier name is not a
  failure, log it under **Additional tasks I did**.

A duration above 60 s means the pipeline escalated to a browser tier or NoVNC. Log it under **Additional tasks I
did**, but do not fail the test if the canary phrase still resolves.

## Fixtures

None.

## Concurrency

Redis keys this spec changes:

- `tier_memory:example.com`: the read may write it, and the reset deletes it.
- `session:example.com:default`: the reset's `session/clear` deletes it if one exists. The read itself writes no
  session record. Only a NoVNC window or an automatic browser read that saw a wall and ended accepted saves one, and
  the read of `example.com` meets no wall and never answers 428.

It also fills, and its reset empties, the service's in-process read cache for `example.com`. Two concurrent reads of
the same URL are still safe, because the response shape is the same for a cached and a fresh read.

Spec 9 ([9-session-status-test.md](9-session-status-test.md)) depends on this spec: its Reset state checks that
`session:example.com:default` does not exist, and its Call 1 expects `status` `none` for `example.com` on the
promise that this spec never writes that key. A read of this spec that climbed to a NoVNC window and saved a
session would turn spec 9's Call 1 into a FAIL, so not beside spec 9. Run it before or after spec 9. Test 7's row a reads the same URL, and its reset deletes
`session:example.com:default` and `tier_memory:example.com`, so not beside test 7. Tests 8
([8-session-clear-test.md](8-session-clear-test.md)) and 17
([17-session-import-test.md](17-session-import-test.md)) count this spec among the specs that write or delete a
`session:*` key during their before and after scans, so not beside them either.

- Serial: false
