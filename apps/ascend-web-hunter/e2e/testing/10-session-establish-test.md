# Session establish: e2e test

## What this verifies

`POST /api/v2/web/session/establish` is the proactive counterpart to the passive NoVNC capture other reads fall
back to: it opens the NoVNC flow for a `url` on demand and always returns HTTP 200 with a `vnc_url` a human can open
to complete a login or captcha, without waiting for that human to act. This test asserts the immediate, synchronous
contract:

- HTTP 200, body `status="login_required"`, `target` equal to the (pydantic-normalised) request URL, and a
  non-empty `vnc_url` string.

## Two behaviours this spec found live, not assumed

A first draft of this spec assumed the call writes no session record at all until a human or scripted login
resolves the background monitor. Running it against the live service on port 7021 disproved that within seconds:
`session:example.net:default` existed, holding an empty-cookie record, well before any human could have acted. Two
things explain it, both confirmed by reading the code the monitor actually runs:

1. **The requested `profile` never reaches the capture path.** `SessionManager.establish`'s second parameter is
   named `_profile` — the leading underscore marks it unused — and neither `NoVNCStrategy.get_html` nor
   `_monitor_for_cookies` nor its `save_storage_state` call ever receives a profile at all, so every capture lands
   under `settings.SESSION_DEFAULT_PROFILE` ("default") regardless of what the caller asked for. The REST and MCP
   surfaces both advertise a `profile` field on this endpoint; establishing under a non-default profile silently
   does not work.
2. **The captcha-branch "cleared" check does not require a challenge to have existed.**
   `ChallengeDetector.is_content_accepted` — "the single shared decision point... before the NoVNC monitor declares
   a challenge cleared" — returns true for any response that is not a recognised block page and has real content.
   An ordinary, never-challenged page satisfies that on its very first poll (`NOVNC_COOKIE_SYNC_POLL_SECONDS`,
   5 seconds by default), so `establish()` against a plain URL captures whatever cookies exist — often none — as
   though a challenge had just been solved.

Neither of these is fixed here. Fixing (1) means threading `profile` through `NoVNCStrategy.get_html`,
`_monitor_for_cookies`, and every `save_storage_state` call inside it; fixing (2), if it is even wrong rather than
the intended fast path for challenges that clear themselves, needs a design decision about what "an unchallenged
page was 'cleared' instantly" should mean. Both are flagged to the owner as findings from this task, not changed by
it. This spec instead documents the real behaviour and works around it: it targets `example.net` (not the
`example.com` key tests 3, 8, and 9 depend on being sessionless) and cleans up the record its own call creates.

## Why this spec is not "free" the way 1, 4, 8, and 9 are

Every other cheap ascend-web-hunter spec either touches no external process at all or only Redis. This one is
different: `SessionManager.establish` launches a real headful Chromium browser through Playwright and hands it to
NoVNC, then starts a background monitor task (`_monitor_for_cookies`) that polls the page for up to
`NOVNC_TIMEOUT_SECONDS` (600 seconds / 10 minutes by default) before giving up and closing the browser on its own —
or, per the finding above, stops within one poll cycle once it decides the page is "cleared." Nothing in this test
asks a human to act; the response assertions are satisfiable immediately, and even the Redis assertion below only
needs a short, bounded wait, not the full 10-minute ceiling. But when the monitor does not resolve this quickly (a
genuinely challenged or slow-loading target), the call still leaves a live, resource-consuming browser + VNC
session running in the background for up to 10 minutes. Running this spec back to back without letting a previous
run's monitor finish will stack multiple live headful browsers in the same container. Treat it as the highest
per-run resource cost in this module's suite, higher than test 6 or 7's Playwright/FlareSolverr usage, even though —
like every other ascend-web-hunter spec — it makes no call to any priced LLM or embedding provider and so still
belongs in the cost-free set in dollar terms.

## Prerequisites

Check Bruno CLI is installed.

```powershell
bru --version
```

Expect a version string.

Check the ascend-web-hunter server is reachable.

```powershell
curl -fsS http://localhost:7021/health
```

Expect HTTP 200 with `{"status":"ok"}`.

Check Redis is reachable from the host's Docker context (this test seeds nothing but does inspect and clean up a
key the call itself creates).

```powershell
docker exec redis redis-cli PING
```

Expect `PONG`.

## Reset state

Confirm `example.net` currently carries no session (IANA-reserved documentation domain; test 8 is the only other
spec that touches its `default`-profile key, and only transiently during its own run).

```powershell
docker exec redis redis-cli EXISTS "session:example.net:default"
```

Expect `0`. If it returns `1`, a previous run of this spec (or of test 8) did not clean up — delete it before
continuing.

```powershell
docker exec redis redis-cli DEL "session:example.net:default"
```

## Run

Move into the Bruno collection root first.

```powershell
cd docs/api/request/AscendAI
```

```powershell
bru run "web-hunter/testing/session-establish.yml" --env ascend-local
```

## Expected

- HTTP 200. Body `status` equals `"login_required"`, `target` equals `"https://example.net/"`, `vnc_url` is a
  non-empty string.
- Wait 15 seconds for the background monitor's first poll cycle (`NOVNC_COOKIE_SYNC_POLL_SECONDS` is 5 seconds by
  default; 15 gives a safe margin over browser launch + navigation), then confirm the capture the "Two behaviours"
  section above describes actually happened:

  ```powershell
  docker exec redis redis-cli EXISTS "session:example.net:default"
  ```

  Expect `1` — this is the documented current behaviour, not a defect this spec is trying to catch.

- Clean up the record this test created, so `example.net` is sessionless again for test 8 or a repeat of this test:

  ```powershell
  docker exec redis redis-cli DEL "session:example.net:default"
  ```

  ```powershell
  docker exec redis redis-cli EXISTS "session:example.net:default"
  ```

  Expect `0`.

## Concurrency

Do not run this test in parallel with test 8 ([8-session-clear-test.md](8-session-clear-test.md)) — both mutate
`session:example.net:default`, and this test's capture races test 8's own seed/clear sequence on the same key. Safe
to run in parallel with everything else in the suite.

## Fixtures

None.
