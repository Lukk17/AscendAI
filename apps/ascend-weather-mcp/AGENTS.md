# AGENTS.md — ascend-weather-mcp

## Project Overview

ascend-weather-mcp is a standalone MCP server built with Spring AI that provides weather data to the ascend-ai-agent via the Model Context Protocol. It uses SSE (Server-Sent Events) for communication.

## Tech Stack

- **Language**: Java 21
- **Framework**: Spring Boot 3.5.4
- **Build Tool**: Gradle (`build.gradle.kts`)
- **Key Library**: Spring AI 1.1.5 (`spring-ai-starter-mcp-server-webmvc`)
- **Docker Base**: `eclipse-temurin:21-jre-alpine`

## Build & Run Commands

```bash
# Build
./gradlew build

# Run (port 9998)
./gradlew bootRun

# Run tests
./gradlew test

# Docker
docker build -t ascend-weather-mcp:latest .
```

## Architecture

This is a Spring Boot MCP server that exposes five weather and location tools:

- **`weather_current`** — returns current observed weather (temperature, condition, wind, observation time) for a city via Open-Meteo, resolved by lat/lon or by city name with optional country code disambiguation.
- **`weather_forecast`** — returns multi-day weather forecast (1–16 days, default 7) with daily entries containing max/min temperature, precipitation, and weather code.
- **`weather_historical`** — returns historical observed weather for a specific past date (ISO format yyyy-MM-dd, within the last 80 years) with daily max/min temperature, precipitation, and weather code. Note: no e2e spec or Bruno request currently covers this tool.
- **`weather_air_quality`** — returns current air quality data (PM10, PM2.5 in µg/m³, US AQI, European AQI) for a city via Open-Meteo Air Quality API.
- **`weather_geocode`** — returns up to `limit` candidate locations (1–10, default 5) for a place name, each with resolved name, country, country code, and lat/lon.

The first four tools (weather_current, weather_forecast, weather_air_quality, weather_geocode) are covered by e2e specs and Bruno requests. weather_historical has no e2e spec or Bruno request coverage.

Communication is **SSE** (Server-Sent Events) over HTTP on port 9998. STDIO transport is disabled. Console logging is intentionally suppressed in `application.yml` to keep the SSE stream clean. Write logs to a file if you need them. Explicit tool discovery via a `ToolCallbackProvider` bean — deterministic registration rather than relying on annotation auto-discovery.

## Design Notes

- This is a reference implementation for Spring AI MCP servers
- Non-blocking, lightweight design
- No database or external service dependencies beyond the weather data source

## Code Conventions

- Standard Spring Boot patterns
- Constructor injection
- `@Tool` annotation for MCP tool definitions via Spring AI

## Relevant Skills

- `/springboot-patterns`, `/java-coding-standards`
- `/api-design`, `/docker-patterns`
