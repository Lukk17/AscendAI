# CAPTCHA solve and session reuse: e2e test

## What this verifies

Two things, both against the real democaptcha hCaptcha demo form (no mocks), with a human in the loop between them:

1. Human intervention contract. A read of `https://democaptcha.com/demo-form-eng/hcaptcha.html` with no stored
   session answers HTTP 428, `status="human_intervention_required"` and a non-empty `vnc_url`. The page's
   `hcaptcha.com/1/api.js` script is one of the block signatures in `src/reader/cloudflare/challenge_dictionary.json`,
   so every automated tier reports a challenge (measured on 2026-09-10: 26 seconds from the request to the NoVNC
   monitor starting) and the scraper escalates to NoVNC for a human to act.
2. Session reuse. After the human solves the widget and submits the form in the NoVNC browser, the monitor captures
   the page's session under `session:democaptcha.com:default`, and a second read of the same URL answers HTTP 200,
   `status="success"` and a content-carrying field of at least 50 characters, with no 428. This is the whole point of
   the spec: the reader routes a read of a site with a stored session onto the browser tier with the saved cookies.
   `WebReader._prefer_browser` in `src/reader/web_reader.py` returns true when `WebReader._has_stored_session` finds a
   storage state for the URL and profile, and `_select_strategies` then runs only the Playwright, Crawlee and NoVNC
   strategies, so the saved cookies ride along on the first attempt. If Call 2 answers 428, the verdict is FAIL and
   the finding is a product defect to register in `docs/DEFECT_REGISTER.md`, not an environment problem.

Between the two calls, a capture check confirms what the human solve left behind: `session:democaptcha.com:default`
holds an auth cookie named `hmt_id` (domain `api.hcaptcha.com`). hCaptcha sets `hmt_id` when the checkbox is clicked,
so its presence proves a human acted in the NoVNC window. It does not prove the image task was solved: the monitor
also clears on a Submit with the widget unsolved, because the failure page has enough words and carries no block
script. A research pass found no public page that both escalates through the tiers and sets a cookie only on a
successful solve, so this is the accepted trade, and Call 2 is what turns the capture into a proof of reuse.

Google's reCAPTCHA v2 demo was the previous target and was dropped because its script stays in the DOM after the
solve, so the monitor can never declare that address cleared, and its `_GRECAPTCHA` cookie appears on a bare load, so
it proved nothing about a human.

### Contract (how the service signals each verdict)

- success: HTTP `200`, body `status="success"`, non-empty content.
- intervention: HTTP `428 Precondition Required`, body `status="human_intervention_required"` and a non-empty
  `vnc_url`. This is the documented interactive-challenge contract (`api/exception_handlers.py`).
- busy, not a verdict: HTTP `409`, body `status="novnc_busy"` with a `holder_url`, and a `Retry-After` header,
  meaning another intervention still holds the single shared browser. This spec runs alone, so a 409 on Call 1 means
  a monitor from an earlier run is still open. Wait the `Retry-After` seconds and re-run Call 1, up to 3 attempts in
  total, recording each attempt and the `holder_url` in the run record.

### Human-intervention forwarding (mandatory)

Any call in this test that returns `status="human_intervention_required"` returns a `vnc_url` that a human must
open. The agent driving the test must print that `vnc_url` verbatim into the chat the moment it is received, then
wait for the human to confirm they solved it before the capture check.

Because a fanned-out `e2e-runner` subagent's output is never shown to the user, the human solve (and any
intervention this test surfaces that a human must act on) must be run by the main agent/session, not delegated to a
subagent. This test has no automated part that may fan out: it runs alone. If this test is ever delegated despite
this, the main agent must re-print the subagent's `vnc_url` to the user. Otherwise the human never receives the link
and the test stalls forever.

## Prerequisites

Check Bruno CLI is installed.

```bash
bru --version
```

Expect a version string.

Check the ascend-web-hunter server is reachable.

```bash
curl -fsS http://localhost:7021/health
```

Expect HTTP 200 with `{"status":"ok"}`.

Check FlareSolverr is reachable (Call 1 walks every automated tier before it escalates to NoVNC).

```bash
curl -fsS http://localhost:8191/
```

Expect HTTP 200.

Check Redis is reachable from the host's Docker context (the capture check reads the key the monitor writes).

```bash
docker exec redis redis-cli PING
```

Expect `PONG`.

No credentials are needed: the human types nothing, they solve the widget in the NoVNC browser.

## Reset state

Delete the democaptcha session so Call 1 starts from a genuine blocked state. A stale capture would route Call 1
straight onto the browser tier and hide the intervention contract. The command is identical in PowerShell and Unix
shells.

```bash
docker exec redis redis-cli DEL "session:democaptcha.com:default"
```

Expect `0` or `1`. Then confirm the key is gone.

```bash
docker exec redis redis-cli EXISTS "session:democaptcha.com:default"
```

Expect `0`.

## Run

> Execution model: this whole test is run by the main agent on the main session, never by an `e2e-runner`
> subagent, whose output is not shown to the user. Call 1 returns a `vnc_url`. The main agent prints that `vnc_url`
> verbatim in the chat and waits for you to solve the challenge in the NoVNC browser before the capture check and
> Call 2. See "Human-intervention forwarding (mandatory)" above.

Move into the Bruno collection root first.

```bash
cd docs/api/request/AscendAI
```

1. Call 1, blocked. Read the demo form with no session.

```bash
bru run "web-hunter/testing/captcha-clearance-blocked.yml" --env ascend-local
```

2. Human solve. Print the `vnc_url` from the Call 1 response verbatim in the chat. The human opens it, ticks the
   hCaptcha checkbox, solves any image task, and presses the form's Submit. The monitor declares the challenge
   cleared when Submit navigates to a response page without the widget, and captures that page's session under
   `session:democaptcha.com:default`. Wait for the human to confirm before continuing.

3. Capture check, after the human confirms.

```bash
docker exec redis redis-cli GET "session:democaptcha.com:default"
```

Expect a JSON value whose `auth` entry contains an `hmt_id` cookie.

4. Call 2, reuse. Read the same URL again with no profile, so the read resolves to the `default` profile the monitor
   captured under.

```bash
bru run "web-hunter/testing/captcha-clearance-reuse.yml" --env ascend-local
```

## Expected

- Call 1: HTTP `428`, `status="human_intervention_required"`, `vnc_url` is a non-empty string. The main agent
  printed the `vnc_url` verbatim in the chat.
- Capture check: `session:democaptcha.com:default` exists and its `auth` entry carries a cookie named `hmt_id`. On
  the 2026-09-10 solve the `auth` entry also carried `evod95wg4` (democaptcha.com) and `__cflb` (api.hcaptcha.com),
  and the `waf` entry carried `__cf_bm` (.hcaptcha.com), none of which are asserted.
- Call 2: HTTP `200`, `status="success"`, and one of `content`, `text` or `markdown` is a string of at least 50
  characters. No `428`. A `428` on Call 2 is a FAIL, and the finding goes into `docs/DEFECT_REGISTER.md` as a
  product defect in the stored-session routing (`_prefer_browser` and `_has_stored_session` in
  `src/reader/web_reader.py`), not into the run record as an environment problem.
- Clean up the record this test created, so the next run starts blocked again. The command is identical in
  PowerShell and Unix shells.

  ```bash
  docker exec redis redis-cli DEL "session:democaptcha.com:default"
  ```

  ```bash
  docker exec redis redis-cli EXISTS "session:democaptcha.com:default"
  ```

  Expect `0`.

## Fixtures

None, and no secrets: the captcha is human-solved. The URL is hardcoded in the two Bruno requests.

## Concurrency

- Mutates: Redis, the ascend-web-hunter session store, key `session:democaptcha.com:default`, plus the single shared
  NoVNC browser for as long as the human window is open (`NOVNC_TIMEOUT_SECONDS`, 600 s by default, if nobody
  solves it).
- Conflicts with: any spec that opens the human window (test 7's row u, test 10, and any read that escalates to
  NoVNC), because the service holds one shared browser and answers `409` `novnc_busy` while it is held, and any test
  that flushes `session:*` (test 7's reset), which would wipe the capture between the two calls.
- Serial: true. Runs alone, last in the sweep, and only on a human's go, with the human on the main session.
