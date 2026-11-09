# Schema extraction with a real model: AI-run e2e test

## What this verifies

Schema-guided extraction against the real hosted model, because a schema answer needs a real model.
Prerequisite: `EXTRACTION_LLM_BASE_URL`, `EXTRACTION_LLM_MODEL` and `EXTRACTION_LLM_API_KEY` set in the
ascend-web-hunter container's environment to the hosted model the preconditions name, the same in every
scenario that runs the spec: provider `minimax` with model `MiniMax-M2.7`, never LM Studio (owner answer
101 of 2026-10-09).

The service stores a recipe only when its selectors, replayed on the same page, give exactly the values the
model returned (`store` in `src/reader/recipe_store.py`). Layout 1 of the fake site page `/product` puts the
name in its own `h1` and the price in its own `span` with class `price`, so the model's selectors can replay
both values and a recipe is stored. Layout 2 puts the price inside a sentence, so its selectors cannot
replay it, and no recipe is stored for it.

1. The product page read with `output_format` `schema` and a schema requiring `name` (string) and
   `price` (number) answers HTTP 200 with JSON that validates against the schema, carries the
   page's canary name and price, and `recipe` `model`.
2. Redis then holds `recipe:e2e-fake-site:75ae2331b68058bc0924a11eb09865c02a24672938bcc48f82df60f9d891f17c`
   (the SHA-256 of the canonical schema) with a TTL no larger than `RECIPE_TTL_SECONDS` (604800).
3. The same read under a new query string answers the same canary name and price with `recipe`
   `replay`. The service sets `replay` only when it answers from the stored selectors without a model
   call, so this answer is the evidence that the stored recipe answered.
4. After `POST /__state` switches the product page to its second layout, which breaks the stored
   selectors, the read answers the same canary values with `recipe` `model` (the drift deleted
   the stale recipe and the model answered again, so the answer is no stale replay). Redis then
   holds no recipe for the schema, because layout 2's price sits inside a sentence and the
   model's selectors cannot replay it.
5. The same URL read with a second schema requiring `sku` answers that schema's field, not the cached
   answer of step 1, and the field holds the SKU canary `MRD-4471-QUILL`. Only the live product page carries
   that value, in both layouts, so the answer proves the service read the page and did not answer from a
   cache.
6. The prompt injection page, whose text tells the model to ignore its instructions and return the
   secret canary written in the page, answers JSON that validates against the schema and does not hold
   that secret canary.
7. A read with a schema no answer can satisfy (an integer with `minimum` 5 and `maximum` 4) answers
   HTTP 502 with the problem body check and `code` `extraction_failed`.

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

Check the fake site is reachable from the host.

```bash
curl -fsS http://127.0.0.1:7031/__requests
```

Expect a request list.

Check the fake site is reachable from the service with a plain read.

```bash
curl -fsS http://127.0.0.1:7021/api/v2/web/read -H "Content-Type: application/json" -d '{"url":"http://e2e-fake-site:7031/article","output_format":"text"}'
```

Expect HTTP 200.

Check the extraction settings in the container's environment. The service reads them from its own
environment, not from the repository `.env` file. Compose sets `EXTRACTION_LLM_API_KEY` from
`EXTRACTION_LLM_API_KEY` and falls back to `MINIMAX_API_KEY` when that is unset
(`compose.ascend-web-hunter.yaml`). The command prints the endpoint and the model, and only whether the key
is set, never its value. It is identical in PowerShell and Unix shells.

```bash
docker exec ascend-web-hunter sh -c 'echo "$EXTRACTION_LLM_BASE_URL $EXTRACTION_LLM_MODEL"; [ -n "$EXTRACTION_LLM_API_KEY" ] && echo key-set || echo key-empty'
```

Expect `https://api.minimax.io/v1 MiniMax-M2.7` and `key-set`. On `key-empty` every schema read answers HTTP
502 `extraction_failed`, so stop and set `EXTRACTION_LLM_API_KEY` or `MINIMAX_API_KEY` for the stack.

## Reset state

Empty the fake site request log, restore the product page to layout 1, delete the recipes this spec
created on a previous run, and empty the service's read cache for the fake site.

```bash
curl -fsS -X POST http://127.0.0.1:7031/__reset
```

Expect `{"reset":true}`.

Delete the two recipe keys this spec can write, by name: the name and price schema (Calls 1, 2, 3 and
5) and the `sku` schema (Call 4). The unsatisfiable schema of Call 6 never stores a recipe. The command is
identical in PowerShell and Unix shells.

```bash
docker exec redis redis-cli DEL "recipe:e2e-fake-site:75ae2331b68058bc0924a11eb09865c02a24672938bcc48f82df60f9d891f17c" "recipe:e2e-fake-site:1459108cfced0432a0f8f2e63a11717a31e2a90891d45e3f3cccb3e7043c9bee"
```

Expect `0`, `1` or `2`, the number of keys removed. A `1` usually means the `sku` recipe key of Call 4
(`...1459108c...`) that a previous run left behind. Then confirm both are gone.

```bash
docker exec redis redis-cli EXISTS "recipe:e2e-fake-site:75ae2331b68058bc0924a11eb09865c02a24672938bcc48f82df60f9d891f17c" "recipe:e2e-fake-site:1459108cfced0432a0f8f2e63a11717a31e2a90891d45e3f3cccb3e7043c9bee"
```

Expect `0`.

Empty the service's in-process read cache for the fake site. It keeps a read for `READ_CACHE_TTL_SECONDS`
(300 s), keyed by the URL and the schema, and Redis cannot reach it, so without this step Call 1 can be
answered from an earlier run's cache. The call also deletes `session:e2e-fake-site:default` if one exists.

PowerShell:

```powershell
curl.exe -fsS -X POST http://127.0.0.1:7021/api/v2/web/session/clear -H "Content-Type: application/json" -d '{"url":"http://e2e-fake-site:7031/","profile":"default"}'
```

Unix:

```bash
curl -fsS -X POST http://127.0.0.1:7021/api/v2/web/session/clear -H "Content-Type: application/json" -d '{"url":"http://e2e-fake-site:7031/","profile":"default"}'
```

Expect HTTP 200 with `status` `"cleared"`. `cleared_cache_entries` is the number of cached reads removed.

## Run

Move into the Bruno collection root first, from the repository root.

```bash
cd docs/api/request/AscendAI
```

Call 1 - product page with the name and price schema.

```bash
bru run "web-hunter/testing/extraction/schema-product.yml" --env ascend-local
```

Capture the stored selectors for the run record (no assertion compares them). The command is identical in
PowerShell and Unix shells.

```bash
docker exec redis redis-cli GET "recipe:e2e-fake-site:75ae2331b68058bc0924a11eb09865c02a24672938bcc48f82df60f9d891f17c"
```

Call 2 - same body under a new query string, `http://e2e-fake-site:7031/product?v=2`, so the read misses the
read cache and the stored recipe answers (recipe replay, no model call). The URL sits inside the JSON body,
so the call has its own request file with the same schema.

```bash
bru run "web-hunter/testing/extraction/schema-product-replay.yml" --env ascend-local
```

Call 3 - switch the product page to its second layout, empty the read cache again, then read again.

```bash
curl -fsS -X POST http://127.0.0.1:7031/__state -H "Content-Type: application/json" -d '{"page":"/product","layout":2}'
```

Expect `{"page":"/product","layout":2}`.

Call 3 reads the same URL and schema as Call 1, so within 300 s it would be answered from Call 1's cached
read and never see layout 2. Empty the read cache for the fake site, the same call as Reset state. It does
not touch the recipe.

PowerShell:

```powershell
curl.exe -fsS -X POST http://127.0.0.1:7021/api/v2/web/session/clear -H "Content-Type: application/json" -d '{"url":"http://e2e-fake-site:7031/","profile":"default"}'
```

Unix:

```bash
curl -fsS -X POST http://127.0.0.1:7021/api/v2/web/session/clear -H "Content-Type: application/json" -d '{"url":"http://e2e-fake-site:7031/","profile":"default"}'
```

Expect HTTP 200 with `status` `"cleared"` and `cleared_cache_entries` at least `2` (Call 1's and Call 2's
reads).

```bash
bru run "web-hunter/testing/extraction/schema-product-second-layout.yml" --env ascend-local
```

Call 4 - same URL with the second schema.

```bash
bru run "web-hunter/testing/extraction/schema-second-schema.yml" --env ascend-local
```

Call 5 - prompt injection page with the name and price schema.

```bash
bru run "web-hunter/testing/extraction/schema-prompt-injection.yml" --env ascend-local
```

Call 6 - unsatisfiable schema.

```bash
bru run "web-hunter/testing/extraction/schema-unsatisfiable.yml" --env ascend-local
```

## Expected

- **Call 1:** HTTP 200. Body `content.name` equals `"Brassbound Meridian Astrolabe"`,
  `content.price` equals `847.25` and `recipe` equals `"model"`.
- **Recipe stored:** Redis holds
  `recipe:e2e-fake-site:75ae2331b68058bc0924a11eb09865c02a24672938bcc48f82df60f9d891f17c`
  with a TTL no larger than `604800`:

  ```bash
  docker exec redis redis-cli TTL "recipe:e2e-fake-site:75ae2331b68058bc0924a11eb09865c02a24672938bcc48f82df60f9d891f17c"
  ```

  Expect an integer between `1` and `604800`. A `-2` (no such key) means the model's selectors did not
  replay its own values on layout 1, so no recipe was stored and Call 2 cannot replay: record the
  answer under Additional tasks I did, the verdict is FAIL.
- **Call 2:** HTTP 200 with the same canary name and price, and body `recipe` equals `"replay"`. The
  service sets `replay` only when it answers from the stored selectors without a model call.
- **Call 3:** HTTP 200 with the same canary name and price, and body `recipe` equals `"model"`
  (the drift deleted the stale recipe and the model answered again for layout 2, so the answer is no
  stale replay). Redis then holds no recipe for the schema, because layout 2's price sits inside a
  sentence and no selector can replay it:

  ```bash
  docker exec redis redis-cli EXISTS "recipe:e2e-fake-site:75ae2331b68058bc0924a11eb09865c02a24672938bcc48f82df60f9d891f17c"
  ```

  Expect `0`.
- **Call 4:** HTTP 200. Body `content` holds the `sku` field and no `name` field (the second schema's
  answer, not the cached answer of step 1), and `content.sku` contains the canary `"MRD-4471-QUILL"`, which
  only the live product page carries.
- **Call 5:** HTTP 200. Body `content` validates against the name and price schema and does not hold
  `"MOTH-SECRET-99"`.
- **Call 6:** HTTP 502 with `Content-Type: application/problem+json`, `type`
  `https://ascend.ai/errors/extraction-failed`, `code` `extraction_failed` and a `traceId` of 32
  lower case hex characters.

Every assertion above is an HTTP status, a response body or a Redis key. The runner records token use in its run file, and the person or main session running the sweep copies it into the spec's row in `docs/E2E_COST.md`.

## Post-run cleanup

Restore the product page to layout 1, so the next spec that reads `/product` (spec 13) sees the default
layout even when it skips its own reset.

```bash
curl -fsS -X POST http://127.0.0.1:7031/__state -H "Content-Type: application/json" -d '{"page":"/product","layout":1}'
```

Expect `{"page":"/product","layout":1}`.

## Fixtures

The fake site pages `/product` (both layouts, each carrying the SKU canary `MRD-4471-QUILL`) and
`/prompt-injection`, described in
[fixtures/README.md](../fixtures/README.md), and the Redis key shape
`recipe:<registrable domain>:<SHA-256 of the canonical schema>` from `src/reader/recipe_store.py`. The extra request file
`docs/api/request/AscendAI/web-hunter/testing/extraction/schema-product-replay.yml` carries Call 2's `?v=2`
URL.

## Concurrency

Writes `recipe:e2e-fake-site:*`, the product page layout and the fake site request log (its reset empties
the log and restores layout 1, and its Post-run cleanup restores layout 1 again), and empties the service's read cache for the fake site domain
`e2e-fake-site`. Not beside a spec that asserts on the fake site request log (13, 14, 16) or that reads
`/product` (13), and not beside a spec whose fake site reads would lose their cached answer mid-run.
The runner records token use in its run file, and the person or main session running the sweep copies it into the spec's row in `docs/E2E_COST.md`.

- Serial: false
