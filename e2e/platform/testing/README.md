# e2e testing guide

Self-contained walkthroughs that an AI agent or a human can execute end to end against the live AscendAI stack. Each spec in this directory drives one platform capability through its Bruno requests and direct checks against Prometheus, Grafana, Loki, and Tempo, with explicit prerequisite checks, reset commands, run steps, and expected outcomes. The paired run-record templates live in the templates subdirectory. Executed run records land in runs.

## Format

Every spec file is the immutable spec for one test and uses the same fixed template.

1. What this verifies. Bullet list of behaviours.
2. Prerequisites. Concrete check commands the runner executes before starting. Each command is its own code block. The prose around it states what success looks like.
3. Reset state. One command per code block, executed in order, to wipe state so the test is reproducible. The metrics and targets spec writes nothing, so it needs no post-run cleanup. The AI traffic spec removes the chat history rows, Redis keys, and memory points of its own test user.
4. Run. Numbered steps. Each step is a single Bruno CLI invocation from the platform collection, a curl check, or a docker compose exec query against Loki or Tempo. Steps wait for HTTP 200 before continuing unless the spec expects another status.
5. Expected. Observable-behaviour assertions verified after each step: HTTP status codes, response body shape, Prometheus target health and series, Loki entry counts per service, Tempo traces and span names. Not log substrings.
6. Fixtures. Paths to local files the test reads, or None. Platform specs use none today, see the fixtures guide.

Each spec has a matching tasks template in the [templates/](templates/) subdirectory: the checkbox template for a run. The runner never edits the spec or the template directly. Before starting a run, it copies the template from templates into [runs/](runs/) with a timestamped filename, ticks boxes as it progresses, fills in Result summary and Verdict, and logs anything done outside the spec under Additional tasks I did. See [runs/README.md](runs/README.md) for the full contract and naming convention.

## Bruno is the source of truth

Every test runs the matching Bruno request files under the platform collection via the Bruno CLI. The observability requests live under the observability subfolder of that collection.

```powershell
cd docs/api/request/AscendAI
```

```powershell
bru run "platform/observability/prometheus-targets.yml" --env ascend-local
```

Install Bruno CLI once.

```powershell
npm install -g @usebruno/cli
```

The request saved default rows are what gets sent. A request that needs a caller-supplied list takes it as an env var on the command line, for example the expected scrape jobs or the Grafana admin password read from .env. To test an alternative payload, edit the disabled rows in the YAML directly.

## Execution order

Each new numbered spec takes the next free number of this suite when it is written, never a number fixed in tasks.md.

Every spec but the one of task 17.7 is deterministic: no AI model is called, and every Bruno request asserts its result in its own tests script. The AI traffic spec of task 17.7 is the only one that calls a model, so it runs alone against a quiet stack and after the deterministic specs.

Before any run, ask the owner which run scenario or service suite from the scenarios document to run, as the suite guide requires. The scenario document keeps that rule.

## Adding a new test

1. Add the Bruno request under the platform collection.
2. Create the spec in this directory using the template above.
3. Create the matching tasks template in [templates/](templates/) mirroring the spec checkboxes.
4. If the test needs a new fixture, add a row to the fixtures guide.
5. Add the file to the ordered list in the suite guide.

## Neighbours

- [e2e/platform/README.md](../README.md)
- [e2e/platform/fixtures/README.md](../fixtures/README.md)
- [e2e/platform/testing/templates/README.md](templates/README.md)
- [e2e/platform/testing/runs/README.md](runs/README.md)
