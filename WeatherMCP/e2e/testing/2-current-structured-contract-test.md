# Current weather structured contract: e2e test

## What this verifies

- `tools/list` advertises a tool named `weather.current` with the documented parameter schema (`city` required;
  `countryCode`, `unit`, `language` optional).
- `weather.current` for Warsaw (no `countryCode`, default `unit`, default `language`) returns HTTP 200 and the
  JSON-RPC `result` content has `status="ok"`.
- The `location` object contains `name`, `country`, `countryCode`, numeric `latitude`, numeric `longitude`. Country
  code is `"PL"` (Poland is the dominant geocoding match for "Warsaw").
- `temperature.value` is a finite number; `temperature.unit` equals `"celsius"` (the default when the caller does
  not pass `unit`).
- `wind.speed` is numeric; `wind.unit` equals `"km/h"`.
- `weatherCode` is an integer.
- `observedAt` is a non-empty string (Open-Meteo ISO-local-datetime).
- `source` equals `"open-meteo"`; `fetchedAt` is a valid ISO-8601 instant.
- `requestedQuery` is `null` on the OK path.

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

Check outbound HTTPS to Open-Meteo works from this host.

```powershell
curl -fsS "https://geocoding-api.open-meteo.com/v1/search?name=Berlin&count=1"
```

Expect HTTP 200 with a `results` array.

## Reset state

None. The first call may hit a warm cache; that's fine because this test asserts shape, not freshness.

## Run

Two Bruno requests in sequence.

```powershell
cd docs/api/request/AscendAI
```

**Step 1.** Open an MCP session via the `initialize` handshake. Capture the `Mcp-Session-Id` value from the response headers.

```powershell
curl.exe -fsS -i -X POST http://localhost:9998/mcp -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"initialize\",\"params\":{\"protocolVersion\":\"2025-11-25\",\"capabilities\":{},\"clientInfo\":{\"name\":\"e2e\",\"version\":\"0.1.0\"}}}"
```

Look for `Mcp-Session-Id: <uuid>` in the response. Use that UUID as the value of the `mcp_session_id` env-var in the next step(s).

**Step 2.** Send the tool call(s) with the captured session ID injected:

```powershell
bru run "weather-mcp/list-tools.yml" --env ascend-local --env-var "mcp_session_id=<paste UUID from step 1>"
```

```powershell
bru run "weather-mcp/current-warsaw.yml" --env ascend-local --env-var "mcp_session_id=<paste UUID from step 1>"
```

## Expected

`list-tools.yml` returns HTTP 200. The JSON-RPC `result.tools` array contains an entry with `name="weather.current"`.
That entry's `inputSchema.properties` advertises `city` (required), `countryCode`, `unit`, `language`.

`current-warsaw.yml` returns HTTP 200. The JSON-RPC `result` content matches:

- `status` equals `"ok"`.
- `message` is `null`.
- `requestedQuery` is `null`.
- `location.name` is non-empty and contains "Warsaw" (case-insensitive).
- `location.countryCode` equals `"PL"`.
- `location.latitude` is numeric and within 51.5–53.0 (Warsaw, PL band).
- `location.longitude` is numeric and within 20.5–22.0.
- `temperature.value` is a finite number.
- `temperature.unit` equals `"celsius"`.
- `weatherCode` is an integer in 0–99 (WMO code range).
- `wind.speed` is a non-null number ≥ 0.
- `wind.unit` equals `"km/h"`.
- `observedAt` is a non-empty string.
- `source` equals `"open-meteo"`.
- `fetchedAt` parses as a valid `Instant`.

## Fixtures

None.
