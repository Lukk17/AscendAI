# platform: end-to-end capability tests

Manual and AI-runnable e2e suite for checks that span the whole AscendAI stack rather than one service. Created by task 17.1 of the add-observability change. That change is the first of the owner build order of 2026-10-04 to need this suite. Later changes add their specs here, namely harden-cloud-deployment and add-deployment-modules.

Before running this suite, or any other e2e suite, pick a run scenario or a service suite from [docs/E2E_RUN_SCENARIOS.md](../../docs/E2E_RUN_SCENARIOS.md). Ask the owner which scenario or service suite to run before any run, as [AGENTS.md](../../AGENTS.md) requires.

## What is here

```text
e2e/platform/
├── README.md
├── fixtures/
│   └── README.md
└── testing/
    ├── README.md
    ├── <N>-<capability>-test.md
    ├── templates/
    │   ├── README.md
    │   └── <N>-<capability>-tasks.template.md
    └── runs/
        ├── README.md
        └── <UTC-timestamp>_<N>-<capability>-tasks.md
```

The layout matches the app suites, for example

```text
apps/ascend-ocr/e2e/
```

## Spec classes

Each spec takes the next free number of this suite when it is written, never a number fixed in tasks.md. Task 17.4 moved to add-ascend-python-common and upgrade-spring-boot-4, so it leaves no spec here.

| Task | Spec | What it proves |
| :--- | :--- | :--- |
| 17.3 | metrics and targets | Every scrape job of infra/observability/prometheus/prometheus.yaml reports up in Prometheus, without writing any state |
| 17.5 | logs reach Loki | One refused request per running service shows up as entries in Loki, counted per service, never matched by text |
| 17.6 | actuator exposure | The agent serves metrics only on the internal management port and the weather service only on its application port, and the closed actuator endpoints answer 404 |
| 17.7 | AI traffic observability | One model call per provider leaves token series, cache series, a Tempo trace with a chat span and a tool span, and non-empty dashboard queries |

Tasks 17.8 and 17.9 own the rows of this table and the list of what is not tested end to end. See [testing/README.md](testing/README.md) for the spec format and [docs/E2E_RUN_SCENARIOS.md](../../docs/E2E_RUN_SCENARIOS.md) for the run scenarios.

The Bruno collection lives at the repo root under

```text
docs/api/request/AscendAI/platform/
```

so it stays a portable API client artifact next to the other collections. Each spec references the matching Bruno request file under that path.

## Shared rules

Pass criteria are observable behaviour only: HTTP status, response bodies, Prometheus targets and series, the number of Loki entries, and the traces Tempo holds. Never the text of a log line.

Every spec but the one of task 17.7 is deterministic: no AI model is called, and every Bruno request asserts its result in its own tests script.

Specs and tasks templates are immutable between runs. The runner copies the template into [testing/runs/](testing/runs/) under a sweep timestamp and fills in that copy only. Run records are gitignored by default.

## What is not tested end to end

Task 17.9 owns this list. Each entry names the requirement and the reason no sweep spec covers it.

- Retention settings (task 15.7): the effective `retention_period` and `block_retention` are read back from the Loki and Tempo config endpoints, not behaviour a request can observe within a sweep.
- 30 minute load test (task 15.5): it measures capacity and disk growth under sustained prompts, not correctness, so it runs as a one-off measurement rather than a repeatable spec.
- Token Cost dashboard after a `pricing.yaml` change (task 14.3): new rates need a Grafana restart with an edited file before the dashboard reflects them, so the check is a restart procedure, not a sweep assertion.
- Scrape interval and Vector migration sinks: configuration values and commented placeholders in `vector.toml`, checked by review rather than by observable behaviour.
- Failure-path metrics such as `memory.extraction.parse_failed` or `memory.insert.failed`: a live provider and ascend-memory cannot be made to fail on demand, so these counters are covered by the metric tests of groups 3 to 6 instead of a live spec.

## Neighbours

- [e2e/platform/fixtures/README.md](fixtures/README.md)
- [e2e/platform/testing/README.md](testing/README.md)
- [e2e/platform/testing/templates/README.md](testing/templates/README.md)
- [e2e/platform/testing/runs/README.md](testing/runs/README.md)
