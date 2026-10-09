# Actuator exposure: e2e test

## What this verifies

- The agent serves its actuator endpoints only on the internal management port `9918`, never on the application port `9917`.
- The management port is unreachable from the host.
- Every sample line of the agent metrics carries `service="ascend-agent"`.
- The closed actuator endpoints `env`, `heapdump`, `threaddump`, `loggers` and `caches` answer 404 on the agent and on the weather service.
- Every sample line of the weather metrics carries `service="ascend-weather-mcp"`.

## Prerequisites

The always-on stack running, Prometheus able to reach the agent on the compose network.

```bash
docker compose ps ascend-agent
```

The agent shows a healthy state.

## Reset state

None. This test writes no persisted state.

## Run

The application port serves no actuator output.

```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:9917/actuator/prometheus
```

The management port is unreachable from the host. The command fails to connect.

```bash
curl -s http://localhost:9918/actuator/health
```

Prometheus reaches the management port on the compose network.

```bash
docker compose exec prometheus wget -qO- http://ascend-agent:9918/actuator/prometheus
```

The closed agent endpoints answer 404 from inside the network.

```bash
docker compose exec prometheus wget -qO- http://ascend-agent:9918/actuator/env
```

```bash
docker compose exec prometheus wget -qO- http://ascend-agent:9918/actuator/heapdump
```

```bash
docker compose exec prometheus wget -qO- http://ascend-agent:9918/actuator/threaddump
```

```bash
docker compose exec prometheus wget -qO- http://ascend-agent:9918/actuator/loggers
```

```bash
docker compose exec prometheus wget -qO- http://ascend-agent:9918/actuator/caches
```

The closed endpoints answer 404 on the weather service from the host.

```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:9998/actuator/env
```

```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:9998/actuator/heapdump
```

```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:9998/actuator/threaddump
```

```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:9998/actuator/loggers
```

```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:9998/actuator/caches
```

Read the weather metrics from the host.

```bash
curl -s http://localhost:9998/actuator/prometheus
```

## Expected

- `curl -s -o /dev/null -w "%{http_code}" http://localhost:9917/actuator/prometheus` prints `404`.
- `curl -s http://localhost:9918/actuator/health` from the host fails to connect.
- The metrics from `http://ascend-agent:9918/actuator/prometheus` hold metric lines, and every sample line carries `service="ascend-agent"`.
- `/actuator/env`, `/actuator/heapdump`, `/actuator/threaddump`, `/actuator/loggers` and `/actuator/caches` answer 404 on `ascend-agent:9918` from inside the network and on `http://localhost:9998` from the host.
- Every sample line of `curl -s http://localhost:9998/actuator/prometheus` carries `service="ascend-weather-mcp"`.

## Fixtures

None.
