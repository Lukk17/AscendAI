# Challenge verdicts on the fake site: e2e test

## What this verifies

`POST /api/v2/web/read` returns the gated challenge verdict for each page of the shared e2e fake site,
read under its allowed name `e2e-fake-site` (design D11 and D12 of `add-web-search-scraping-e2e`,
owner answer 67.3 of 2026-10-04). The fake site pages are the ones task 11.12 adds or rebuilds, served
from `e2e/fake-site/pages/`, and the unit test `tests/reader/cloudflare/test_fake_site_verdicts.py` runs
`assess` over the same page files, so these rows and the unit test judge the same markup.

Rows, with their fake site path and gated verdict:

1. `/wall-ko`, a site's own captcha page in Korean with no vendor marker: HTTP 428 with
   `intervention_type` `captcha`.
2. `/wall-tr`, a Turkish login form with a password input and a captcha input: HTTP 428 with
   `intervention_type` `login`.
3. `/wall-vendor-thin`, a catalogued vendor script on a thin page: HTTP 428.
4. `/wall-header`, a 403 carrying the definitive `cf-mitigated` challenge header beside a rich body:
   HTTP 428.
5. `/wall-oversized`, a wall page larger than `CHALLENGE_DETECTION_MAX_BYTES`: HTTP 428.
6. `/captcha-wall`, a blog post of at least 150 words with a catalogued widget under its comment form:
   HTTP 200 with `status` `success` and its canary sentence.
7. `/article-ja`, a Japanese article with no vendor marker: HTTP 200 `success` with its canary sentence.
8. `/article-ar`, an Arabic article with no vendor marker: HTTP 200 `success` with its canary sentence.
9. `/prose-captcha`, a page with the word `captcha` only in its prose: HTTP 200 `success`.
10. `/rich-403`, a 403 with a rich body and no other signal: any answer but HTTP 428.

Every 428 passes the problem body check of design D13 of `add-web-search-scraping-e2e` with a non-empty
`vnc_url`. After the rows, `/metrics` shows `challenge_verdicts_total` with `verdict="wall"` grown by
the number of wall rows and with `verdict="content"` grown by at least the number of content rows, and
every `vendor` label value of `challenge_signals_fired_total` is a catalogue vendor name or the fixed
label `none` of the observability spec. Cleanup waits until `GET /api/v2/session/interventions`
reports `active_flows` 0.

## Concurrency

Each wall row opens a NoVNC flow. This spec does not run beside the concurrent intervention spec of
`open-several-novnc-windows-at-once` or any spec that can answer a 428.

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

Check no intervention flow is left over from an earlier run.

```bash
curl -fsS http://localhost:7021/api/v2/session/interventions
```

Expect a body with `active_flows` `0`. If it is not `0`, wait for the flows to drain and retry; do not
start the rows while a flow is still open.

## Reset state

No persistent state needs wiping: reads are stateless against the fake site, and the Prerequisites
check already gates on a drained flow registry.

## Run

Move into the Bruno collection root first.

```bash
cd docs/api/request/AscendAI
```

The Bruno requests below live in `web-hunter/testing/challenge-verdicts/` (added by task 11.9 of
`detect-challenge-walls-in-any-language`).

Step 0 - capture the metrics baseline before any row runs, so the Expected section can measure growth.

```bash
curl -fsS http://localhost:7021/metrics -o /tmp/challenge-verdicts-before.txt
```

Wall rows. Send one request per row and wait for HTTP 428 before continuing.

> Repair 2026-10-26 (no owning tasks box; documented here like the cap-5 fix): back-to-back wall
> rows joined one live flow. Flows are keyed by registrable domain + profile, so every wall row here
> shares `e2e-fake-site:default`: wall-tr's read joined wall-ko's still-live flow and answered
> `intervention_type` `captcha` instead of its specified `login` (run records
> `2026-10-26T09-37-51_19-challenge-verdicts-tasks.md` and
> `2026-10-26T10-30-00_19-challenge-verdicts-tasks.md`; every tier verdict log says `type=login`
> for the page while the 428 carries `captcha` from the joined flow). Each wall row after the first
> therefore starts with a drain: poll `GET /api/v2/session/interventions` until `active_flows` is
> `0`, up to 90 polls of 10 seconds (the flow lease plus sweep bound, as in Cleanup). The wall-tr
> row on a drained registry is the proof: it must answer `login` on its own fresh flow.

```bash
bru run "web-hunter/testing/challenge-verdicts/wall-own-captcha-korean.yml" --env ascend-local
```

Drain before the next wall row (see repair note above).

```bash
for i in $(seq 1 90); do if [ "$(curl -fsS http://localhost:7021/api/v2/session/interventions | python3 -c 'import json,sys; print(json.load(sys.stdin)["active_flows"])')" = "0" ]; then break; fi; sleep 10; done; curl -fsS http://localhost:7021/api/v2/session/interventions
```

```bash
bru run "web-hunter/testing/challenge-verdicts/wall-login-turkish.yml" --env ascend-local
```

Drain before the next wall row (see repair note above).

```bash
for i in $(seq 1 90); do if [ "$(curl -fsS http://localhost:7021/api/v2/session/interventions | python3 -c 'import json,sys; print(json.load(sys.stdin)["active_flows"])')" = "0" ]; then break; fi; sleep 10; done; curl -fsS http://localhost:7021/api/v2/session/interventions
```

```bash
bru run "web-hunter/testing/challenge-verdicts/wall-vendor-script-thin.yml" --env ascend-local
```

Drain before the next wall row (see repair note above).

```bash
for i in $(seq 1 90); do if [ "$(curl -fsS http://localhost:7021/api/v2/session/interventions | python3 -c 'import json,sys; print(json.load(sys.stdin)["active_flows"])')" = "0" ]; then break; fi; sleep 10; done; curl -fsS http://localhost:7021/api/v2/session/interventions
```

```bash
bru run "web-hunter/testing/challenge-verdicts/wall-definitive-header.yml" --env ascend-local
```

Drain before the next wall row (see repair note above).

```bash
for i in $(seq 1 90); do if [ "$(curl -fsS http://localhost:7021/api/v2/session/interventions | python3 -c 'import json,sys; print(json.load(sys.stdin)["active_flows"])')" = "0" ]; then break; fi; sleep 10; done; curl -fsS http://localhost:7021/api/v2/session/interventions
```

```bash
bru run "web-hunter/testing/challenge-verdicts/wall-oversized.yml" --env ascend-local
```

Content rows. Send one request per row and wait for its answer before continuing.

```bash
bru run "web-hunter/testing/challenge-verdicts/content-widget-under-article.yml" --env ascend-local
```

```bash
bru run "web-hunter/testing/challenge-verdicts/content-article-japanese.yml" --env ascend-local
```

```bash
bru run "web-hunter/testing/challenge-verdicts/content-article-arabic.yml" --env ascend-local
```

```bash
bru run "web-hunter/testing/challenge-verdicts/content-captcha-word-in-prose.yml" --env ascend-local
```

```bash
bru run "web-hunter/testing/challenge-verdicts/content-403-rich-body.yml" --env ascend-local
```

Metrics row, after all ten rows above.

```bash
bru run "web-hunter/testing/challenge-verdicts/metrics-challenge.yml" --env ascend-local
```

Capture the metrics output after the run for the growth comparison.

```bash
curl -fsS http://localhost:7021/metrics -o /tmp/challenge-verdicts-after.txt
```

Cleanup. Wait until every NoVNC flow the wall rows opened has drained.

**Unix:**

```bash
for i in $(seq 1 60); do if [ "$(curl -fsS http://localhost:7021/api/v2/session/interventions | python3 -c 'import json,sys; print(json.load(sys.stdin)["active_flows"])')" = "0" ]; then break; fi; sleep 10; done; curl -fsS http://localhost:7021/api/v2/session/interventions
```

**PowerShell:**

```powershell
for ($i = 0; $i -lt 60 -and ((Invoke-RestMethod http://localhost:7021/api/v2/session/interventions).active_flows) -ne 0; $i++) { Start-Sleep 10 }; Invoke-RestMethod http://localhost:7021/api/v2/session/interventions
```

Expect the final body to report `active_flows` `0`.

## Expected

- **`/wall-ko`:** HTTP 428. The problem body holds `code` `human_intervention_required`,
  `intervention_type` `captcha`, and a non-empty `vnc_url`.
- **`/wall-tr`:** HTTP 428. The problem body holds `code` `human_intervention_required`,
  `intervention_type` `login`, and a non-empty `vnc_url`.
- **`/wall-vendor-thin`:** HTTP 428. The problem body holds `code`
  `human_intervention_required` and a non-empty `vnc_url`.
- **`/wall-header`:** HTTP 428. The problem body holds `code` `human_intervention_required`
  and a non-empty `vnc_url`.
- **`/wall-oversized`:** HTTP 428. The problem body holds `code`
  `human_intervention_required` and a non-empty `vnc_url`.
- **`/captcha-wall`:** HTTP 200. The body holds `status` `success` and the canary sentence
  `"The QUARRY-THRUSH survey logged 47 nesting pairs along the basalt cliffs of Lake Mirell on June 9th."`.
- **`/article-ja`:** HTTP 200. The body holds `status` `success` and the canary sentence
  `"QUARRY-THRUSHの調査で47組の営巣を確認した。"`.
- **`/article-ar`:** HTTP 200. The body holds `status` `success` and the canary sentence
  `"سجل مسح QUARRY-THRUSH 47 زوجا معششا."`.
- **`/prose-captcha`:** HTTP 200. The body holds `status` `success`.
- **`/rich-403`:** any HTTP answer but 428. A 428 is a FAIL.
- **Metrics:** `challenge_verdicts_total` with `verdict="wall"` is exactly 5 higher in the
  after-output than in the baseline, and with `verdict="content"` is at least 4 higher:

  ```bash
  grep 'challenge_verdicts_total{[^}]*verdict="wall"' /tmp/challenge-verdicts-before.txt /tmp/challenge-verdicts-after.txt
  ```

  ```bash
  grep 'challenge_verdicts_total{[^}]*verdict="content"' /tmp/challenge-verdicts-before.txt /tmp/challenge-verdicts-after.txt
  ```

  Every `vendor` label value on the `challenge_signals_fired_total` lines of the after-output
  is a catalogue vendor name or `none`:

  ```bash
  grep -o 'challenge_signals_fired_total{[^}]*}' /tmp/challenge-verdicts-after.txt | grep -o 'vendor="[^"]*"' | sort -u
  ```

- **Cleanup:** the final `GET /api/v2/session/interventions` body reports `active_flows` `0`.

Every assertion above is an HTTP status, a response body, or `/metrics`.

## Fixtures

None checked in. The fake site pages `/wall-ko`, `/wall-tr`, `/wall-vendor-thin`, `/wall-header`,
`/wall-oversized`, `/captcha-wall`, `/article-ja`, `/article-ar`, `/prose-captcha` and `/rich-403`
carry the canaries, all indexed in [fixtures/README.md](../fixtures/README.md).
