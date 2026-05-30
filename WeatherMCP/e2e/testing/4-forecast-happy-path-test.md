# Forecast happy path: e2e test

## What this verifies

- `weather.forecast` for Warsaw with `days=3` returns HTTP 200 and `status="ok"`.
- The `forecast` array has length exactly 3.
- Each element has a `date` field (ISO `yyyy-MM-dd`), numeric `temperatureMax`, numeric `temperatureMin`, optional
  numeric `precipitationSum`, integer `weatherCode`.
- Dates are strictly increasing.
- The first date equals today (UTC) or today+1 (depending on Open-Meteo's day cutover for the requesting region).
- `location.countryCode` equals `"PL"`.
- `temperatureUnit` equals `"celsius"` (the default when the caller does not pass `unit`).
- `source` equals `"open-meteo"`.

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

Check outbound HTTPS to Open-Meteo's forecast API works.

```powershell
curl -fsS "https://api.open-meteo.com/v1/forecast?latitude=52&longitude=21&daily=temperature_2m_max&forecast_days=1"
```

Expect HTTP 200 with a `daily` block.

## Reset state

None. Whether the geocoding cache is warm or cold does not affect this assertion.

## Run

Single Bruno request.

```powershell
cd docs/api/request/AscendAI
```

```powershell
bru run "mcp/weather-mcp/forecast-warsaw-3d.yml" --env ascend-local
```

## Expected

HTTP 200. The JSON-RPC `result` content matches:

- `status` equals `"ok"`.
- `message` is `null`.
- `requestedQuery` is `null`.
- `location.name` is non-empty and contains "Warsaw" (case-insensitive).
- `location.countryCode` equals `"PL"`.
- `forecast` is an array of exactly 3 entries.
- For each entry: `date` matches `yyyy-MM-dd`; `temperatureMax` and `temperatureMin` are finite numbers with
  `temperatureMin <= temperatureMax`; `weatherCode` is an integer in 0–99.
- The `date` values are strictly increasing.
- `temperatureUnit` equals `"celsius"`.
- `source` equals `"open-meteo"`.
- `fetchedAt` parses as a valid `Instant`.

## Fixtures

None.
