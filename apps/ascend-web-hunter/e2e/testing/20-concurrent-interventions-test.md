# Concurrent interventions: e2e test

## What this verifies

That the service holds several NoVNC intervention windows at once, one flow per profile, against one wall page.

`POST /api/v2/web/read` of the synthetic captcha wall page `/turnstile-wall` of task 11.9 on the shared fake
site under its allowed name `e2e-fake-site` (design D12 of `add-web-search-scraping-e2e`, owner answer 67.3 of
2026-10-04), read under the profiles `e2e-w1` to `e2e-w6`: the first five profiles open five distinct flows and
the sixth profile is refused. The page is a
thin page holding only a title, one short line asking the visitor to confirm they are human, and a
`<div class="cf-turnstile">` element, with no script, which `ChallengeDetector.is_blocked` treats as a wall
(its `cf-turnstile` rule for a page under `CHALLENGE_WALL_MAX_BYTES`) and the read escalates to NoVNC.

Prerequisite: `GET /api/v2/session/interventions` reports `active_flows` 0 and `max_concurrent_flows` 5
(the listing fields of design Decision 9).

Run and Expected, each step checked before the next:

1. Reads under `e2e-w1` to `e2e-w4` each answer HTTP 428 with the problem body check of design D13 of
   `add-web-search-scraping-e2e` (`code` `human_intervention_required`, `type`, `status`, `instance`, `traceId`,
   non-empty `vnc_url`), `joined` false, four distinct `flow_id` values, four distinct `window.slot` values, and a
   `window` position and size inside the display size `NOVNC_DISPLAY_SIZE` the startup banner prints.
2. The REST listing reports `active_flows` 4, `max_concurrent_flows` 5 and each `flow_id` once with its target,
   profile, slot, window and a positive remaining lease, and its body holds no cookie name, cookie value or
   storage state. The MCP `session_interventions` tool returns the same four `flow_id` values.
3. A read under `e2e-w5` answers HTTP 428 with the problem body check of step 1, `joined` false, a fifth
   distinct `flow_id` and a fifth distinct `window.slot` inside the display size. Then a read under `e2e-w6`
   answers HTTP 409 with the problem body check (`code` `novnc_busy`), a `Retry-After` header, `active_flows`
   5, `max_concurrent_flows` 5, `flows` with five entries and `holder_url` naming the oldest flow.
4. A second read under `e2e-w2` answers HTTP 428 with `joined` true and the `flow_id` of step 1 for `e2e-w2`, and
   the listing still reports `active_flows` 5.
5. `/ready` answers the same status it answered before step 1, and a read of the fake site's plain article page
   answers HTTP 200 with `status` `success`.
6. `/metrics` shows `novnc_active_flows` 5, `human_intervention_total{joined="true"}` one higher and
   `novnc_flow_busy_total` one higher than before step 1.
7. Cleanup waits, polling the listing, until it reports `active_flows` 0 (at most the flow lease of design
   Decision 7 plus one sweep interval), then asserts no `session:<fake site domain>:e2e-w*` key and no
   `novnc_flow:<fake site domain>:e2e-w*` key exists in Redis, because nobody solved a wall. Review item C13 of
   the overengineering review proposes a restart of ascend-web-hunter in place of this wait. It waits for the
   owner's yes, so the wait stays until then.

## Concurrency

It fills every window slot, so it runs alone, with no other spec that can answer a 428 (7, 10, 11, 12 and the
wall spec of `detect-challenge-walls-in-any-language`).

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

Expect HTTP 200 with `status` `ok`, `service` `ascend-web-hunter` and a non-empty `version`.

Check the fake site is reachable from the host.

```bash
curl -fsS http://127.0.0.1:7031/__requests
```

Expect a request list.

Check Redis is reachable from the host's Docker context (the cleanup step asserts the flow keys are gone).

```bash
docker exec redis redis-cli PING
```

Expect `PONG`.

Check no intervention flow is left over from an earlier run and the cap is 5.

```bash
curl -fsS http://localhost:7021/api/v2/session/interventions
```

Expect a body with `active_flows` `0` and `max_concurrent_flows` `5`. If `active_flows` is not `0`, wait for the
flows to drain and retry; do not start the rows while a flow is still open.

## Reset state

No persistent state needs wiping: reads are stateless against the fake site, nobody solves a wall so no session
record is written, and the Prerequisites check already gates on a drained flow registry.

## Run

Move into the Bruno collection root first.

```bash
cd docs/api/request/AscendAI
```

The Bruno requests below live in `web-hunter/testing/interventions/` (added by task 11.4).

Step 0 - capture the baselines before any row runs, so steps 5 and 6 can measure against them. Record the
`/ready` status and the `NOVNC_DISPLAY_SIZE` value the startup banner prints for the window bounds check of
step 1.

```bash
curl -fsS http://localhost:7021/ready
```

```bash
curl -fsS http://localhost:7021/metrics -o /tmp/concurrent-interventions-before.txt
```

Step 1 - open four windows, one request per profile. The open request takes the profile from an environment
variable (named and defined by task 11.4); run it once with that variable set to each of `e2e-w1`, `e2e-w2`,
`e2e-w3` and `e2e-w4` in that order, and wait for HTTP 428 before continuing.

```bash
bru run "web-hunter/testing/interventions/intervention-window-open.yml" --env ascend-local
```

```bash
bru run "web-hunter/testing/interventions/intervention-window-open.yml" --env ascend-local
```

```bash
bru run "web-hunter/testing/interventions/intervention-window-open.yml" --env ascend-local
```

```bash
bru run "web-hunter/testing/interventions/intervention-window-open.yml" --env ascend-local
```

The four runs above use the profiles `e2e-w1`, `e2e-w2`, `e2e-w3` and `e2e-w4` in that order, one window per
profile. Record each response's `flow_id` and `window.slot` in the run record.

Step 2 - list the flows from both surfaces.

```bash
bru run "web-hunter/testing/interventions/interventions-list.yml" --env ascend-local
```

```bash
bru run "web-hunter/testing/interventions/mcp-session-interventions.yml" --env ascend-local
```

Step 3 - the fifth window opens, the sixth does not fit. Send one read under `e2e-w5` through the open
request and wait for HTTP 428; record its `flow_id` and `window.slot`. Then send one read under `e2e-w6` and
wait for HTTP 409.

```bash
bru run "web-hunter/testing/interventions/intervention-window-open.yml" --env ascend-local --env-var profile=e2e-w5
```

```bash
bru run "web-hunter/testing/interventions/intervention-window-6th-busy.yml" --env ascend-local
```

Step 4 - rejoining an open flow answers the same flow. Send a second read under `e2e-w2` and wait for
HTTP 428.

```bash
bru run "web-hunter/testing/interventions/intervention-window-duplicate-join.yml" --env ascend-local
```

Then confirm the listing still reports `active_flows` `5`.

```bash
curl -fsS http://localhost:7021/api/v2/session/interventions
```

Step 5 - the stack still serves beside five open windows.

```bash
curl -fsS http://localhost:7021/ready
```

```bash
curl -fsS -X POST http://localhost:7021/api/v2/web/read -H "Content-Type: application/json" -d '{"url":"http://e2e-fake-site:7031/article"}'
```

The article request reads the fake site's plain article page under its allowed name `e2e-fake-site`. It needs
no Bruno file: the page carries no challenge, so one anonymous `POST /api/v2/web/read` answers HTTP 200 with
`status` `success`.

Step 6 - capture the metrics output after the run for the growth comparison.

```bash
curl -fsS http://localhost:7021/metrics -o /tmp/concurrent-interventions-after.txt
```

Step 7 - cleanup. Wait until every NoVNC flow the window rows opened has drained. Nobody solved a wall, so each
flow expires on its lease and the sweeper frees its slot. The bound is the flow lease of design Decision 7 plus
one sweep interval, polled every 10 seconds.

**Unix:**

```bash
for i in $(seq 1 66); do if [ "$(curl -fsS http://localhost:7021/api/v2/session/interventions | python3 -c 'import json,sys; print(json.load(sys.stdin)["active_flows"])')" = "0" ]; then break; fi; sleep 10; done; curl -fsS http://localhost:7021/api/v2/session/interventions
```

**PowerShell:**

```powershell
for ($i = 0; $i -lt 66 -and ((Invoke-RestMethod http://localhost:7021/api/v2/session/interventions).active_flows) -ne 0; $i++) { Start-Sleep 10 }; Invoke-RestMethod http://localhost:7021/api/v2/session/interventions
```

Expect the final body to report `active_flows` `0`. Then assert no flow key survived in Redis.

```bash
docker exec redis redis-cli --scan --pattern "session:e2e-fake-site:e2e-w*"
```

```bash
docker exec redis redis-cli --scan --pattern "novnc_flow:e2e-fake-site:e2e-w*"
```

Expect no output from either scan.

## Expected

- **Step 1:** four HTTP 428 answers, one per profile `e2e-w1` to `e2e-w4`. Each problem body holds `code`
  `human_intervention_required`, `type`, `status`, `instance`, `traceId`, a non-empty `vnc_url` and `joined`
  `false`. The four `flow_id` values are distinct, the four `window.slot` values are distinct, and each
  `window` position (`x`, `y`) plus size (`width`, `height`) sits inside the `NOVNC_DISPLAY_SIZE` display from
  Step 0.
- **Step 2:** the REST listing body reports `active_flows` `4` and `max_concurrent_flows` `5`, and its `flows`
  array holds each step-1 `flow_id` exactly once, each with its target URL, profile, slot, window and a
  positive `expires_in_seconds`. The body carries no `cookies`, no `storage_state` and no page content. The
  MCP `session_interventions` result holds the same four `flow_id` values.
- **Step 3:** the `e2e-w5` read answers HTTP `428` with the step-1 problem body check, `joined` `false`,
  a fifth distinct `flow_id` and a fifth distinct `window.slot` inside the Step 0 display size. The `e2e-w6`
  read answers HTTP `409`. Its problem body holds `code` `novnc_busy`, `active_flows` `5`,
  `max_concurrent_flows` `5`, `flows` with five entries, and `holder_url` naming the oldest flow of steps 1
  and 3. The response carries a `Retry-After` header.
- **Step 4:** HTTP `428` with `joined` `true` and the step-1 `flow_id` of `e2e-w2`. The listing still reports
  `active_flows` `5`, so the rejoin opened no sixth flow.
- **Step 5:** `/ready` answers the same status it answered in Step 0, and the article read answers HTTP 200
  with `status` `success`.
- **Step 6:** `novnc_active_flows` is `5` in the after-output:

  ```bash
  grep '^novnc_active_flows' /tmp/concurrent-interventions-after.txt
  ```

  `human_intervention_total` with `joined="true"` is exactly one higher in the after-output than in the
  baseline, and `novnc_flow_busy_total` is exactly one higher:

  ```bash
  grep 'human_intervention_total{[^}]*joined="true"' /tmp/concurrent-interventions-before.txt /tmp/concurrent-interventions-after.txt
  ```

  ```bash
  grep 'novnc_flow_busy_total' /tmp/concurrent-interventions-before.txt /tmp/concurrent-interventions-after.txt
  ```

- **Step 7:** the final `GET /api/v2/session/interventions` body reports `active_flows` `0`, and both Redis
  scans print nothing.

Every assertion above is an HTTP status, a response body, `/metrics`, or a Redis key.

## Fixtures

None checked in. The `/turnstile-wall` page carries the canary
`Please confirm you are human to continue.`, indexed in [fixtures/README.md](../fixtures/README.md). The six
profiles `e2e-w1` to `e2e-w6` exist only as profile names on the read requests; no session is ever stored under
them.
