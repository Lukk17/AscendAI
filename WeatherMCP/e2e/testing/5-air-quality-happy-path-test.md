# Air quality happy path: e2e test

## What this verifies

- `weather.airQuality` for Warsaw returns HTTP 200 and `status="ok"`.
- The response carries at least one PM field (`pm10`, `pm25`) as a finite non-negative number.
- At least one AQI field (`usAqi` or `europeanAqi`) is an integer ≥ 0.
- `location.name` matches "Warsaw" (case-insensitive); `location.countryCode` equals `"PL"`.
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

Check outbound HTTPS to Open-Meteo's air-quality API works.

```powershell
curl -fsS "https://air-quality-api.open-meteo.com/v1/air-quality?latitude=52&longitude=21&current=pm10"
```

Expect HTTP 200.

## Reset state

None.

## Run

Single Bruno request.

```powershell
cd docs/api/request/AscendAI
```

```powershell
bru run "weather-mcp/air-quality-warsaw.yml" --env ascend-local
```

## Expected

HTTP 200. The JSON-RPC `result` content matches:

- `status` equals `"ok"`.
- `message` is `null`.
- `requestedQuery` is `null`.
- `location.name` is non-empty and contains "Warsaw" (case-insensitive).
- `location.countryCode` equals `"PL"`.
- At least one of `pm10` or `pm25` is a finite non-negative number.
- At least one of `usAqi` or `europeanAqi` is an integer ≥ 0.
- `source` equals `"open-meteo"`.
- `fetchedAt` parses as a valid `Instant`.

## Fixtures

None.
