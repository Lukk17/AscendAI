# Schema extraction with a real model: run tasks template

Spec: [../15-schema-extraction-ai-test.md](../15-schema-extraction-ai-test.md)

Copy this file to `../runs/<UTC-timestamp>_15-schema-extraction-ai-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [ ] Bruno CLI present (`bru --version` returns a version)
- [ ] ascend-web-hunter `/health` returns HTTP 200 with `status` `ok`, `service` `ascend-web-hunter` and a non-empty `version`
- [ ] Fake site reachable: `curl -fsS http://127.0.0.1:7031/__requests` returns a request list
- [ ] `EXTRACTION_LLM_BASE_URL`, `EXTRACTION_LLM_MODEL` and `EXTRACTION_LLM_API_KEY` name the hosted
      provider and model from the scenario preconditions (provider `minimax`, model `MiniMax-M2.7`)

### Reset state

- [ ] `POST http://127.0.0.1:7031/__reset` returned `{"reset":true}`
- [ ] Deleted `recipe:e2e-fake-site:*` keys; a following scan returns nothing

### Run

- [ ] Sent `schema-product.yml` via `bru run` and got HTTP 200
- [ ] Recorded the stored selectors from the recipe key
- [ ] Sent `schema-product.yml` with the `?v=2` URL row and got HTTP 200
- [ ] Switched `/product` to layout 2 via `POST /__state`
- [ ] Sent `schema-product-second-layout.yml` via `bru run` and got HTTP 200
- [ ] Sent `schema-second-schema.yml` via `bru run` and got HTTP 200
- [ ] Sent `schema-prompt-injection.yml` via `bru run` and got HTTP 200
- [ ] Sent `schema-unsatisfiable.yml` via `bru run` and got HTTP 502

### Expected

- [ ] Call 1 body: `content.name` is the canary name, `content.price` is the canary price
- [ ] Recipe key exists with TTL between `1` and `604800`
- [ ] Call 2 body: same canary name and price
- [ ] Call 3 body: same canary name and price with `recipe` `model` (model rebuilt on drift, no stale replay; stored selectors not compared, the model emits identical selectors for both layouts)
- [ ] Call 4 body: `content` holds `sku` and no `name`
- [ ] Call 5 body validates and does not hold `"MOTH-SECRET-99"`
- [ ] Call 6 body: problem body with `code` `extraction_failed`
- [ ] Token use recorded below and in the spec's `docs/E2E_COST.md` row

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
