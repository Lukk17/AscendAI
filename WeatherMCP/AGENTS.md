# AGENTS.md — WeatherMCP

## Project Overview

WeatherMCP is a standalone MCP server built with Spring AI that provides weather data to the AscendAgent via the Model Context Protocol. It uses SSE (Server-Sent Events) for communication.

## Tech Stack

- **Language**: Java 21
- **Framework**: Spring Boot 3.5.4
- **Build Tool**: Gradle (`build.gradle.kts`)
- **Key Library**: Spring AI 1.1.4 (`spring-ai-starter-mcp-server-webmvc`)
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
docker build -t weather-mcp:latest .
```

## Architecture

This is a minimal Spring Boot MCP server with a single tool:

- **`getCurrentWeather`** — Returns current weather data for a given location
- Communication via SSE (STDIO is disabled)
- Console logging intentionally disabled to preserve STDIO integrity
- Explicit tool discovery via `ToolCallbackProvider`
- Headless operation (`spring.main.web-application-type` may be set to `none` for STDIO mode)

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
