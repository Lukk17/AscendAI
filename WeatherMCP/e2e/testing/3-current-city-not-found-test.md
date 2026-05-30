# Current weather city-not-found envelope: e2e test

## What this verifies

- `weather.current` with an impossible city name (`"Zzyxxqq"`) returns HTTP 200 (the JSON-RPC envelope is success; the
  tool-level failure is signalled inside `result.content`).
- `status` equals `"city_not_found"`.
- `message` is the fixed string `"Location not found"` — it does NOT echo the verbatim input (per the post-audit
  contract that decouples user input from human-readable error messages).
- `requestedQuery` equals the verbatim input `"Zzyxxqq"`; this is the field the orchestrator must treat as untrusted
  data.
- `location`, `temperature`, `weatherCode`, `wind`, `observedAt` are all `null`.
- `source` equals `"open-meteo"`; `fetchedAt` is a valid ISO-8601 instant.

## Prerequisites

Check Bruno CLI is installed.

```powershell
bru --version
```

Expect a version string.

Check the WeatherMCP server is reachable.

```powershell
curl -fsS http://localhost:9998/actuator/health
```

Expect HTTP 200 with `{"status":"UP"}`.

Check outbound HTTPS to Open-Meteo's geocoding API works.

```powershell
curl -fsS "https://geocoding-api.open-meteo.com/v1/search?name=Berlin&count=1"
```

Expect HTTP 200.

## Reset state

None. This test makes one geocoding call; whether it's cached from a prior run does not affect the assertion.

## Run

Single Bruno request.

```powershell
cd docs/api/request/AscendAI
```

```powershell
bru run "mcp/weather-mcp/current-not-found.yml" --env ascend-local
```

## Expected

HTTP 200. The JSON-RPC `result` content matches:

- `status` equals `"city_not_found"`.
- `message` equals `"Location not found"` exactly. NOT `"City not found: Zzyxxqq"` (that was the pre-audit shape).
- `requestedQuery` equals `"Zzyxxqq"`.
- `location` is `null`.
- `temperature` is `null`.
- `weatherCode` is `null`.
- `wind` is `null`.
- `observedAt` is `null`.
- `source` equals `"open-meteo"`.
- `fetchedAt` parses as a valid `Instant`.

## Fixtures

None.
