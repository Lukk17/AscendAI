# WeatherMCP

---

A standalone Model Context Protocol (MCP) server built with Spring Boot and Spring AI 1.1.4. It exposes a single tool, `getCurrentWeather`, that AscendAgent (or any MCP-compatible client) can call to fetch weather data.

It's the reference implementation in this repo for "what a Spring AI MCP server looks like end to end" — small, single-purpose, no database.

---

## Tech stack

- Java 21
- Spring Boot 3.5.4
- Spring AI 1.1.4 (`spring-ai-starter-mcp-server-webmvc`)
- Gradle (`build.gradle.kts`)

---

## How it talks to AscendAgent

The server runs as a normal Spring Boot web app on port `9998` and serves MCP over **SSE** (Server-Sent Events). AscendAgent's MCP client subscribes at startup and discovers the `getCurrentWeather` tool automatically.

STDIO transport is intentionally disabled. Console logging is also intentionally suppressed — if you need logs, write them to a file. This keeps the SSE stream clean and unblocks orchestrator parsing.

---

## Build

Bash:

```bash
./gradlew clean bootJar
```

PowerShell:

```powershell
.\gradlew.bat clean bootJar
```

The JAR lands in `build/libs/`. Project version is in `build.gradle.kts`.

---

## Run

Bash:

```bash
./gradlew bootRun
```

PowerShell:

```powershell
.\gradlew.bat bootRun
```

Or via Docker (in the monorepo this is wired into `docker-compose.yaml`):

Bash:

```bash
docker build -t weather-mcp:latest .
```

```bash
docker run -d -p 9998:9998 --name weather-mcp weather-mcp:latest
```

PowerShell:

```powershell
docker build -t weather-mcp:latest .
```

```powershell
docker run -d -p 9998:9998 --name weather-mcp weather-mcp:latest
```

---

## How AscendAgent registers the tool

`WeatherToolService` exposes `getCurrentWeather` annotated with `@Tool`. A `ToolCallbackProvider` bean lists it explicitly so discovery is deterministic, not implicit. AscendAgent's MCP client then sees it in the registered tools array on startup and the LLM can call it whenever the prompt asks for live weather.

---

## Why this exists in the monorepo

It's a demonstration MCP server, not a critical service. The interesting thing is the *integration shape*: a self-contained Spring Boot module that AscendAgent picks up over MCP without code changes on the agent side. Drop in another `@Tool` method and AscendAgent will surface it on next restart.

For larger MCP servers (audio, web search, OCR), see `AudioScribe/`, `AscendWebSearch/`, `PaddleOCR/`.
