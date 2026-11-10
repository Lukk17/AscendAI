# Challenge verdicts on the fake site: run tasks template

Spec: [../19-challenge-verdicts-test.md](../19-challenge-verdicts-test.md)

Copy this file to `../runs/<UTC-timestamp>_19-challenge-verdicts-tasks.md` before starting a run. For a repeated run of the same spec in the same sweep, which shares the sweep's timestamp, add `-rerun<N>` before `.md` (`-rerun2` for the second run, `-rerun3` for the third). Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [ ] Bruno CLI present (`bru --version` returns a version)
- [ ] ascend-web-hunter `/health` returns HTTP 200 with `status` `ok`, `service` `ascend-web-hunter` and a non-empty `version`
- [ ] Fake site reachable: `curl -fsS http://127.0.0.1:7031/__requests` returns a request list
- [ ] `GET /api/v2/session/interventions` reports `active_flows` `0` before starting

### Reset state

- [ ] `POST /api/v2/web/session/clear` for `http://e2e-fake-site:7031/` returned HTTP 200 `status` `"cleared"` (read cache emptied)
- [ ] `DEL "tier_memory:e2e-fake-site" "novnc_window_result:e2e-fake-site:default"` run once (`0`, `1` or `2`), with the flow registry already drained (see Prerequisites)

### Run

- [ ] From the repository root, `cd docs/api/request/AscendAI`.
- [ ] Step 0 - created the private report directory `E2E_OUT` (`mktemp -d`, or a random folder under the temp path in PowerShell), no fixed `/tmp` path.
- [ ] Step 0 - captured the metrics baseline to `challenge-verdicts-before.txt` in `E2E_OUT`.
- [ ] Wall row - sent `challenge-verdicts/wall-own-captcha-korean.yml`, got HTTP 428.
- [ ] Closed the row's window with `DELETE /api/v2/session/interventions/{flow_id}` (one line `204 <flow_id>`), then drained - polled `GET /api/v2/session/interventions` until `active_flows` `0` before the next wall row (repair 2026-10-26: same-domain flows join, so wall-tr must not read while wall-ko's flow lives).
- [ ] Wall row - sent `challenge-verdicts/wall-login-turkish.yml`, got HTTP 428.
- [ ] Closed the row's window with `DELETE /api/v2/session/interventions/{flow_id}` (one line `204 <flow_id>`), then drained until `active_flows` `0` before the next wall row (same repair).
- [ ] Wall row - sent `challenge-verdicts/wall-vendor-script-thin.yml`, got HTTP 428.
- [ ] Closed the row's window with `DELETE /api/v2/session/interventions/{flow_id}` (one line `204 <flow_id>`), then drained until `active_flows` `0` before the next wall row (same repair).
- [ ] Wall row - sent `challenge-verdicts/wall-definitive-header.yml`, got HTTP 428.
- [ ] Closed the row's window with `DELETE /api/v2/session/interventions/{flow_id}` (one line `204 <flow_id>`), then drained until `active_flows` `0` before the next wall row (same repair).
- [ ] Wall row - sent `challenge-verdicts/wall-oversized.yml`, got HTTP 428.
- [ ] Closed the last wall row's window with `DELETE /api/v2/session/interventions/{flow_id}` (one line `204 <flow_id>`), then drained until `active_flows` `0` before the content rows.
- [ ] Content row - sent `challenge-verdicts/content-widget-under-article.yml`, got HTTP 200.
- [ ] Content row - sent `challenge-verdicts/content-article-japanese.yml`, got HTTP 200.
- [ ] Content row - sent `challenge-verdicts/content-article-arabic.yml`, got HTTP 200.
- [ ] Content row - sent `challenge-verdicts/content-captcha-word-in-prose.yml`, got HTTP 200.
- [ ] Content row - sent `challenge-verdicts/content-403-rich-body.yml`, got a non-428 answer.
- [ ] Metrics row - sent `challenge-verdicts/metrics-challenge.yml`.
- [ ] Captured the after-run metrics to `challenge-verdicts-after.txt` in `E2E_OUT`.
- [ ] Cleanup - closed any window still open for `e2e-fake-site:default` (no line, or `204 <flow_id>` per window), then polled `GET /api/v2/session/interventions` until `active_flows` `0`.

### Expected

- [ ] `/wall-ko` body: `code` `human_intervention_required`, `intervention_type` `captcha`, non-empty `vnc_url`.
- [ ] `/wall-tr` body: `code` `human_intervention_required`, `intervention_type` `login`, non-empty `vnc_url`.
- [ ] `/wall-vendor-thin` body: `code` `human_intervention_required`, non-empty `vnc_url`.
- [ ] `/wall-header` body: `code` `human_intervention_required`, non-empty `vnc_url`.
- [ ] `/wall-oversized` body: `code` `human_intervention_required`, non-empty `vnc_url`.
- [ ] `/captcha-wall` body: `status` `success` with the QUARRY-THRUSH field-notes canary.
- [ ] `/article-ja` body: `status` `success` with its Japanese canary.
- [ ] `/article-ar` body: `status` `success` with its Arabic canary.
- [ ] `/prose-captcha` body: `status` `success`.
- [ ] `/rich-403`: answer was not HTTP 428.
- [ ] `/metrics`: `challenge_verdicts_total{verdict="wall"}`, summed over every `tier` label, grew by at least 5 (each read tier records once per page, the crawlee tier included, which judges a 403, 429 or 503 page once, and a closed window records its last check once under `novnc-monitor`, so one wall page can add more than one). The `tier` label `curl_cffi` counts both static tiers (`1-beautifulsoup` and `2-trafilatura`), so a read through both adds 2 under it, not 1. `{verdict="content"}`, summed the same way, grew by at least 8 (each of the four gated content reads counts once under its serving tier and once under `reader`, the second look).
- [ ] `/metrics`: `challenge_verdicts_total{verdict="content",tier="novnc-monitor"}` did not grow (the window judges its last check with the main frame response headers, so `/wall-header` ends as a wall).
- [ ] `/metrics`: every `vendor` label value of `challenge_signals_fired_total` is a catalogue vendor name or `none`.
- [ ] Cleanup body: `active_flows` `0`.
- [ ] Every assertion checked was an HTTP status, a response body, or `/metrics`.

### Post-run cleanup

- [ ] After the Expected checks, removed the `E2E_OUT` report directory with both metrics files

### Verdict

- [ ] Verdict: PASS / FAIL (delete the wrong one)

## Result summary

Input tokens:

Output tokens:

Start (UTC):

End (UTC):

Duration:

---

## Additional tasks I did

<!-- Optional. List anything outside the spec, e.g. diagnostic curls, manual log inspection, retries with different inputs. Leave empty if nothing extra. -->
