# CAPTCHA solve and capture: e2e test

## What this verifies

Two things, both against the real democaptcha hCaptcha demo form (no mocks), with a human in the loop between them:

1. Human intervention contract. A read of `https://democaptcha.com/demo-form-eng/hcaptcha.html` with no stored
   session answers HTTP 428, `code="human_intervention_required"` and a non-empty `vnc_url`. The page's
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
- intervention: HTTP `428 Precondition Required`, body `code="human_intervention_required"` and a non-empty
  `vnc_url`. This is the documented interactive-challenge contract (`api/exception_handlers.py`).
- busy, not a verdict: HTTP `409`, body `code="novnc_busy"` with a `holder_url`, and a `Retry-After` header,
  meaning another intervention still holds the single shared browser. This spec runs alone, so a 409 on Call 1 means
  a monitor from an earlier run is still open. Wait the `Retry-After` seconds and re-run Call 1, up to 3 attempts in
  total, recording each attempt and the `holder_url` in the run record.

### Human-intervention forwarding (mandatory)

Any call in this test that returns `code="human_intervention_required"` returns a `vnc_url` that a human must
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
curl -fsS http://127.0.0.1:7021/health
```

Expect HTTP 200 with `status` `ok`, `service` `ascend-web-hunter` and a non-empty `version`.

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

Part 2 uses two more profiles, so start it with both of their keys absent too.

```bash
docker exec redis redis-cli DEL "session:democaptcha.com:e2e-h1" "session:democaptcha.com:e2e-h2"
```

Expect `0`, `1` or `2` in total. Then confirm both keys are gone.

```bash
docker exec redis redis-cli EXISTS "session:democaptcha.com:e2e-h1" "session:democaptcha.com:e2e-h2"
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

### Part 2 - Two windows solved out of order

Part 1 proved one window and its capture under the default profile. Part 2 proves two windows at once,
cleared in the opposite order they were opened: the runner opens the `e2e-h1` window first and the `e2e-h2`
window second, the human solves `e2e-h2` first and `e2e-h1` second, and after each solve the runner asserts
the listing freed exactly that flow's slot and the solved profile's session holds the `hmt_id` cookie while
the other profile's key is unchanged.

4. Call 2, blocked under `e2e-h1`. Send the same demo-form read with `"profile": "e2e-h1"` added to the
   `captcha-clearance-blocked.yml` body (an alternative payload is an edit of the request file, per "Bruno is
   the source of truth" in [testing/README.md](README.md), not a new file).

```bash
bru run "web-hunter/testing/captcha-clearance-blocked.yml" --env ascend-local
```

Expect HTTP 428 with a new `flow_id` and its own `window.slot`. Record both.

5. Call 3, blocked under `e2e-h2`. Send the same read with `"profile": "e2e-h2"`.

```bash
bru run "web-hunter/testing/captcha-clearance-blocked.yml" --env ascend-local
```

Expect HTTP 428 with a second new `flow_id` and a different `window.slot`. Print both `vnc_url` values
and both slots verbatim in the chat.

6. Human solves the `e2e-h2` window first, then confirms. After the confirmation, check the listing freed
   exactly that flow's slot while the `e2e-h1` flow is still open.

```bash
curl -fsS http://127.0.0.1:7021/api/v2/session/interventions
```

Expect the `flows` array to hold the Call 2 `flow_id` with its slot and no entry with the Call 3 slot.

7. Capture check for `e2e-h2`, after the human confirms.

```bash
docker exec redis redis-cli GET "session:democaptcha.com:e2e-h2"
```

Expect a JSON value whose `auth` entry contains an `hmt_id` cookie. Then confirm the `e2e-h1` key is
unchanged (still absent, nobody solved that window yet).

```bash
docker exec redis redis-cli EXISTS "session:democaptcha.com:e2e-h1"
```

Expect `0`.

8. Human solves the `e2e-h1` window second, then confirms. Check the listing holds neither flow any
   longer.

```bash
curl -fsS http://127.0.0.1:7021/api/v2/session/interventions
```

Expect no entry with the Call 2 `flow_id` and none with the Call 3 `flow_id`.

9. Capture check for `e2e-h1`, after the human confirms.

```bash
docker exec redis redis-cli GET "session:democaptcha.com:e2e-h1"
```

Expect a JSON value whose `auth` entry contains an `hmt_id` cookie. Re-read the `e2e-h2` key and confirm
it still holds the record step 7 saw, unchanged by the second solve.

## Expected

- Call 1: HTTP `428`, `code="human_intervention_required"`, `vnc_url` is a non-empty string. The main agent
  printed the `vnc_url` verbatim in the chat.
- Capture check: `session:democaptcha.com:default` exists and its `auth` entry carries a cookie named `hmt_id`. On
  the 2026-09-10 solve the `auth` entry also carried `evod95wg4` (democaptcha.com) and `__cflb` (api.hcaptcha.com),
  and the `waf` entry carried `__cf_bm` (.hcaptcha.com), none of which are asserted.
- Part 2, open: Call 2 under `e2e-h1` and Call 3 under `e2e-h2` each answer HTTP `428` with their own `flow_id`
  and their own `window.slot`, the two slots different. Both `vnc_url` values and both slots were printed verbatim
  in the chat.
- Part 2, `e2e-h2` solved first: the listing holds the Call 2 `flow_id` with its slot and no entry with the Call
  3 slot; `session:democaptcha.com:e2e-h2` exists with an `hmt_id` cookie in its `auth` entry; and
  `session:democaptcha.com:e2e-h1` is still absent.
- Part 2, `e2e-h1` solved second: the listing holds neither `flow_id`; `session:democaptcha.com:e2e-h1` exists
  with an `hmt_id` cookie in its `auth` entry; and the `e2e-h2` record is unchanged.
- Clean up the record this test created, so the next run starts blocked again. The command is identical in
  PowerShell and Unix shells.

  ```bash
  docker exec redis redis-cli DEL "session:democaptcha.com:default"
  ```

  ```bash
  docker exec redis redis-cli EXISTS "session:democaptcha.com:default"
  ```

  Expect `0`.

- Clean up the Part 2 records too.

  ```bash
  docker exec redis redis-cli DEL "session:democaptcha.com:e2e-h1" "session:democaptcha.com:e2e-h2"
  ```

  ```bash
  docker exec redis redis-cli EXISTS "session:democaptcha.com:e2e-h1" "session:democaptcha.com:e2e-h2"
  ```

  Expect `0`.

## Fixtures

None, and no secrets: the captcha is human-solved. The URL is hardcoded in the Bruno request.

## Concurrency

- Mutates: Redis, the ascend-web-hunter session store, keys `session:democaptcha.com:default`,
  `session:democaptcha.com:e2e-h1` and `session:democaptcha.com:e2e-h2`, plus up to two NoVNC
  window slots for as long as the human windows are open (`NOVNC_TIMEOUT_SECONDS`, 600 s by default, if nobody
  solves them).
- Conflicts with: any spec that opens a NoVNC flow (test 7's 428 rows, test 10, the wall rows of spec 19
  ([19-challenge-verdicts-test.md](19-challenge-verdicts-test.md)), spec 20
  ([20-concurrent-interventions-test.md](20-concurrent-interventions-test.md)), and any read that escalates to
  NoVNC), because the service answers `409` `novnc_busy` while every window slot is held. Test 7's reset deletes
  only the named keys of its own domains, none of them on `democaptcha.com`, so it does not touch the capture.
- Serial: true. Runs alone, last in the sweep, and only on a human's go, with the human on the main session.
