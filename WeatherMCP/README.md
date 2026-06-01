# WeatherMCP

A standalone Model Context Protocol (MCP) server built with Spring Boot and Spring AI 1.1.5. It exposes a single
tool, `getCurrentWeather`, that AscendAgent (or any MCP-compatible client) can call to fetch weather data.

This is the reference implementation in this repo for "what a Spring AI MCP server looks like end to end". Small,
single-purpose, no database.

---

### Tech stack

- Java 21
- Spring Boot 3.5.4
- Spring AI 1.1.5 (`spring-ai-starter-mcp-server-webmvc`)
- Gradle ([build.gradle.kts](build.gradle.kts))

---

### How it talks to AscendAgent

The server runs as a normal Spring Boot web app on port `9998` and serves MCP over **SSE** (Server-Sent Events).
AscendAgent's MCP client subscribes at startup and discovers the `getCurrentWeather` tool automatically.

STDIO transport is intentionally disabled. Console logging is also intentionally suppressed. If you need logs, write
them to a file. This keeps the SSE stream clean and unblocks orchestrator parsing.

---

### Build

Bash:

```bash
./gradlew clean bootJar
```

PowerShell:

```powershell
.\gradlew.bat clean bootJar
```

The JAR lands in `build/libs/`. Project version lives in [build.gradle.kts](build.gradle.kts).

---

### Run

Bash:

```bash
./gradlew bootRun
```

PowerShell:

```powershell
.\gradlew.bat bootRun
```

Or via Docker. The service is wired into the main [docker-compose.yaml](../docker-compose.yaml) at the monorepo root as
`weather-mcp`. Run every compose command against the main file (no `-f` flag).

Start (or rebuild) just this service from the repo root:

```bash
docker compose up -d --build weather-mcp
```

Tail the logs:

```bash
docker logs --tail 80 -f weather-mcp
```

Force a clean recreate after a Dockerfile or env-var change:

```bash
docker compose up -d --build --force-recreate weather-mcp
```

Standalone build, when iterating outside compose:

```bash
docker build -t weather-mcp:latest .
```

Standalone run, when iterating outside compose:

```bash
docker run -d -p 9998:9998 --name weather-mcp weather-mcp:latest
```

---

### Startup readiness banner

On readiness, [config/StartupLogConfig.java](src/main/java/com/lukk/ascend/ai/mcp/weather/config/StartupLogConfig.java)
emits a single multi-line INFO log entry (ANSI Shadow `WEATHER MCP` banner, access URLs, active profile, external
dependency probes with a 2 s timeout, observability endpoints, the MCP SSE endpoint). The convention is shared with
every other long-running service in the repo. See [.agents/skills/coding-standards/SKILL.md](../.agents/skills/coding-standards/SKILL.md).

---

### How AscendAgent registers the tool

[service/WeatherToolService.java](src/main/java/com/lukk/ascend/ai/mcp/weather/service/WeatherToolService.java)
exposes `getCurrentWeather` annotated with `@Tool`. A `ToolCallbackProvider` bean in
[provider/ToolProvider.java](src/main/java/com/lukk/ascend/ai/mcp/weather/provider/ToolProvider.java) lists it
explicitly so discovery is deterministic, not implicit. AscendAgent's MCP client then sees it in the registered tools
array on startup and the LLM can call it whenever the prompt asks for live weather.

---

### Why this exists in the monorepo

It's a demonstration MCP server, not a critical service. The interesting thing is the *integration shape*: a
self-contained Spring Boot module that AscendAgent picks up over MCP without code changes on the agent side. Drop in
another `@Tool` method and AscendAgent will surface it on next restart.

For larger MCP servers (audio, web search, OCR), see [AudioScribe/](../AudioScribe/), [AscendWebSearch/](../AscendWebSearch/),
[PaddleOCR/](../PaddleOCR/).

---

### Docs map

| File                                                                                                          | What's in it                                                |
| :------------------------------------------------------------------------------------------------------------ | :---------------------------------------------------------- |
| [AGENTS.md](AGENTS.md)                                                                                        | Module-level instructions for AI coding agents.             |
| [src/main/resources/application.yaml](src/main/resources/application.yaml)                                    | Server port, MCP server config, log levels.                 |
| [src/main/java/com/lukk/ascend/ai/mcp/weather/](src/main/java/com/lukk/ascend/ai/mcp/weather/)                | Source: `McpServer`, `WeatherToolService`, `ToolProvider`.  |
| [../README.md](../README.md)                                                                                  | Monorepo overview, the architecture diagram, ports table.   |
| [../docs/architecture/README.md](../docs/architecture/README.md)                                              | Monorepo architecture, ADRs.                                |
