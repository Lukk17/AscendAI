# Schema extraction with a real model: run tasks template

Spec: [../15-schema-extraction-ai-test.md](../15-schema-extraction-ai-test.md)

Copy this file to `../runs/<UTC-timestamp>_15-schema-extraction-ai-tasks.md` before starting a run. For a repeated run of the same spec in the same sweep, which shares the sweep's timestamp, add `-rerun<N>` before `.md` (`-rerun2` for the second run, `-rerun3` for the third). Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [ ] Bruno CLI present (`bru --version` returns a version)
- [ ] ascend-web-hunter `/health` returns HTTP 200 with `status` `ok`, `service` `ascend-web-hunter` and a non-empty `version`
- [ ] Fake site reachable: `curl -fsS http://127.0.0.1:7031/__requests` returns a request list
- [ ] Plain read of `http://e2e-fake-site:7031/article` through the service returned HTTP 200
- [ ] The ascend-web-hunter container's environment (not `.env`) holds `EXTRACTION_LLM_BASE_URL`
      `https://api.minimax.io/v1`, `EXTRACTION_LLM_MODEL` `MiniMax-M2.7` and a set `EXTRACTION_LLM_API_KEY`
      (compose falls back to `MINIMAX_API_KEY`), checked with the `docker exec` command that prints `key-set`

### Reset state

- [ ] `POST http://127.0.0.1:7031/__reset` returned `{"reset":true}`
- [ ] Deleted the two recipe keys (`...75ae2331...` and `...1459108c...`) with one `DEL` naming both (reply `0`, `1` or `2`, a `1` usually being the `sku` key a previous run left behind), `EXISTS` returns `0`
- [ ] `POST /api/v2/web/session/clear` for `http://e2e-fake-site:7031/` returned HTTP 200 `status` `"cleared"` (read cache emptied)

### Run

- [ ] Moved into `docs/api/request/AscendAI` from the repository root
- [ ] Sent `schema-product.yml` via `bru run` and got HTTP 200
- [ ] Recorded the stored selectors from the recipe key
- [ ] Sent `schema-product-replay.yml` (same body, URL `http://e2e-fake-site:7031/product?v=2`) via `bru run` and got HTTP 200
- [ ] Switched `/product` to layout 2 via `POST /__state`
- [ ] Emptied the read cache again with `POST /api/v2/web/session/clear` for `http://e2e-fake-site:7031/` (`cleared_cache_entries` at least `2`)
- [ ] Sent `schema-product-second-layout.yml` via `bru run` and got HTTP 200
- [ ] Sent `schema-second-schema.yml` via `bru run` and got HTTP 200
- [ ] Sent `schema-prompt-injection.yml` via `bru run` and got HTTP 200
- [ ] Sent `schema-unsatisfiable.yml` via `bru run` and got HTTP 502

### Expected

- [ ] Call 1 body: `content.name` is the canary name, `content.price` is the canary price, `recipe` is `model`
- [ ] Recipe key exists with TTL between `1` and `604800`
- [ ] Call 2 body: same canary name and price with `recipe` `replay` (the service sets `replay` only when it answers from the stored selectors without a model call)
- [ ] Call 3 body: same canary name and price with `recipe` `model` (the drift deleted the stale recipe and the model answered again, no stale replay)
- [ ] After Call 3, `EXISTS` on the name and price recipe key returns `0` (layout 2's price sits inside a sentence, so no recipe is stored for it)
- [ ] Call 4 body: `content` holds `sku` and no `name`, and `content.sku` contains the canary `MRD-4471-QUILL` (only the live product page carries it)
- [ ] Call 5 body validates and does not hold `"MOTH-SECRET-99"`
- [ ] Call 6: HTTP 502 with `Content-Type: application/problem+json`, body `type` `https://ascend.ai/errors/extraction-failed`, `code` `extraction_failed` and a `traceId` of 32 lower case hex characters
- [ ] Token use recorded below in this run file (the person or main session running the sweep copies it into the spec's `docs/E2E_COST.md` row, the runner writes only this run file)

### Post-run cleanup

- [ ] `POST http://127.0.0.1:7031/__state` with `{"page":"/product","layout":1}` returned `{"page":"/product","layout":1}`

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
