# CAPTCHA solve and capture: e2e test

## What this verifies

Two things, both against the real democaptcha hCaptcha demo form (no mocks), with a human in the loop between them:

1. Human intervention contract. A read of `https://democaptcha.com/demo-form-eng/hcaptcha.html` with no stored
   session answers HTTP 428, `status="human_intervention_required"` and a non-empty `vnc_url`. The page's
   `hcaptcha.com/1/api.js` script is one of the block signatures in `src/reader/cloudflare/challenge_dictionary.json`,
   so every automated tier reports a challenge (measured on 2026-09-10: 26 seconds from the request to the NoVNC
   monitor starting) and the scraper escalates to NoVNC for a human to act.
2. Capture. After the human solves the widget and submits the form in the NoVNC browser, the monitor captures the
   page's session under `session:democaptcha.com:default`, and that record holds an auth cookie named `hmt_id`
   (domain `api.hcaptcha.com`). hCaptcha sets `hmt_id` when the checkbox is clicked, so its presence proves a human
   acted in the NoVNC window. It does not prove the image task was solved: the monitor also clears on a Submit with
   the widget unsolved, because the failure page has enough words and carries no block script. A research pass
   found no public page that both escalates through the tiers and sets a cookie only on a successful solve, so this
   is the accepted trade.

Reuse of the captured session is not asserted here. It is proven by spec 12
([12-clearance-reuse-test.md](12-clearance-reuse-test.md)) on a site whose wall disappears once the clearance is
stored, because the democaptcha form renders its widget on every load, so a second read of it carries the block
signature whatever cookies the browser holds (measured 2026-09-10, register A60).

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
> verbatim in the chat and waits for you to solve the challenge in the NoVNC browser before the capture check. See
> "Human-intervention forwarding (mandatory)" above.

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

## Expected

- Call 1: HTTP `428`, `status="human_intervention_required"`, `vnc_url` is a non-empty string. The main agent
  printed the `vnc_url` verbatim in the chat.
- Capture check: `session:democaptcha.com:default` exists and its `auth` entry carries a cookie named `hmt_id`. On
  the 2026-09-10 solve the `auth` entry also carried `evod95wg4` (democaptcha.com) and `__cflb` (api.hcaptcha.com),
  and the `waf` entry carried `__cf_bm` (.hcaptcha.com), none of which are asserted.
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

None, and no secrets: the captcha is human-solved. The URL is hardcoded in the Bruno request.

## Concurrency

- Mutates: Redis, the ascend-web-hunter session store, key `session:democaptcha.com:default`, plus the single shared
  NoVNC browser for as long as the human window is open (`NOVNC_TIMEOUT_SECONDS`, 600 s by default, if nobody
  solves it).
- Conflicts with: any spec that opens the human window (test 7's row u, test 10, and any read that escalates to
  NoVNC), because the service holds one shared browser and answers `409` `novnc_busy` while it is held, and any test
  that flushes `session:*` (test 7's reset), which would wipe the capture before the capture check.
- Serial: true. Runs alone, last in the sweep, and only on a human's go, with the human on the main session.
