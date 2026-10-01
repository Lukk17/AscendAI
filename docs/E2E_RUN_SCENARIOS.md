# End-to-end run scenarios

As of 2026-09-10, commit e887414. Defines the six run pipelines the repository owner uses to exercise the e2e
suites, so an agent asked to "run the e2e tests" has a fixed menu to choose from instead of guessing a shape. The
suite READMEs own spec content, fixtures, and each suite's own parallel groups: [apps/ascend-agent/e2e/README.md](../apps/ascend-agent/e2e/README.md),
[apps/ascend-audio-scribe/e2e/README.md](../apps/ascend-audio-scribe/e2e/README.md),
[apps/ascend-memory/e2e/README.md](../apps/ascend-memory/e2e/README.md),
[apps/ascend-ocr/e2e/README.md](../apps/ascend-ocr/e2e/README.md),
[apps/ascend-weather-mcp/e2e/README.md](../apps/ascend-weather-mcp/e2e/README.md),
[apps/ascend-web-hunter/e2e/README.md](../apps/ascend-web-hunter/e2e/README.md). This document owns which
scenario to pick, which specs that scenario runs or skips, and the cross-suite scheduling that only exists once
more than one suite's runners share a host.

It also defines one [service suite](#service-suites) per service: the way to run a single service's end-to-end specs alone, without running every other suite to test that one service.

The repository ships 61 specs total across the six suites (11 + 5 + 6 + 20 + 7 + 12). No single scenario below runs
all 61 with nobody at the keyboard, because one spec (`ascend-web-hunter` spec 11, `11-captcha-solve-and-capture`)
needs a human to solve an hCaptcha challenge through NoVNC. Scenarios 3 and 4 run every spec, and both need a human present for that one spec. No spec needs LM Studio: every enabled provider row in the Bruno requests the specs run selects a hosted provider. So Scenario 2 runs the same specs as Scenario 1, and Scenario 4 the same as Scenario 3. The LM Studio column records only whether LM Studio is running on the host during the sweep.

---

## How to ask

Before running any end-to-end test, ask which scenario or which service suite from this document the requester wants. Never assume one, even when the request sounds like "run the e2e tests" with no further detail, and even when the request names one service. The six scenarios run specs across every suite. A [service suite](#service-suites) runs one service's specs and nothing else. They differ in which compose project is up, whether LM Studio must answer, whether a human needs to be at the keyboard, and how many specs run, so picking wrong wastes a compose cycle at minimum and, for the human-gated choices, wastes a person's attention waiting for a step that choice never reaches.

---

## Scenario summary

| Scenario | Stack | LM Studio | Human at keyboard | Spec count |
| :------- | :---- | :-------- | :----------------- | :--------- |
| 1 | Full (`ascend-ai`, includes the scraping stack) | Off | No | 60 |
| 2 | Full (`ascend-ai`, includes the scraping stack) | On | No | 60 |
| 3 | Full (`ascend-ai`, includes the scraping stack) | Off | Yes | 61 |
| 4 | Full (`ascend-ai`, includes the scraping stack) | On | Yes | 61 |
| 5 | Scraping only (`ascend-scrapper`) | Not applicable | Yes | 12 |
| 6 | Scraping only (`ascend-scrapper`) | Not applicable | No | 11 |

---

## Compose projects and the shared container names

Both compose files declare the same four container names: `searxng`, `flaresolverr`, `ascend-web-hunter`, and
`ngrok-ascend-web-hunter`. [compose.yaml](../compose.yaml) (project `ascend-ai`) pulls in
[compose.ascend-web-hunter.yaml](../compose.ascend-web-hunter.yaml) via `include:`, so the full stack already
contains those four containers. Running the scraping file as its own project (`ascend-scrapper`) at the same time
fails on a name conflict, so only one of the two projects is ever up. Switching means `docker compose down` on the
project being left, not `stop`, because a stopped container still holds its name.

Bring the full stack up.

```bash
docker compose up -d --build
```

Take the full stack down.

```bash
docker compose down
```

Bring the scraping stack up alone.

```bash
docker compose -f compose.ascend-web-hunter.yaml up -d --build
```

Take the scraping stack down alone.

```bash
docker compose -f compose.ascend-web-hunter.yaml down
```

Running the scraping file alone on a host with no Redis of its own needs `COMPOSE_PROFILES=redis` and
`REDIS_URL=redis://redis:6379/0` in [.env](../.env.example), which starts the bundled `redis` service under
container name `ascend-scrapper-redis` (not `redis`, because the host's own external-prerequisite Redis container
already holds that name). Every `docker exec redis ...` command a web-hunter spec calls for targets
`ascend-scrapper-redis` in this mode, not the host's `redis` container.

---

## Scenario 1: Automated, full stack, LM Studio off

### Preconditions

- Compose: `ascend-ai` project up (full stack, scraping stack included). `ascend-scrapper` project not running
  standalone (it cannot be, its containers are already part of `ascend-ai`).
- Local-dev prerequisites: PostgreSQL `:5432` (database `ascend_ai`, user `postgres`, password `local`), Redis
  `:6379`, Qdrant `:6333`, and S3-compatible object storage (Floci) `:9070` / `:9071`, all up before `docker compose up`.
- LM Studio: off. No spec needs it. Memory specs 2, 3, 5, and 6 embed through the `openai` provider, which every insert and search request under [docs/api/request/AscendAI/memory/testing](api/request/AscendAI/memory/testing) pins, so `MEM0_DEFAULT_PROVIDER=lmstudio` never applies to them.
- Human at keyboard: not needed. `ascend-web-hunter` spec 11 (the only human-gated spec in the repository) does not
  run in this scenario.
- Credentials present in `.env`, read from the enabled rows of the Bruno requests the specs run: `OPENAI_API_KEY` (the `openai` embedding provider every agent prompt sends, the agent chat provider in specs 2 and 8, audio-scribe specs 2 and 5, memory specs 2, 3, 5, and 6), `MINIMAX_API_KEY` (the agent chat provider in specs 1, 3, 4, and 5), `ASCEND_ANTHROPIC_API_KEY` (the agent chat provider in specs 6, 7, 9, 10, and 11), `HF_TOKEN` (audio-scribe spec 3), `SEARXNG_SECRET` (mandatory, the scraping stack refuses to start without it), `NGROK_AUTHTOKEN` (the `ngrok-ascend-web-hunter` container needs it to run cleanly even though nobody opens the tunnel in this scenario). `GEMINI_API_KEY` is not exercised by any spec in this scenario.

### Spec list

| Suite | Specs run | Count |
| :---- | :-------- | :---- |
| ascend-agent | 1-11 | 11 |
| ascend-audio-scribe | 1-5 | 5 |
| ascend-memory | 1-6 | 6 |
| ascend-ocr | 1-20 | 20 |
| ascend-weather-mcp | 1-7 | 7 |
| ascend-web-hunter | 1-10, 12 | 11 |
| Total | | 60 |

### Skipped specs

- `ascend-web-hunter` 11: needs a human at NoVNC to solve an hCaptcha challenge.

### Run order

1. Every suite's spec 1 runs first (fail fast, cheapest setup), up to 5 runners at once across all suites.
2. Each suite then proceeds through its own README's parallel groups. The OCR engine-bound specs (2, 3, 4, 6, 13, 14,
   15, 16, 17, 18, 19) and the agent docling-bound specs (3, 5, 6, 7) each run alone whenever their turn comes: no other runner
   of any suite, anywhere on the host, may be active at the same time. Within OCR, specs 15 and 16 run after the
   shorter engine-bound specs because each replaces the worker, and the two long specs run last, spec 14 and then
   spec 13, because each reads the twenty five page document to the end. See
   [Global ordering rules](#global-ordering-rules) for the measured cost of breaking this rule.
3. Weather spec 7 runs last within the weather suite, because it restarts the `ascend-weather-mcp` container.
4. Memory runs its full chain, specs 1 through 6, in any order or in parallel, since all six specs use disjoint user ids per its own README.
5. Web-hunter's own chain: spec 1, then specs 2, 4, 5, 9 in parallel, then spec 6, then spec 12 (same site as spec
   6, and before spec 7 because spec 7's reset would wipe its capture), then spec 7 (fully automated, its
   `409 novnc_busy` rows retried per its own `Retry-After` rule), then spec 3, then spec 8, then spec 10 alone.
   Spec 11 does not run in this scenario.

---

## Scenario 2: Automated, full stack, LM Studio on

### Preconditions

Same as [Scenario 1](#scenario-1-automated-full-stack-lm-studio-off), except:

- LM Studio: on, answering at `:1234`. No spec needs it, so this scenario runs the same specs as Scenario 1.
- No new credential beyond Scenario 1's list. LM Studio uses the hardcoded local key `sk_local`
  ([compose.yaml](../compose.yaml)), not a `.env` entry.

### Spec list

| Suite | Specs run | Count |
| :---- | :-------- | :---- |
| ascend-agent | 1-11 | 11 |
| ascend-audio-scribe | 1-5 | 5 |
| ascend-memory | 1-6 | 6 |
| ascend-ocr | 1-20 | 20 |
| ascend-weather-mcp | 1-7 | 7 |
| ascend-web-hunter | 1-10, 12 | 11 |
| Total | | 60 |

### Skipped specs

- `ascend-web-hunter` 11: needs a human at NoVNC to solve an hCaptcha challenge.

### Run order

Same as [Scenario 1's run order](#run-order).

---

## Scenario 3: Human captcha, full stack, LM Studio off

### Preconditions

Same as [Scenario 1](#scenario-1-automated-full-stack-lm-studio-off), except:

- Human at keyboard: yes, for `ascend-web-hunter` spec 11.
- `VNC_PASSWORD` in `.env` is still optional in this dev stack (an unset value means the NoVNC desktop is
  passwordless and the container logs a warning at boot), but worth setting when a real person is going to open the
  tunnel.

### Spec list

| Suite | Specs run | Count |
| :---- | :-------- | :---- |
| ascend-agent | 1-11 | 11 |
| ascend-audio-scribe | 1-5 | 5 |
| ascend-memory | 1-6 | 6 |
| ascend-ocr | 1-20 | 20 |
| ascend-weather-mcp | 1-7 | 7 |
| ascend-web-hunter | 1-12 | 12 |
| Total | | 61 |

### Skipped specs

None. This scenario runs every spec the repository ships.

### Run order

Same as [Scenario 1's run order](#run-order) through web-hunter's spec 10, then one more step:

6. Spec 11 (`11-captcha-solve-and-capture`) runs last across the entire sweep, after every other suite and
   web-hunter's own specs 1 through 10 and 12 have finished. The runner posts the exact `vnc_url` string from spec
   11's Call 1 response into the chat verbatim, waits for the human to confirm they solved the hCaptcha challenge
   and submitted the form, and only then checks `session:democaptcha.com:default` in Redis for the `hmt_id` cookie
   (the capture check), which closes the spec. Reuse is proven by spec 12 earlier in the chain, with no human.

---

## Scenario 4: Human captcha, full stack, LM Studio on

### Preconditions

Same as [Scenario 2](#scenario-2-automated-full-stack-lm-studio-on), except:

- Human at keyboard: yes, for `ascend-web-hunter` spec 11.
- `VNC_PASSWORD` in `.env` is still optional in this dev stack, same note as Scenario 3.

### Spec list

| Suite | Specs run | Count |
| :---- | :-------- | :---- |
| ascend-agent | 1-11 | 11 |
| ascend-audio-scribe | 1-5 | 5 |
| ascend-memory | 1-6 | 6 |
| ascend-ocr | 1-20 | 20 |
| ascend-weather-mcp | 1-7 | 7 |
| ascend-web-hunter | 1-12 | 12 |
| Total | | 61 |

### Skipped specs

None. Like Scenario 3, this scenario runs every spec the repository ships.

### Run order

Same as [Scenario 2's run order](#run-order-1) through web-hunter's spec 10, then the same closing step as
[Scenario 3's step 6](#run-order-2): spec 11 last, human-gated, `vnc_url` pasted verbatim, human confirmation
before the capture check.

---

## Scenario 5: Human captcha, scraping compose only

### Preconditions

- Compose: `ascend-scrapper` project up alone (`docker compose -f compose.ascend-web-hunter.yaml up -d --build`).
  `ascend-ai` project down first, since both projects share the same four container names.
- Local-dev prerequisites: none of PostgreSQL or Qdrant are needed, since no suite in this scenario
  touches the agent, memory, OCR, audio, or weather containers. Redis is needed, but supplied by the bundled
  `redis` service (container name `ascend-scrapper-redis`), not the host's external-prerequisite Redis: set
  `COMPOSE_PROFILES=redis` and `REDIS_URL=redis://redis:6379/0` in `.env` when no host Redis runs.
- LM Studio: not applicable. `ascend-web-hunter` has no LM Studio dependency.
- Human at keyboard: yes, for spec 11.
- Credentials present in `.env`: `SEARXNG_SECRET` (mandatory), `NGROK_AUTHTOKEN` (needed for the human to reach
  NoVNC through the tunnel). `VNC_PASSWORD` is optional in this dev stack but worth setting before a human opens
  the tunnel, same as Scenario 3.
- Every `docker exec redis ...` command the web-hunter specs call for targets `ascend-scrapper-redis`, per
  [Compose projects and the shared container names](#compose-projects-and-the-shared-container-names).

### Spec list

| Suite | Specs run | Count |
| :---- | :-------- | :---- |
| ascend-web-hunter | 1-12 | 12 |
| Total | | 12 |

### Skipped specs

None. Only the web-hunter suite runs in this scenario, and it runs in full.

### Run order

Web-hunter's own chain, unmodified by any cross-suite constraint since no other suite is running: spec 1, then
specs 2, 4, 5, 9 in parallel, then spec 6, then spec 12 (same site as spec 6, and before spec 7 because spec 7's
reset would wipe its capture), then spec 7 (fully automated, its `409 novnc_busy` rows retried per its own
`Retry-After` rule), then spec 3, then spec 8, then spec 10 alone, then spec 11 (`11-captcha-solve-and-capture`)
last, human-gated. The runner posts the exact `vnc_url` string from spec 11's Call 1 response into the chat
verbatim, waits for the human to confirm they solved the hCaptcha challenge and submitted the form, and only then
checks `session:democaptcha.com:default` in Redis for the `hmt_id` cookie (the capture check), which closes the
spec.

---

## Scenario 6: Automated, scraping compose only

### Preconditions

Same as [Scenario 5](#scenario-5-human-captcha-scraping-compose-only), except:

- Human at keyboard: not needed. Spec 11 does not run in this scenario.
- `NGROK_AUTHTOKEN` is still needed for the `ngrok-ascend-web-hunter` container to run cleanly, even though nobody
  opens the tunnel.

### Spec list

| Suite | Specs run | Count |
| :---- | :-------- | :---- |
| ascend-web-hunter | 1-10, 12 | 11 |
| Total | | 11 |

### Skipped specs

- `ascend-web-hunter` 11: needs a human at NoVNC to solve an hCaptcha challenge.

### Run order

Web-hunter's own chain, same as [Scenario 5's run order](#run-order-4) through spec 10, with spec 12 in its place
after spec 6. Spec 11 does not run.

---

## Service suites

A service suite runs the end-to-end specs of one service and nothing else. Use one when the change under test touches a single service, since a scenario above runs every suite in the repository to reach the same specs. Each subsection below names what has to be up, the specs, the order, the resets and where the verdict lands. The suite README it links stays the owner of spec content, fixtures and the reasons behind each ordering rule.

Rules shared by every service suite:

- Only the one suite's runners are active on the host. The cross-suite rules in [Global ordering rules](#global-ordering-rules) do not come into play, except that an exclusive spec (the OCR engine-bound specs, the agent docling-bound specs) still runs with no other runner of any kind active.
- The default cap is 5 runners at once, per [.agents/skills/e2e-runbooks/SKILL.md](../.agents/skills/e2e-runbooks/SKILL.md).
- The Bruno CLI is installed (`bru --version` prints a version) and every run executes from [docs/api/request/AscendAI](api/request/AscendAI).
- Each spec run copies its tasks-template into the suite's `testing/runs/` folder and ends with a Verdict line of PASS or FAIL. Pass criteria are observable behaviour only (HTTP status, response body, persisted state), never log lines. The service suite passes when every spec it ran has a run record reading PASS.
- Starting one service from the main compose file brings up that service and whatever its `depends_on` names, nothing else. Where a suite needs more than that, its subsection says so.

### ascend-agent service suite

- Compose: the `ascend-ai` project up in full, as [apps/ascend-agent/e2e/README.md](../apps/ascend-agent/e2e/README.md) "Prerequisites before any test" requires. The specs reach `ascend-agent` on `:9917`, `ascend-memory` on `:7020`, `ascend-weather-mcp` on `:9998` (spec 1), `docling-serve` on `:5001` (specs 3, 5, 6, 7) and `unstructured-api` on `:9080` (spec 5).
- External prerequisites: PostgreSQL `:5432` (database `ascend_ai`), Redis `:6379`, Qdrant `:6333` and the object store `:9070`. Every spec resets and cleans rows in `postgres` and keys in `redis` through `docker exec`.
- LM Studio: not needed. Every `lmstudio` row in the Bruno requests under [docs/api/request/AscendAI/ascend-agent/testing](api/request/AscendAI/ascend-agent/testing) is disabled.
- Human at keyboard: not needed.
- Credentials in `.env`, read from the enabled rows of those Bruno requests: `OPENAI_API_KEY` (the `openai` embedding provider every prompt sends, plus the chat provider in specs 2 and 8), `MINIMAX_API_KEY` (chat provider in specs 1, 3, 4 and 5), `ASCEND_ANTHROPIC_API_KEY` (chat provider in specs 6, 7, 9, 10 and 11).

Bring the stack up.

```bash
docker compose up -d --build
```

| # | Spec |
| :- | :--- |
| 1 | [1-weather-mcp-test.md](../apps/ascend-agent/e2e/testing/1-weather-mcp-test.md) |
| 2 | [2-image-description-test.md](../apps/ascend-agent/e2e/testing/2-image-description-test.md) |
| 3 | [3-summarization-test.md](../apps/ascend-agent/e2e/testing/3-summarization-test.md) |
| 4 | [4-semantic-memory-test.md](../apps/ascend-agent/e2e/testing/4-semantic-memory-test.md) |
| 5 | [5-rag-test.md](../apps/ascend-agent/e2e/testing/5-rag-test.md) |
| 6 | [6-attach-sources-test.md](../apps/ascend-agent/e2e/testing/6-attach-sources-test.md) |
| 7 | [7-rag-dedup-test.md](../apps/ascend-agent/e2e/testing/7-rag-dedup-test.md) |
| 8 | [8-prompt-cache-openai-test.md](../apps/ascend-agent/e2e/testing/8-prompt-cache-openai-test.md) |
| 9 | [9-prompt-cache-anthropic-test.md](../apps/ascend-agent/e2e/testing/9-prompt-cache-anthropic-test.md) |
| 10 | [10-compaction-fires-test.md](../apps/ascend-agent/e2e/testing/10-compaction-fires-test.md) |
| 11 | [11-compaction-idempotency-test.md](../apps/ascend-agent/e2e/testing/11-compaction-idempotency-test.md) |

Run order, from the suite README's "Parallelism and execution order":

1. Specs 1, 2, 4 on one runner and specs 8, 9, 10, 11 on a second runner, both at once.
2. Once both runners have returned, spec 3 alone.
3. Then specs 5, 6, 7, in that order, each alone. The chain is strictly serial because all three share the `knowledge-base` bucket and the `ascendai-1536` collection, and all four of specs 3, 5, 6, 7 are docling-bound.

Resets: every spec carries its own Reset state and Post-run cleanup sections, scoped to its own `X-User-Id` and fixtures. Run both, the cleanup even after a FAIL. Allowlist the reset commands first when the runner is Claude Code's `e2e-runner`, per the suite README's "Claude Code permission allowlist".

### ascend-audio-scribe service suite

- Compose: the `ascend-ai` project with only `ascend-audio-scribe` up. Its compose service reserves an NVIDIA GPU device.
- External prerequisites: the object store `:9070` for spec 5 only, which uploads its fixture to the `e2e-fixtures` bucket. PostgreSQL, Redis and Qdrant are not used.
- LM Studio: not needed.
- Human at keyboard: not needed.
- Credentials in `.env`: `OPENAI_API_KEY` (specs 2 and 5), `HF_TOKEN` (spec 3). Specs 2, 3 and 5 also need outbound HTTPS to the provider.

Bring the service up.

```bash
docker compose up -d --build ascend-audio-scribe
```

| # | Spec |
| :- | :--- |
| 1 | [1-invalid-input-test.md](../apps/ascend-audio-scribe/e2e/testing/1-invalid-input-test.md) |
| 2 | [2-transcribe-openai-test.md](../apps/ascend-audio-scribe/e2e/testing/2-transcribe-openai-test.md) |
| 3 | [3-transcribe-hf-test.md](../apps/ascend-audio-scribe/e2e/testing/3-transcribe-hf-test.md) |
| 4 | [4-mcp-tools-list-test.md](../apps/ascend-audio-scribe/e2e/testing/4-mcp-tools-list-test.md) |
| 5 | [5-mcp-transcribe-test.md](../apps/ascend-audio-scribe/e2e/testing/5-mcp-transcribe-test.md) |

Run order, from [apps/ascend-audio-scribe/e2e/README.md](../apps/ascend-audio-scribe/e2e/README.md) "Parallelism and execution order":

1. Spec 1 first.
2. Specs 2 and 3, in parallel or one after the other (one after the other on a low rate-limit tier, since both spend paid quota).
3. Spec 4, then spec 5. Spec 4 must come before spec 5.

Resets: specs 2 and 3 delete the `/tmp/transcript_*.md` files inside the container in their own Reset state, and spec 5's Reset state seeds the `e2e-fixtures` bucket with its fixture. Specs 1 and 4 need none.

### ascend-memory service suite

- Compose: the `ascend-ai` project with only `ascend-memory` up.
- External prerequisites: Qdrant `:6333`. PostgreSQL, Redis and the object store are not used.
- LM Studio: not needed. Every insert and search request under [docs/api/request/AscendAI/memory/testing](api/request/AscendAI/memory/testing) pins `provider=openai`, so specs 2, 3, 5 and 6 embed through OpenAI. `MEM0_DEFAULT_PROVIDER=lmstudio` applies only when a caller omits `provider`.
- Human at keyboard: not needed.
- Credentials in `.env`: `OPENAI_API_KEY` (specs 2, 3, 5 and 6).

Bring the service up.

```bash
docker compose up -d --build ascend-memory
```

| # | Spec |
| :- | :--- |
| 1 | [1-invalid-input-test.md](../apps/ascend-memory/e2e/testing/1-invalid-input-test.md) |
| 2 | [2-insert-and-search-test.md](../apps/ascend-memory/e2e/testing/2-insert-and-search-test.md) |
| 3 | [3-wipe-user-scope-test.md](../apps/ascend-memory/e2e/testing/3-wipe-user-scope-test.md) |
| 4 | [4-mcp-tools-list-test.md](../apps/ascend-memory/e2e/testing/4-mcp-tools-list-test.md) |
| 5 | [5-mcp-insert-and-search-test.md](../apps/ascend-memory/e2e/testing/5-mcp-insert-and-search-test.md) |
| 6 | [6-user-isolation-test.md](../apps/ascend-memory/e2e/testing/6-user-isolation-test.md) |

Run order, from [apps/ascend-memory/e2e/README.md](../apps/ascend-memory/e2e/README.md) "Parallelism and execution order": spec 1 first, then specs 2 through 6 in any order or in parallel, since each owns disjoint user ids.

Resets: each writing spec wipes its own user ids in Reset state and again in Post-run cleanup through `POST /api/v1/memory/wipe`. Never wipe all users and never restart the container as a reset.

### ascend-ocr service suite

- Compose: the `ascend-ai` project with only `ascend-ocr` up.
- External prerequisites: the object store `:9070`, because every successful reading writes its Markdown to the `ocr-results` bucket and spec 6 fetches its fixture from the `e2e-fixtures` bucket. PostgreSQL, Redis and Qdrant are not used.
- Extra container: spec 11 starts its own throwaway `ascend-ocr-jail` container from the `ascend-ai-ascend-ocr:latest` image, outside compose, on `127.0.0.1:7023` with `MCP_FILE_URI_ROOT` set, and removes it before it returns. Port 7023 must be free.
- LM Studio: not needed.
- Human at keyboard: not needed.
- Credentials: none beyond the result store keys, which default to the local object store's own in [compose.yaml](../compose.yaml). No spec makes a paid call.
- Every other prerequisite, fixtures included, is in [apps/ascend-ocr/e2e/README.md](../apps/ascend-ocr/e2e/README.md) "Prerequisites before any test".

Bring the service up.

```bash
docker compose up -d --build ascend-ocr
```

| # | Spec | Class |
| :- | :--- | :--- |
| 1 | [1-invalid-input-test.md](../apps/ascend-ocr/e2e/testing/1-invalid-input-test.md) | Reject-fast |
| 2 | [2-ocr-english-test.md](../apps/ascend-ocr/e2e/testing/2-ocr-english-test.md) | Engine-bound |
| 3 | [3-ocr-polish-test.md](../apps/ascend-ocr/e2e/testing/3-ocr-polish-test.md) | Engine-bound |
| 4 | [4-ocr-default-language-test.md](../apps/ascend-ocr/e2e/testing/4-ocr-default-language-test.md) | Engine-bound |
| 5 | [5-mcp-tools-list-test.md](../apps/ascend-ocr/e2e/testing/5-mcp-tools-list-test.md) | Reject-fast |
| 6 | [6-mcp-ocr-test.md](../apps/ascend-ocr/e2e/testing/6-mcp-ocr-test.md) | Engine-bound |
| 7 | [7-ready-endpoint-test.md](../apps/ascend-ocr/e2e/testing/7-ready-endpoint-test.md) | Reject-fast |
| 8 | [8-mcp-ssrf-rejection-test.md](../apps/ascend-ocr/e2e/testing/8-mcp-ssrf-rejection-test.md) | Reject-fast |
| 9 | [9-mcp-bad-scheme-test.md](../apps/ascend-ocr/e2e/testing/9-mcp-bad-scheme-test.md) | Reject-fast |
| 10 | [10-mcp-credentials-rejection-test.md](../apps/ascend-ocr/e2e/testing/10-mcp-credentials-rejection-test.md) | Reject-fast |
| 11 | [11-mcp-file-uri-jail-test.md](../apps/ascend-ocr/e2e/testing/11-mcp-file-uri-jail-test.md) | Reject-fast |
| 12 | [12-ocr-unsupported-mime-test.md](../apps/ascend-ocr/e2e/testing/12-ocr-unsupported-mime-test.md) | Reject-fast |
| 13 | [13-long-document-test.md](../apps/ascend-ocr/e2e/testing/13-long-document-test.md) | Engine-bound |
| 14 | [14-job-listing-test.md](../apps/ascend-ocr/e2e/testing/14-job-listing-test.md) | Engine-bound |
| 15 | [15-cancel-running-job-test.md](../apps/ascend-ocr/e2e/testing/15-cancel-running-job-test.md) | Engine-bound |
| 16 | [16-queue-full-test.md](../apps/ascend-ocr/e2e/testing/16-queue-full-test.md) | Engine-bound |
| 17 | [17-ocr-rotated-photo-test.md](../apps/ascend-ocr/e2e/testing/17-ocr-rotated-photo-test.md) | Engine-bound |
| 18 | [18-ocr-straighten-crumpled-photo-test.md](../apps/ascend-ocr/e2e/testing/18-ocr-straighten-crumpled-photo-test.md) | Engine-bound |
| 19 | [19-ocr-crumpled-photo-default-test.md](../apps/ascend-ocr/e2e/testing/19-ocr-crumpled-photo-default-test.md) | Engine-bound |
| 20 | [20-mcp-unsupported-language-test.md](../apps/ascend-ocr/e2e/testing/20-mcp-unsupported-language-test.md) | Reject-fast |

Run order, from [apps/ascend-ocr/e2e/testing/README.md](../apps/ascend-ocr/e2e/testing/README.md) "Execution order":

1. The nine reject-fast specs, 1, 5, 7, 8, 9, 10, 11, 12, 20, in parallel up to the cap of 5, the rest queued. Specs 1, 9, 11, 12 and 20 assert an empty job listing, so start them with nothing queued or running.
2. Wait until every one of them has returned and spec 11's `ascend-ocr-jail` container is gone.
3. The eleven engine-bound specs one at a time, each alone with no other runner of any suite active anywhere on the host, not even a reject-fast spec of this suite: 2, 3, 4, 6, 17, 18, 19, then 15, then 16, then 14, then 13. Specs 15 and 16 each replace the worker. Specs 14 and 13 both read the twenty five page document to the end, the two longest specs in the suite, so they run last: 172.1 seconds of processing for that document on image `7605748a6afa` on 2026-09-25, and spec 14 reads two single pages after it.

Resets: run both commands in the suite README's [Resetting between runs](../apps/ascend-ocr/e2e/README.md#resetting-between-runs) before every engine-bound spec, and confirm both the job listing and the `ocr-results` bucket are empty. The reject-fast specs need no reset.

### ascend-weather-mcp service suite

- Compose: the `ascend-ai` project with only `ascend-weather-mcp` up.
- External prerequisites: none of PostgreSQL, Redis, Qdrant or the object store. Specs 2 through 7 need outbound HTTPS to `*.open-meteo.com`.
- LM Studio: not needed.
- Human at keyboard: not needed.
- Credentials: none.

Bring the service up.

```bash
docker compose up -d --build ascend-weather-mcp
```

| # | Spec |
| :- | :--- |
| 1 | [1-invalid-input-test.md](../apps/ascend-weather-mcp/e2e/testing/1-invalid-input-test.md) |
| 2 | [2-current-structured-contract-test.md](../apps/ascend-weather-mcp/e2e/testing/2-current-structured-contract-test.md) |
| 3 | [3-current-city-not-found-test.md](../apps/ascend-weather-mcp/e2e/testing/3-current-city-not-found-test.md) |
| 4 | [4-forecast-happy-path-test.md](../apps/ascend-weather-mcp/e2e/testing/4-forecast-happy-path-test.md) |
| 5 | [5-air-quality-happy-path-test.md](../apps/ascend-weather-mcp/e2e/testing/5-air-quality-happy-path-test.md) |
| 6 | [6-geocode-multiple-candidates-test.md](../apps/ascend-weather-mcp/e2e/testing/6-geocode-multiple-candidates-test.md) |
| 7 | [7-current-country-code-disambiguation-test.md](../apps/ascend-weather-mcp/e2e/testing/7-current-country-code-disambiguation-test.md) |

Run order, from [apps/ascend-weather-mcp/e2e/README.md](../apps/ascend-weather-mcp/e2e/README.md) "Parallelism and execution order": spec 1 first, then specs 2 through 6 in any order or in parallel, then spec 7 last.

Resets: specs 1 through 6 need none. Spec 7's own Reset state restarts the `ascend-weather-mcp` container to clear the geocoding cache, which is why it runs last.

### ascend-web-hunter service suite

- Compose: either project. On the scraping project alone (`ascend-scrapper`), this service suite is [Scenario 5](#scenario-5-human-captcha-scraping-compose-only) with spec 11 or [Scenario 6](#scenario-6-automated-scraping-compose-only) without it, and their preconditions apply unchanged, including the bundled `ascend-scrapper-redis` when the host has no Redis. When the `ascend-ai` project is already up, run the same specs against the four containers it includes (`searxng`, `flaresolverr`, `ascend-web-hunter`, `ngrok-ascend-web-hunter`) with no project switch. Never have both projects up, per [Compose projects and the shared container names](#compose-projects-and-the-shared-container-names).
- External prerequisites: Redis `:6379` on the host, or the bundled Redis on the scraping project. PostgreSQL, Qdrant and the object store are not used.
- LM Studio: not applicable.
- Human at keyboard: only for spec 11. Leave spec 11 out when nobody is at the keyboard.
- Credentials in `.env`: `SEARXNG_SECRET` (mandatory), `NGROK_AUTHTOKEN`. `VNC_PASSWORD` is optional in this dev stack and worth setting before a human opens the tunnel for spec 11.

| # | Spec |
| :- | :--- |
| 1 | [1-invalid-input-test.md](../apps/ascend-web-hunter/e2e/testing/1-invalid-input-test.md) |
| 2 | [2-search-happy-path-test.md](../apps/ascend-web-hunter/e2e/testing/2-search-happy-path-test.md) |
| 3 | [3-read-example-com-test.md](../apps/ascend-web-hunter/e2e/testing/3-read-example-com-test.md) |
| 4 | [4-mcp-tools-list-test.md](../apps/ascend-web-hunter/e2e/testing/4-mcp-tools-list-test.md) |
| 5 | [5-mcp-search-test.md](../apps/ascend-web-hunter/e2e/testing/5-mcp-search-test.md) |
| 6 | [6-tiered-scraping-test.md](../apps/ascend-web-hunter/e2e/testing/6-tiered-scraping-test.md) |
| 7 | [7-authenticated-realworld-scraping-test.md](../apps/ascend-web-hunter/e2e/testing/7-authenticated-realworld-scraping-test.md) |
| 8 | [8-session-clear-test.md](../apps/ascend-web-hunter/e2e/testing/8-session-clear-test.md) |
| 9 | [9-session-status-test.md](../apps/ascend-web-hunter/e2e/testing/9-session-status-test.md) |
| 10 | [10-session-establish-test.md](../apps/ascend-web-hunter/e2e/testing/10-session-establish-test.md) |
| 11 | [11-captcha-solve-and-capture-test.md](../apps/ascend-web-hunter/e2e/testing/11-captcha-solve-and-capture-test.md) |
| 12 | [12-clearance-reuse-test.md](../apps/ascend-web-hunter/e2e/testing/12-clearance-reuse-test.md) |

Run order: [Scenario 5's run order](#run-order-4), whichever project is up. Spec 11, when it runs, goes last, alone, on the main session, with its `vnc_url` pasted verbatim and the human's confirmation before the capture check.

Resets: each spec's own Reset state names the Redis keys it wipes. The conflicts between specs 3, 6, 7, 8, 10, 11 and 12 over shared `session:*` keys are why the order is fixed, and [apps/ascend-web-hunter/e2e/README.md](../apps/ascend-web-hunter/e2e/README.md) "Parallelism and execution order" gives the reason for each. On the scraping project with the bundled Redis, every `docker exec redis` command targets `ascend-scrapper-redis`.

---

## Global ordering rules

These apply whenever more than one suite's runners share the host, which is every full-stack scenario (1 through
4). Measured 2026-09-09 and 2026-09-10.

- Default concurrency cap: 5 runners at once, across all suites combined, per the project's `e2e-runbooks` skill
  convention ([.agents/skills/e2e-runbooks/SKILL.md](../.agents/skills/e2e-runbooks/SKILL.md)).
- Each suite's spec 1 runs before any other spec in that suite, because spec 1 is the cheapest, fail-fast spec in
  every suite's own numbering convention.
- After spec 1, each suite proceeds through its own README's parallel groups.
- Two exclusivity classes override the concurrency cap entirely: the OCR engine-bound specs (2, 3, 4, 6, 13, 14, 15,
  16, 17, 18, 19) and the agent docling-bound specs (3, 5, 6, 7). Whenever one of these fifteen specs needs to run, it runs
  alone, no other runner of any suite anywhere on the host may be active at the same time, not even a reject-fast
  spec from the same suite. The OCR worker reads one document at a time and uses every CPU its container is given, and the docling engine
  is single-threaded per call, so a second runner on the host does not fail the shared spec, it slows it past its own
  timeout budget. Measured on 2026-09-10 with the same OCR English fixture: 59.2
  seconds on a quiet host against 160.9 seconds beside four other suites' runners, past the 150-second per-page
  budget [compose.yaml](../compose.yaml) set for that suite at the time. The OCR service now stops a page that
  overruns its engine's page allowance with `OCR_FAILED` instead.
- Weather spec 7 runs last within the weather suite, because it restarts the `ascend-weather-mcp` container,
  clearing the geocoding cache specs 2 through 6 rely on having warmed.
- Memory specs 2, 3, 5, and 6 run in every full-stack scenario. Their Bruno requests pin the `openai` provider, so they need `OPENAI_API_KEY` and never LM Studio. `MEM0_DEFAULT_PROVIDER=lmstudio` applies only to a caller that omits `provider`.
- Web-hunter's own chain never breaks inside a full-stack sweep: spec 1, then specs 2, 4, 5, 9 in parallel, then
  spec 6, then spec 12 (same site as spec 6, before spec 7's `session:*` flush), then spec 7 (fully automated, its
  busy rows retried per its own rule), then spec 3, then spec 8, then spec 10 alone, then spec 11
  (`11-captcha-solve-and-capture`) last and only on the human's go, with the `vnc_url` pasted verbatim into the
  chat and the human confirming before the capture check.

The practical shape this produces: a "parallel lane" holding up to 5 runners across the five non-exclusive suites
plus web-hunter's own non-exclusive specs, and a "quarantine lane" for the fifteen exclusivity specs that the
parallel lane pauses for and resumes after.

---

## Measured wall-clock

A full automated sweep across every suite, measured on 2026-09-10 with five parallel runners, covered 46 specs and
took about two hours wall-clock end to end. This figure is reported as measured on that date rather than
reconciled against today's six-suite total of 61 (or any single scenario's spec count above): the suites have
since been corrected and extended (see the `07469b9` and `23597ac` commits), so a spec added or corrected after
2026-09-10 is not represented in that two-hour figure.

---

## Documentation map

| Document | What it covers |
| :------- | :-------------- |
| [AGENTS.md](../AGENTS.md) | Repository-wide conventions, compose project mechanics, the End-to-End Test Suite pointer |
| [apps/ascend-agent/e2e/README.md](../apps/ascend-agent/e2e/README.md) | ascend-agent's 11 specs, fixtures, and its own parallel groups |
| [apps/ascend-audio-scribe/e2e/README.md](../apps/ascend-audio-scribe/e2e/README.md) | ascend-audio-scribe's 5 specs |
| [apps/ascend-memory/e2e/README.md](../apps/ascend-memory/e2e/README.md) | ascend-memory's 6 specs and its provider dependency |
| [apps/ascend-ocr/e2e/README.md](../apps/ascend-ocr/e2e/README.md) | ascend-ocr's 20 specs and the engine-bound exclusivity rule |
| [apps/ascend-weather-mcp/e2e/README.md](../apps/ascend-weather-mcp/e2e/README.md) | ascend-weather-mcp's 7 specs |
| [apps/ascend-web-hunter/e2e/README.md](../apps/ascend-web-hunter/e2e/README.md) | ascend-web-hunter's 12 specs, including the human-gated spec 11 and the automated reuse proof in spec 12 |
| [.agents/skills/e2e-runbooks/SKILL.md](../.agents/skills/e2e-runbooks/SKILL.md) | The general spec / tasks-template / runs methodology and the default concurrency cap |
| [docs/E2E_COST.md](E2E_COST.md) | Per-provider dollar cost of a sweep, rolled up from each run record's token fields |
