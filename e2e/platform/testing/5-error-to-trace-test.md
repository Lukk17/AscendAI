# Error to trace: e2e test

## What this verifies

- A request to a path AscendMemory does not serve answers the 404 problem body, with `code` `not_found` and a `traceId` of 32 lower case hex characters.
- Tempo holds the trace that `traceId` names, and that trace carries a span whose resource attribute `service.name` is `ascend-memory`.
- No model is called and no persisted state is written, so the trace of the refusal is the whole evidence.

## Prerequisites

Bruno CLI installed, the always-on stack running, AscendMemory healthy and exporting traces, and Tempo reachable from the Grafana container.

```bash
bru --version
```

```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:7020/health
```

The second command prints `200`.

```bash
docker compose exec grafana wget -qO- "http://tempo:3200/api/search?tags=service.name%3Dascend-memory&limit=1"
```

The third command answers with a Tempo search body that lists at least one trace, which proves AscendMemory exports spans and Tempo holds them.

## Reset state

None. This test writes no persisted state.

## Run

```bash
cd docs/api/request/AscendAI
```

```bash
bru run "platform/observability/memory-unknown-path.yml" --env ascend-local
```

The request stores the `traceId` of the problem body in the Bruno variable `traceId` and prints it as `traceId=<value>`. Record that value for the next step.

Wait 15 seconds so the span of the refused request reaches Tempo through the collector.

```bash
sleep 15
```

```bash
docker compose exec grafana wget -qO- http://tempo:3200/api/traces/<traceId>
```

Replace `<traceId>` with the value recorded in the Run step.

## Expected

- `memory-unknown-path.yml` answers HTTP 404 with content type `application/problem+json`, `status` 404 and `code` `not_found`.
- The problem body carries a `traceId` that matches `^[0-9a-f]{32}$`.
- The Tempo answer for that `traceId` holds at least one batch and that batch carries the resource attribute `service.name` with the value `ascend-memory`.
- No expected line matches the text of a log line.

## Fixtures

None.

## Concurrency

- Mutates: nothing
- Conflicts with: none
- Serial: false
- Hermetic contract: reads only the problem body and the trace Tempo returns, so it leaves no state behind for any other spec.
