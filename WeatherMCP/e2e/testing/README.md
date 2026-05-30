# e2e testing guide

Self-contained walkthroughs that an AI agent (or a human) can execute end-to-end against a live WeatherMCP container.
Each `<N>-<capability>-test.md` spec in this directory drives one MCP tool through its Bruno request, with explicit
prerequisite checks, reset commands, run steps, and expected outcomes. The paired run-record templates live in the
`templates/` subdirectory; executed run records land in `runs/`.

## Format

Every `<N>-<capability>-test.md` file is the **immutable spec** for one test and uses the same fixed template.

1. **What this verifies.** Bullet list of behaviours.
2. **Prerequisites.** Concrete check commands (`curl`, `bru --version`) the runner executes before starting. Each
   command is its own code block; the prose around it states what success looks like.
3. **Reset state.** One command per code block, executed in order, to wipe state so the test is reproducible. Most
   WeatherMCP tests do not need reset (read-only against Open-Meteo). Test 7 restarts the container to clear the
   geocoding cache.
4. **Run.** One or more numbered steps. Each step is a single Bruno CLI invocation. Steps wait for HTTP 200 before
   continuing.
5. **Expected.** Observable-behaviour assertions verified after each step: HTTP status codes, JSON-RPC `result`
   payload shape, the structured `WeatherToolStatus` value (`"ok"`, `"city_not_found"`, `"no_results"`,
   `"upstream_unavailable"`, `"invalid_input"`), the populated / null fields per status. NOT log substrings.
6. **Fixtures.** Paths to local files the test reads (none for the current suite).

Each spec has a matching `<N>-<capability>-tasks.template.md` in the [templates/](templates/) subdirectory — the
**checkbox template** for a run. The runner never edits the spec or the template directly. Before starting a run, it
copies the template from `templates/` into [runs/](runs/) with a timestamped filename, ticks boxes as it progresses,
fills in `Result summary` and `Verdict`, and logs anything done outside the spec under `Additional tasks I did`. See
[runs/README.md](runs/README.md) for the full contract and naming convention.

## Bruno is the source of truth

Every test runs the matching Bruno request file under `docs/api/request/AscendAI/weather-mcp/` via the Bruno CLI.

```powershell
cd docs/api/request/AscendAI
```

```powershell
bru run "weather-mcp/<request>.yml" --env ascend-local
```

The request's saved default rows are what gets sent. To test an alternative payload, edit the disabled rows in the
YAML directly.

Install Bruno CLI once with `npm install -g @usebruno/cli`.

## Test order

Numbered by setup cost (lowest first). Run earliest first when stepping through; each is self-contained so any can
be run on its own.

1. [1-invalid-input-test.md](1-invalid-input-test.md). Validator short-circuit. **Air-gap-safe.**
2. [2-current-structured-contract-test.md](2-current-structured-contract-test.md). Tools list + structured Warsaw call.
3. [3-current-city-not-found-test.md](3-current-city-not-found-test.md). Impossible-name `city_not_found` envelope.
4. [4-forecast-happy-path-test.md](4-forecast-happy-path-test.md). 3-day forecast shape.
5. [5-air-quality-happy-path-test.md](5-air-quality-happy-path-test.md). AQI + PM fields.
6. [6-geocode-multiple-candidates-test.md](6-geocode-multiple-candidates-test.md). Ambiguity stress (`"Springfield"`).
7. [7-current-country-code-disambiguation-test.md](7-current-country-code-disambiguation-test.md). Warsaw PL vs Warsaw US. **Container restart between probes.**

## Cross-cutting conventions

Pass criteria are observable behaviour only. HTTP status, JSON-RPC response body content, the structured `status`
enum value, the populated / null fields per status. Logs are diagnostic, not authoritative. Log lines drift across
versions and aren't visible from every runner's shell. If a behaviour assertion fails, a tail of the WeatherMCP log
(or `docker logs weather-mcp`) is the next diagnostic step, but not a pass criterion.

## Adding a new test

1. Add a Bruno request under `docs/api/request/AscendAI/weather-mcp/<request>.yml`.
2. Create `WeatherMCP/e2e/testing/<N>-<capability>-test.md` using the template above. Pick the lowest unused number
   prefix that matches its setup-cost position in the order.
3. Create `WeatherMCP/e2e/testing/templates/<N>-<capability>-tasks.template.md` mirroring the spec's checkboxes.
4. Add the file to the ordered list in this README and in the capability table in the parent
   [../README.md](../README.md).
