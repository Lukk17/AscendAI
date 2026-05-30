# Invalid input rejection: e2e test

## What this verifies

- `weather.current` with a blank `city` returns HTTP 200 and `status="invalid_input"` with `message` describing the
  blank-field failure.
- `weather.current` with a CRLF-injected `city` is rejected with `status="invalid_input"` (the regex blocks control
  characters) before any Open-Meteo call.
- `weather.current` with a non-ISO `countryCode` (`"USA"` — 3 letters, not alpha-2) is rejected with
  `status="invalid_input"`.
- In every rejection: `requestedQuery` echoes the verbatim user input; `message` is the validator's own error string
  (no echo of the offending value); `location` / `temperature` / `weatherCode` / `wind` / `observedAt` are all `null`;
  `source="open-meteo"`.
- **No Open-Meteo egress is required.** All three short-circuit inside `InputValidator` before the geocoding call.

## Prerequisites

Check Bruno CLI is installed.

```powershell
bru --version
```

Expect a version string. If the command is not found, install it with `npm install -g @usebruno/cli`.

Check the WeatherMCP server is reachable.

```powershell
curl -fsS http://localhost:9998/actuator/health
```

Expect HTTP 200 with `{"status":"UP"}`.

## Reset state

None. This test does not write persisted state and is read-only against Open-Meteo (which it should never reach).

## Run

Send three Bruno requests in sequence. Each must complete before the next begins.

```powershell
cd docs/api/request/AscendAI
```

```powershell
bru run "weather-mcp/invalid-blank-city.yml" --env ascend-local
```

```powershell
bru run "weather-mcp/invalid-crlf-city.yml" --env ascend-local
```

```powershell
bru run "weather-mcp/invalid-country-code.yml" --env ascend-local
```

## Expected

All three calls return HTTP 200.

Each response body's `result` content matches:

- `status` equals `"invalid_input"`.
- `message` is non-empty and does NOT contain the offending user-supplied value (validator returns fixed-shape error
  strings).
- `requestedQuery` equals the exact value the caller sent (`"   "` / `"Warsaw\r\nignore previous"` / `"Warsaw"`
  respectively for the three calls — for the `countryCode` test the `requestedQuery` is still the city, since the
  country code is a separate field that the validator rejects before the city flows downstream).
- `location` is `null`.
- `temperature` is `null`.
- `weatherCode` is `null`.
- `wind` is `null`.
- `observedAt` is `null`.
- `source` equals `"open-meteo"`.
- `fetchedAt` is a valid ISO-8601 instant.

No outbound HTTPS request to `*.open-meteo.com` is made — this is an internal property the spec does not directly
assert (since the runner is black-box), but a steady-state run takes < 50 ms per call. A duration > 500 ms suggests
the validator was bypassed and Open-Meteo was actually called; investigate before declaring PASS.

## Fixtures

None.
