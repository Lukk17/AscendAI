# Logs reach Loki: e2e test

## What this verifies

- One refused request to each running service shows up in Loki.
- Each service answer holds at least one stream with at least one entry newer than the recorded time.
- Entry counts are asserted, never entry text.

## Prerequisites

Bruno CLI installed, the always-on stack running, Loki reachable through Grafana.

```bash
bru --version
```

```bash
docker compose exec grafana wget -qO- "http://loki:3100/ready"
```

The second command prints `ready`.

## Reset state

None. This test writes no fixture state. The refused requests leave only their own log lines, which is what the test counts.

## Run

Record the current time in nanoseconds.

```bash
date +%s%N
```

Send one refused request to each running service. Each prints `404`.

```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:9917/e2e-canary-no-such-path
```

```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:9998/e2e-canary-no-such-path
```

```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:7020/e2e-canary-no-such-path
```

```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:7017/e2e-canary-no-such-path
```

```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:7021/e2e-canary-no-such-path
```

```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:7022/e2e-canary-no-such-path
```

Wait 10 seconds so Vector ships the lines to Loki.

```bash
sleep 10
```

Query Loki once per service, with `<recorded time>` replaced by the value of the first step.

```bash
docker compose exec grafana wget -qO- "http://loki:3100/loki/api/v1/query_range?query=%7Bservice%3D%22ascend-agent%22%7D&start=<recorded time>&limit=5"
```

```bash
docker compose exec grafana wget -qO- "http://loki:3100/loki/api/v1/query_range?query=%7Bservice%3D%22ascend-weather-mcp%22%7D&start=<recorded time>&limit=5"
```

```bash
docker compose exec grafana wget -qO- "http://loki:3100/loki/api/v1/query_range?query=%7Bservice%3D%22ascend-memory%22%7D&start=<recorded time>&limit=5"
```

```bash
docker compose exec grafana wget -qO- "http://loki:3100/loki/api/v1/query_range?query=%7Bservice%3D%22ascend-audio-scribe%22%7D&start=<recorded time>&limit=5"
```

```bash
docker compose exec grafana wget -qO- "http://loki:3100/loki/api/v1/query_range?query=%7Bservice%3D%22ascend-web-hunter%22%7D&start=<recorded time>&limit=5"
```

```bash
docker compose exec grafana wget -qO- "http://loki:3100/loki/api/v1/query_range?query=%7Bservice%3D%22ascend-ocr%22%7D&start=<recorded time>&limit=5"
```

## Expected

- Each refused request answers HTTP 404.
- Each Loki answer holds at least one stream with at least one entry newer than the recorded time.
- No expected line names the text of a log line.

## Fixtures

None.
