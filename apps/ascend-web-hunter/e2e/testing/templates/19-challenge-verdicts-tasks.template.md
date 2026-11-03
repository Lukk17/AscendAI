# Challenge verdicts on the fake site: run tasks template

Spec: [../19-challenge-verdicts-test.md](../19-challenge-verdicts-test.md)

Copy this file to `../runs/<UTC-timestamp>_19-challenge-verdicts-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [ ] Bruno CLI present (`bru --version` returns a version)
- [ ] ascend-web-hunter `/health` returns HTTP 200 with `status` `ok`, `service` `ascend-web-hunter` and a non-empty `version`
- [ ] Fake site reachable: `curl -fsS http://127.0.0.1:7031/__requests` returns a request list
- [ ] `GET /api/v2/session/interventions` reports `active_flows` `0` before starting

### Reset state

- [ ] No reset needed: reads are stateless and the flow registry is already drained (see Prerequisites)

### Run

- [ ] `cd docs/api/request/AscendAI`.
- [ ] Step 0 - captured the metrics baseline to `/tmp/challenge-verdicts-before.txt`.
- [ ] Wall row - sent `challenge-verdicts/wall-own-captcha-korean.yml`, got HTTP 428.
- [ ] Drained - polled `GET /api/v2/session/interventions` until `active_flows` `0` before the next wall row (repair 2026-10-26: same-domain flows join, so wall-tr must not read while wall-ko's flow lives).
- [ ] Wall row - sent `challenge-verdicts/wall-login-turkish.yml`, got HTTP 428.
- [ ] Drained - polled `GET /api/v2/session/interventions` until `active_flows` `0` before the next wall row (same repair).
- [ ] Wall row - sent `challenge-verdicts/wall-vendor-script-thin.yml`, got HTTP 428.
- [ ] Drained - polled `GET /api/v2/session/interventions` until `active_flows` `0` before the next wall row (same repair).
- [ ] Wall row - sent `challenge-verdicts/wall-definitive-header.yml`, got HTTP 428.
- [ ] Drained - polled `GET /api/v2/session/interventions` until `active_flows` `0` before the next wall row (same repair).
- [ ] Wall row - sent `challenge-verdicts/wall-oversized.yml`, got HTTP 428.
- [ ] Content row - sent `challenge-verdicts/content-widget-under-article.yml`, got HTTP 200.
- [ ] Content row - sent `challenge-verdicts/content-article-japanese.yml`, got HTTP 200.
- [ ] Content row - sent `challenge-verdicts/content-article-arabic.yml`, got HTTP 200.
- [ ] Content row - sent `challenge-verdicts/content-captcha-word-in-prose.yml`, got HTTP 200.
- [ ] Content row - sent `challenge-verdicts/content-403-rich-body.yml`, got a non-428 answer.
- [ ] Metrics row - sent `challenge-verdicts/metrics-challenge.yml`.
- [ ] Captured the after-run metrics to `/tmp/challenge-verdicts-after.txt`.
- [ ] Cleanup - polled `GET /api/v2/session/interventions` until `active_flows` `0`.

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
- [ ] `/metrics`: `challenge_verdicts_total{verdict="wall"}` grew by exactly 5; `{verdict="content"}` grew by at least 4.
- [ ] `/metrics`: every `vendor` label value of `challenge_signals_fired_total` is a catalogue vendor name or `none`.
- [ ] Cleanup body: `active_flows` `0`.
- [ ] Every assertion checked was an HTTP status, a response body, or `/metrics`.

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
