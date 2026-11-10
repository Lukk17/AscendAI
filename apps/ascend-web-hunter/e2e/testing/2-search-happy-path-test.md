# REST search happy path: e2e test

## What this verifies

- `GET /api/v1/web/search?query=OpenStreetMap&limit=3` returns HTTP 200 and a JSON array body.
- The array has at least one element and at most three (honours the `limit` parameter).
- Each element is an object with non-empty string fields `title` and `url`, and a string field `content`. The
  service writes `content` as an empty string when the SearXNG result has no snippet, so `content` is always
  present but may be empty.
- At least one element's `url` field starts with `http://` or `https://`.
- At least one element's `title` or `content` field references OpenStreetMap (case-insensitive substring match
  on `"openstreetmap"`).
- The call completes against the SearXNG backend without raising HTTP 5xx (proves SearXNG → meta-engines →
  HTML parser path is intact).

`"OpenStreetMap"` is chosen as a stable, widely-indexed term that virtually every meta-search engine ranks
highly - minimising flakiness from upstream result churn.

## Prerequisites

Check Bruno CLI is installed.

```bash
bru --version
```

Expect a version string.

Check the ascend-web-hunter server is reachable. The `-w` option prints the status code after the body.

```bash
curl -fsS -w "\nHTTP %{http_code}\n" http://127.0.0.1:7021/health
```

Expect a body with `status` `ok`, `service` `ascend-web-hunter` and a non-empty `version`, then the line `HTTP 200`.

Check the SearXNG backend is reachable from the host.

```bash
curl -fsS "http://localhost:9020/search?q=test&format=html"
```

Expect HTTP 200 with HTML content.

Confirm SearXNG's upstream engines actually return results. The settings.yml overlay enables JSON; this query
fans the meta-search across every enabled engine and parses the count from the response.

**PowerShell:**

```powershell
$json = curl -fsS "http://localhost:9020/search?q=openstreetmap&format=json" | ConvertFrom-Json; "$($json.results.Count) results, $($json.unresponsive_engines.Count) blocked engines"
```

**Unix:**

```bash
curl -fsS "http://localhost:9020/search?q=openstreetmap&format=json" | "$(command -v python3 || command -v python)" -c "import json, sys; d = json.load(sys.stdin); print(f\"{len(d.get('results', []))} results, {len(d.get('unresponsive_engines', []))} blocked engines\")"
```

Expect a non-zero results count. If results is `0` and the unresponsive-engines list shows access-denied /
CAPTCHA across all enabled engines, the residential / shared egress IP is being walled by upstream search
providers - the ascend-web-hunter service itself is healthy but this test cannot exercise the end-to-end happy
path. Mark this run **BLOCKED** (not FAIL) and re-run when an upstream is reachable; the suspended_times in
`infra/searxng/settings.yml` are set to seconds-to-minutes so recovery is fast once the upstreams release the IP.

## Reset state

The search path writes no search state. SearXNG owns its own internal cache. The call does count against the
caller's rate limit window for the route, which lives in Redis under one key per caller and path:
`LIMITS:LIMITER/ascend-web-hunter/<caller address>//api/v1/web/search/<limit>/1/minute`. The shared library
(`build_limiter` in `libs/ascend-python-common`) sets the key prefix `ascend-web-hunter`, and the path part is the
request path with its leading slash, so two slashes follow the caller address. `<limit>` is the
`RATE_LIMIT_DEFAULT` count (1200 by default). `<caller address>` is the address the container sees for a call from
the host, the gateway of the compose network, which differs from host to host. A window left nearly full by an
earlier run can answer the search with HTTP 429, so delete the key before the run.

List the key first (a read, it deletes nothing) to get the exact key on this host.

```bash
docker exec redis redis-cli --scan --pattern "LIMITS:LIMITER/ascend-web-hunter/*/api/v1/web/search/*"
```

Expect no line (no window open) or one line naming the key. When the scan printed no line, skip the next step.
Otherwise delete that exact key: replace `<key the scan printed>` with the whole line, unchanged.

```bash
docker exec redis redis-cli DEL "<key the scan printed>"
```

Expect `1`.

## Run

Single Bruno request. Move into the Bruno collection root first, from the repository root.

```bash
cd docs/api/request/AscendAI
```

```bash
bru run "web-hunter/testing/search-stable-query.yml" --env ascend-local
```

## Expected

HTTP 200. The JSON body matches:

- Top-level type is a JSON array.
- Array length is in `[1, 3]`.
- Every entry has:
  - `title` is a non-empty string.
  - `url` is a non-empty string starting with `http://` or `https://`.
  - `content` is a string (may be empty for entries whose engine did not return a snippet, but the field MUST
    be present).
- At least one entry's `title` or `content`, lowercased, contains `"openstreetmap"`.

Total call duration is typically 1-5 s (SearXNG fan-out time). A duration > 30 s indicates upstream engines are
timing out - investigate SearXNG health before declaring FAIL.

**Environmental BLOCKED:** if the JSON prereq above returned `0 results` and the same IP cannot reach any
upstream engine, the run was never able to exercise the end-to-end happy path. Report the verdict as
**BLOCKED** with the unresponsive-engines list as evidence. This is distinct from a code regression and
should not block a merge.

## Fixtures

None.

## Concurrency

Writes no `session:*`, tier-memory, crawl or recipe key. The search call writes only SearXNG's own cache, out of
process, and the rate limit window of the route, which its reset deletes. Spec 1
([1-invalid-input-test.md](1-invalid-input-test.md)) counts against the same window, and neither spec asserts on the
count, so the two still run side by side. Safe beside every other spec.

- Serial: false
