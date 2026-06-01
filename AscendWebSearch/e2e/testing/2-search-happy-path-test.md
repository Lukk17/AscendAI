# REST search happy path: e2e test

## What this verifies

- `GET /api/v1/web/search?query=OpenStreetMap&limit=3` returns HTTP 200 and a JSON array body.
- The array has at least one element and at most three (honours the `limit` parameter).
- Each element is an object with non-empty string fields `title`, `url`, `content`.
- At least one element's `url` field starts with `http://` or `https://`.
- At least one element's `title` or `content` field references OpenStreetMap (case-insensitive substring match
  on `"openstreetmap"`).
- The call completes against the SearXNG backend without raising HTTP 5xx (proves SearXNG → meta-engines →
  HTML parser path is intact).

`"OpenStreetMap"` is chosen as a stable, widely-indexed term that virtually every meta-search engine ranks
highly — minimising flakiness from upstream result churn.

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

Check the SearXNG backend is reachable from the host.

```powershell
curl -fsS "http://localhost:9020/search?q=test&format=html"
```

Expect HTTP 200 with HTML content.

Confirm SearXNG's upstream engines actually return results. The settings.yml overlay enables JSON; this query
fans the meta-search across every enabled engine and parses the count from the response.

```powershell
$json = curl -fsS "http://localhost:9020/search?q=openstreetmap&format=json" | ConvertFrom-Json; "$($json.results.Count) results, $($json.unresponsive_engines.Count) blocked engines"
```

Expect a non-zero results count. If results is `0` and the unresponsive-engines list shows access-denied /
CAPTCHA across all enabled engines, the residential / shared egress IP is being walled by upstream search
providers — the AscendWebSearch service itself is healthy but this test cannot exercise the end-to-end happy
path. Mark this run **BLOCKED** (not FAIL) and re-run when an upstream is reachable; the suspended_times in
`searxng/settings.yml` are set to seconds-to-minutes so recovery is fast once the upstreams release the IP.

## Reset state

None. SearXNG owns its own internal cache; the host does not write persisted state for the search path.

## Run

Single Bruno request.

```powershell
cd docs/api/request/AscendAI
```

```powershell
bru run "web-search/testing/search-stable-query.yml" --env ascend-local
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

Total call duration is typically 1–5 s (SearXNG fan-out time). A duration > 30 s indicates upstream engines are
timing out — investigate SearXNG health before declaring FAIL.

**Environmental BLOCKED:** if the JSON prereq above returned `0 results` and the same IP cannot reach any
upstream engine, the run was never able to exercise the end-to-end happy path. Report the verdict as
**BLOCKED** with the unresponsive-engines list as evidence. This is distinct from a code regression and
should not block a merge.

## Fixtures

None.
