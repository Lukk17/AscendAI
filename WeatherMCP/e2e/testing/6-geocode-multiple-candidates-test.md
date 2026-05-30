# Geocode multiple candidates: e2e test

## What this verifies

- `weather.geocode` for `query="Springfield"` with `limit=5` returns HTTP 200 and `status="ok"`.
- The `candidates` array contains at least 3 entries with distinct `(latitude, longitude)` tuples.
- At least one candidate has `countryCode="US"` (Springfield, MO / IL / MA / OH / VA all exist — the US dominates
  this query).
- Each candidate has `name`, `latitude`, `longitude`, `countryCode` populated.
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
curl -fsS "https://geocoding-api.open-meteo.com/v1/search?name=Springfield&count=5"
```

Expect HTTP 200 with a `results` array of ≥ 3 entries.

## Reset state

None.

## Run

Single Bruno request.

```powershell
cd docs/api/request/AscendAI
```

```powershell
bru run "weather-mcp/geocode-springfield.yml" --env ascend-local
```

## Expected

HTTP 200. The JSON-RPC `result` content matches:

- `status` equals `"ok"`.
- `message` is `null`.
- `requestedQuery` is `null`.
- `candidates` is an array of at least 3 entries.
- The `(latitude, longitude)` tuples across the entries are all distinct.
- At least one entry has `countryCode="US"`.
- Each entry's `name` is non-empty and contains "Springfield" (case-insensitive).
- Each entry's `latitude` and `longitude` are finite numbers.
- `source` equals `"open-meteo"`.
- `fetchedAt` parses as a valid `Instant`.

## Fixtures

None.
