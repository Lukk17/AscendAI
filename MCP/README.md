# AI MCP Server

Based on:
https://github.com/spring-projects/spring-ai-examples/tree/main/model-context-protocol/mcp-annotations-server

---

This project is a standalone Model Context Protocol (MCP) server built with Spring Boot and Spring AI. 
Its purpose is to expose specific functionalities, to an external MCP-compatible orchestrator.

The server is designed for headless operation and communicates exclusively over Standard Input/Output (STDIO), 
making it a lightweight and efficient component in a larger AI system.

---

## Features

- Tool Capability: Exposes a getCurrentWeather function as a callable tool for an LLM. 
- STDIO Communication: Uses standard input/output for a direct, serverless communication channel with an orchestrator. 
- Lightweight: Runs as a non-web Spring Boot application for minimal overhead. 
- Explicit Tool Registration: Ensures reliable tool discovery through a dedicated provider configuration.

---

## How to Build

Build the project using the Gradle wrapper:

On macOS/Linux:
```
./gradlew clean bootJar
```

On Windows:
```
gradlew.bat clean bootJar
```
The build process will generate an executable JAR file in the `build/libs/` directory. 
The file will be named MCP-0.0.1.jar based on the project's group and version.

---

## How It Works
This application is not meant to be run directly by a user. It's a background process started and managed by an MCP orchestrator.

### 1. Communication Protocol
The server is configured to run as a non-web application (`web-application-type: none`). 
It uses STDIO as its transport layer. 
This means an orchestrator starts the server's JAR file as a child process 
and communicates with it by writing JSON-RPC 2.0 messages to its standard input and reading responses from its standard output.

### 2. Tool Definition (example of WeatherToolService)
The core functionality is defined in the `WeatherToolService`. 
This class contains a method, `getCurrentWeather`, which is annotated with `@Tool`. 
This annotation, provided by Spring AI, marks the method as a function that can be described to and executed by an AI model.

### 3. Explicit Tool Discovery (ToolProvider)
While Spring AI can auto-discover `@Tool` beans, this project ensures reliability by explicitly registering the tool with the application context. 
The ToolProvider configuration class creates a `ToolCallbackProvider` bean, 
which is the component responsible for listing and executing available tools. 
This manual registration guarantees that the `WeatherToolService` is always visible to the MCP server.

Of course. Here is a comprehensive README.md file for your project based on the code and configuration you provided.

AscendAI MCP Weather Server
This project is a standalone Model Context Protocol (MCP) server built with Spring Boot and Spring AI. Its purpose is to expose specific functionalities, in this case, a weather information tool, to an external MCP-compatible orchestrator.

The server is designed for headless operation and communicates exclusively over Standard Input/Output (STDIO), making it a lightweight and efficient component in a larger AI system.

---

## Features
Tool Capability: Exposes a getCurrentWeather function as a callable tool for an LLM.

STDIO Communication: Uses standard input/output for a direct, serverless communication channel with an orchestrator.

Lightweight: Runs as a non-web Spring Boot application for minimal overhead.

Explicit Tool Registration: Ensures reliable tool discovery through a dedicated provider configuration.

---


## An Important Note on Logging 📝
Console logging is intentionally disabled.

The logging.pattern.console property in application.yml is left blank. 
This is a critical design choice for STDIO-based communication.

The STDIO stream is used exclusively for the structured JSON-RPC messages between the orchestrator and this server. 
Any other text printed to the console, such as application logs, would corrupt this data stream, 
break the communication protocol, and cause the orchestrator to fail.
