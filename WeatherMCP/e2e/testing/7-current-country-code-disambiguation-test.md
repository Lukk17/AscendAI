# Current weather country-code disambiguation: e2e test

## What this verifies

- `weather.current` for `city="Warsaw"` with no `countryCode` returns `location.countryCode="PL"` and a latitude band
  consistent with Warsaw, Poland (~52.23°N).
- `weather.current` for the same `city="Warsaw"` with `countryCode="US"` returns `location.countryCode="US"` and a
  latitude band consistent with one of the US Warsaws (Warsaw, IN ~41.24°N; Warsaw, NY ~42.74°N; Warsaw, MO ~38.25°N
  — all in 38–43°N, distinct from PL's 52°N band).
- Both calls return `status="ok"`.
- The two responses have distinct `location.latitude` values (mathematically must differ if the dominant matches are
  different cities).
- The `temperature.value` of the two responses are independent reads — they CAN coincide by accident but the two
  geocoding lookups MUST resolve different coordinates.

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
curl -fsS "https://geocoding-api.open-meteo.com/v1/search?name=Warsaw&count=5"
```

Expect HTTP 200 with a `results` array. Visually confirm at least one result has `country_code="US"`; if open-meteo
returns only Polish matches even at `count=5`, this test cannot pass and the spec needs a different city pair.

## Reset state

Restart the WeatherMCP container to clear the in-process Caffeine geocoding cache. Without this, the second call may
hit the cached Polish result via the lowercase normalised key prefix and never re-query Open-Meteo with the US
disambiguation hint.

```powershell
docker restart weather-mcp
```

Wait for the container to be ready before continuing.

```powershell
curl -fsS http://localhost:9998/actuator/health
```

Expect HTTP 200 with `{"status":"UP"}`. Retry with a short delay if the first call returns a connection error or
`{"status":"DOWN"}`.

## Run

Two Bruno requests in sequence.

```powershell
cd docs/api/request/AscendAI
```

```powershell
bru run "weather-mcp/current-warsaw.yml" --env ascend-local
```

```powershell
bru run "weather-mcp/current-warsaw-us.yml" --env ascend-local
```

## Expected

Both calls return HTTP 200.

First call (no `countryCode`):

- `status` equals `"ok"`.
- `location.countryCode` equals `"PL"`.
- `location.latitude` is within 51.5–53.0.
- `location.longitude` is within 20.5–22.0.

Second call (`countryCode="US"`):

- `status` equals `"ok"`.
- `location.countryCode` equals `"US"`.
- `location.latitude` is within 38.0–43.0.
- `location.longitude` is within -95.0 — -75.0 (US continental).

Cross-call assertions:

- The two `location.latitude` values differ by at least 8 degrees.
- The two `location.countryCode` values are different.

## Fixtures

None.
