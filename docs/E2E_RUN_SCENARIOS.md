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

The repository ships 53 specs total across the six suites (11 + 5 + 6 + 12 + 7 + 12). No single scenario below runs
all 53 with nobody at the keyboard, because one spec (`ascend-web-hunter` spec 11, `11-captcha-solve-and-capture`)
needs a human to solve an hCaptcha challenge through NoVNC. Scenario 4 is the only one that runs every spec, and it
needs a human present for that one spec.

---

## How to ask

Before running any end-to-end test, ask which scenario from this document the requester wants. Never assume one,
even when the request sounds like "run the e2e tests" with no further detail. The six scenarios differ in which
compose project is up, whether LM Studio must answer, whether a human needs to be at the keyboard, and how many
specs run, so picking wrong wastes a compose cycle at minimum and, for the human-gated scenarios, wastes a person's
attention waiting for a step that scenario never reaches.

---

## Scenario summary

| Scenario | Stack | LM Studio | Human at keyboard | Spec count |
| :------- | :---- | :-------- | :----------------- | :--------- |
| 1 | Full (`ascend-ai`, includes the scraping stack) | Off | No | 48 |
| 2 | Full (`ascend-ai`, includes the scraping stack) | On | No | 52 |
| 3 | Full (`ascend-ai`, includes the scraping stack) | Off | Yes | 49 |
| 4 | Full (`ascend-ai`, includes the scraping stack) | On | Yes | 53 |
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
- LM Studio: off. Memory specs 2, 3, 5, and 6 default to the `lmstudio` embedding provider and are skipped.
- Human at keyboard: not needed. `ascend-web-hunter` spec 11 (the only human-gated spec in the repository) does not
  run in this scenario.
- Credentials present in `.env`: `OPENAI_API_KEY` (agent spec 8, audio-scribe specs 2 and 5),
  `ASCEND_ANTHROPIC_API_KEY` (agent spec 9), `HF_TOKEN` (audio-scribe spec 3), `SEARXNG_SECRET` (mandatory, the
  scraping stack refuses to start without it), `NGROK_AUTHTOKEN` (the `ngrok-ascend-web-hunter` container needs it
  to run cleanly even though nobody opens the tunnel in this scenario). `GEMINI_API_KEY` and `MINIMAX_API_KEY` are
  not exercised by any spec in this scenario.

### Spec list

| Suite | Specs run | Count |
| :---- | :-------- | :---- |
| ascend-agent | 1-11 | 11 |
| ascend-audio-scribe | 1-5 | 5 |
| ascend-memory | 1, 4 | 2 |
| ascend-ocr | 1-12 | 12 |
| ascend-weather-mcp | 1-7 | 7 |
| ascend-web-hunter | 1-10, 12 | 11 |
| Total | | 48 |

### Skipped specs

- `ascend-memory` 2, 3, 5, 6: default to the `lmstudio` provider, and LM Studio is off in this scenario.
- `ascend-web-hunter` 11: needs a human at NoVNC to solve an hCaptcha challenge.

### Run order

1. Every suite's spec 1 runs first (fail fast, cheapest setup), up to 5 runners at once across all suites.
2. Each suite then proceeds through its own README's parallel groups. The OCR engine-bound specs (2, 3, 4, 6) and
   the agent docling-bound specs (3, 5, 6, 7) each run alone whenever their turn comes: no other runner of any
   suite, anywhere on the host, may be active at the same time. See
   [Global ordering rules](#global-ordering-rules) for the measured cost of breaking this rule.
3. Weather spec 7 runs last within the weather suite, because it restarts the `ascend-weather-mcp` container.
4. Memory runs only specs 1 and 4 in this scenario.
5. Web-hunter's own chain: spec 1, then specs 2, 4, 5, 9 in parallel, then spec 6, then spec 12 (same site as spec
   6, and before spec 7 because spec 7's reset would wipe its capture), then spec 7 (fully automated, its
   `409 novnc_busy` rows retried per its own `Retry-After` rule), then spec 3, then spec 8, then spec 10 alone.
   Spec 11 does not run in this scenario.

---

## Scenario 2: Automated, full stack, LM Studio on

### Preconditions

Same as [Scenario 1](#scenario-1-automated-full-stack-lm-studio-off), except:

- LM Studio: on, answering at `:1234`. Memory specs 2, 3, 5, and 6 need the `lmstudio` embedding provider
  reachable there and the embedding model it names loaded.
- No new credential beyond Scenario 1's list. LM Studio uses the hardcoded local key `sk_local`
  ([compose.yaml](../compose.yaml)), not a `.env` entry.

### Spec list

| Suite | Specs run | Count |
| :---- | :-------- | :---- |
| ascend-agent | 1-11 | 11 |
| ascend-audio-scribe | 1-5 | 5 |
| ascend-memory | 1-6 | 6 |
| ascend-ocr | 1-12 | 12 |
| ascend-weather-mcp | 1-7 | 7 |
| ascend-web-hunter | 1-10, 12 | 11 |
| Total | | 52 |

### Skipped specs

- `ascend-web-hunter` 11: needs a human at NoVNC to solve an hCaptcha challenge.

### Run order

Same as [Scenario 1's run order](#run-order), except step 4 becomes: memory runs its full chain, specs 1 through 6,
in any order or in parallel, since all six specs use disjoint user ids per its own README.

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
| ascend-memory | 1, 4 | 2 |
| ascend-ocr | 1-12 | 12 |
| ascend-weather-mcp | 1-7 | 7 |
| ascend-web-hunter | 1-12 | 12 |
| Total | | 49 |

### Skipped specs

- `ascend-memory` 2, 3, 5, 6: default to the `lmstudio` provider, and LM Studio is off in this scenario.

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
| ascend-ocr | 1-12 | 12 |
| ascend-weather-mcp | 1-7 | 7 |
| ascend-web-hunter | 1-12 | 12 |
| Total | | 53 |

### Skipped specs

None. This is the only scenario that runs every spec the repository ships.

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

## Global ordering rules

These apply whenever more than one suite's runners share the host, which is every full-stack scenario (1 through
4). Measured 2026-09-09 and 2026-09-10.

- Default concurrency cap: 5 runners at once, across all suites combined, per the project's `e2e-runbooks` skill
  convention ([.agents/skills/e2e-runbooks/SKILL.md](../.agents/skills/e2e-runbooks/SKILL.md)).
- Each suite's spec 1 runs before any other spec in that suite, because spec 1 is the cheapest, fail-fast spec in
  every suite's own numbering convention.
- After spec 1, each suite proceeds through its own README's parallel groups.
- Two exclusivity classes override the concurrency cap entirely: the OCR engine-bound specs (2, 3, 4, 6) and the
  agent docling-bound specs (3, 5, 6, 7). Whenever one of these eight specs needs to run, it runs alone, no other
  runner of any suite anywhere on the host may be active at the same time, not even a reject-fast spec from the
  same suite. Both engines are single-threaded per call, so a second runner on the host does not fail the shared
  spec, it slows it past its own timeout budget. Measured on 2026-09-10 with the same OCR English fixture: 59.2
  seconds on a quiet host against 160.9 seconds beside four other suites' runners, past the 150-second per-page
  budget [compose.yaml](../compose.yaml) sets for that suite.
- Weather spec 7 runs last within the weather suite, because it restarts the `ascend-weather-mcp` container,
  clearing the geocoding cache specs 2 through 6 rely on having warmed.
- Memory specs 2, 3, 5, and 6 run only when LM Studio is answering, because they default to the `lmstudio`
  embedding provider (`apps/ascend-memory/AGENTS.md`, `MEM0_DEFAULT_PROVIDER=lmstudio`).
- Web-hunter's own chain never breaks inside a full-stack sweep: spec 1, then specs 2, 4, 5, 9 in parallel, then
  spec 6, then spec 12 (same site as spec 6, before spec 7's `session:*` flush), then spec 7 (fully automated, its
  busy rows retried per its own rule), then spec 3, then spec 8, then spec 10 alone, then spec 11
  (`11-captcha-solve-and-capture`) last and only on the human's go, with the `vnc_url` pasted verbatim into the
  chat and the human confirming before the capture check.

The practical shape this produces: a "parallel lane" holding up to 5 runners across the five non-exclusive suites
plus web-hunter's own non-exclusive specs, and a "quarantine lane" for the eight exclusivity specs that the
parallel lane pauses for and resumes after.

---

## Measured wall-clock

A full automated sweep across every suite, measured on 2026-09-10 with five parallel runners, covered 46 specs and
took about two hours wall-clock end to end. This figure is reported as measured on that date rather than
reconciled against today's six-suite total of 53 (or any single scenario's spec count above): the suites have
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
| [apps/ascend-ocr/e2e/README.md](../apps/ascend-ocr/e2e/README.md) | ascend-ocr's 12 specs and the engine-bound exclusivity rule |
| [apps/ascend-weather-mcp/e2e/README.md](../apps/ascend-weather-mcp/e2e/README.md) | ascend-weather-mcp's 7 specs |
| [apps/ascend-web-hunter/e2e/README.md](../apps/ascend-web-hunter/e2e/README.md) | ascend-web-hunter's 12 specs, including the human-gated spec 11 and the automated reuse proof in spec 12 |
| [.agents/skills/e2e-runbooks/SKILL.md](../.agents/skills/e2e-runbooks/SKILL.md) | The general spec / tasks-template / runs methodology and the default concurrency cap |
| [docs/E2E_COST.md](E2E_COST.md) | Per-provider dollar cost of a sweep, rolled up from each run record's token fields |
