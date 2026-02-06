# AscendWebSearch

AscendWebSearch is a powerful web search and extraction service for the AscendAI ecosystem. It integrates **SearXNG** for meta-search capabilities and combines **Trafilatura** with **Playwright** for robust content extraction (reading).

---

## Table of Contents

*   [API Documentation](#api-documentation)
*   [Prerequisites](#prerequisites)
*   [Configuration (Environment Variables)](#configuration-environment-variables)
*   [Running the Service](#running-the-service)
    *   [Standard Python App](#running-as-a-standard-python-app-without-docker)
    *   [Docker](#running-with-docker-recommended)
*   [MCP Server Mode](#mcp-server-mode)
*   [REST API Examples](#rest-api-examples)
*   [How it Works (Extraction Strategy)](#how-it-works-extraction-strategy)

---

## API Documentation

*   **Swagger UI**: [http://localhost:7021/docs](http://localhost:7021/docs)
*   **Redoc**: [http://localhost:7021/redoc](http://localhost:7021/redoc)

---

## Prerequisites

*   **Python 3.12**
*   **SearXNG Instance** (Running on port 8080 or accessible via URL)
*   **Playwright Browsers** (If running locally)

---

## Configuration (Environment Variables)

*   `SEARXNG_BASE_URL`: **(Required)** URL of the SearXNG instance. Default: `http://searxng:8080` (Docker) or `http://localhost:9020` (Local).
*   `API_PORT`: **(Optional)** Port to run the server on. Default: `7021`.
*   `API_HOST`: **(Optional)** Host to bind to. Default: `0.0.0.0`.
*   `LOG_LEVEL`: **(Optional)** Logging level. Default: `INFO`.

---

## Running the Service

### Running as a standard Python App (without Docker)

1.  **Create virtual environment**

    Linux/MacOS:
    ```shell
    python3 -m venv .venv
    ```

    Windows:
    ```powershell
    python -m venv .venv
    ```

2.  **Activate virtual environment**

    Linux/MacOS:
    ```shell
    source .venv/bin/activate
    ```

    Windows:
    ```powershell
    .\.venv\Scripts\activate
    ```

3.  **Install dependencies**

    ```shell
    pip install -e .[dev]
    ```

4.  **Install Playwright Browsers**

    ```shell
    playwright install --with-deps chromium
    ```

5.  **Run the Server**

    Ensure `SEARXNG_BASE_URL` is set (e.g., `http://localhost:9020` if using Docker mapping).

    *Exporting variables:*

    Linux/MacOS:
    ```shell
    export SEARXNG_BASE_URL="http://localhost:9020"
    export LOG_LEVEL="INFO"
    ```

    ```shell
    python src/main.py
    ```

    Windows:
    ```powershell
    $env:SEARXNG_BASE_URL="http://localhost:9020"
    $env:LOG_LEVEL="INFO"
    ```

    ```powershell
    python src/main.py
    ```

### Running with Docker (Recommended)

1.  **Build the Image**

    ```shell
    docker build -t ascend-web-search:latest .
    ```

2.  **Run the Container**

    Linux/MacOS:
    ```shell
    docker run -d \
      --name ascend-web-search \
      -p 7021:7021 \
      -e SEARXNG_BASE_URL="http://host.docker.internal:9020" \
      ascend-web-search:latest
    ```

    Windows:
    ```powershell
    docker run -d `
      --name ascend-web-search `
      -p 7021:7021 `
      -e SEARXNG_BASE_URL="http://host.docker.internal:9020" `
      ascend-web-search:latest
    ```

    *Note: If running in the same Docker Compose network, use `http://searxng:8080` instead of `host.docker.internal`.*

---

## MCP Server Mode

The service exposes an MCP server over HTTP at `/mcp`.

### Tool Configuration

```json
{
  "mcpServers": {
    "ascend-web-search": {
      "type": "sse",
      "url": "http://localhost:7021/mcp"
    }
  }
}
```

### Available Tools

*   `web_search(query, limit)`: Search the web.
*   `web_read(url)`: Extract content from a URL.

---

## REST API Examples

### Health Check

Linux/MacOS:
```shell
curl -X GET http://localhost:7021/health
```

Windows:
```powershell
curl -X GET http://localhost:7021/health
```

### Standard REST API

#### 1. Web Search
**GET** `/api/v1/web/search`

```shell
curl "http://localhost:7021/api/v1/web/search?query=AscendAI&limit=3"
```

#### 2. Web Read
**GET** `/api/v1/web/read`

```shell
curl "http://localhost:7021/api/v1/web/read?url=https://example.com"
```

### Call MCP Tool (POST)

#### 1. Web Search (`web_search`)

**Linux/MacOS**:
```shell
curl -X POST http://localhost:7021/mcp \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/call",
    "params": {
      "name": "web_search",
      "arguments": {
        "query": "AscendAI",
        "limit": 1
      }
    },
    "id": 1
  }'
```

**Windows**:
```powershell
curl -X POST http://localhost:7021/mcp `
  -H "Content-Type: application/json" `
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/call",
    "params": {
      "name": "web_search",
      "arguments": {
        "query": "AscendAI",
        "limit": 1
      }
    },
    "id": 1
  }'
```

#### 2. Web Read (`web_read`)

**Linux/MacOS**:
```shell
curl -X POST http://localhost:7021/mcp \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/call",
    "params": {
      "name": "web_read",
      "arguments": {
        "url": "https://example.com"
      }
    },
    "id": 2
  }'
```

**Windows**:
```powershell
curl -X POST http://localhost:7021/mcp `
  -H "Content-Type: application/json" `
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/call",
    "params": {
      "name": "web_read",
      "arguments": {
        "url": "https://example.com"
      }
    },
    "id": 2
  }'
```

---

## How it Works (Extraction Strategy)

The `web_read` tool uses a smart fallback strategy to ensure high success rates while maintaining speed:

1.  **Fast Path**: Attempts to fetch the URL using standard HTTP GET and extract content with `trafilatura`. This is fast and resource-efficient.
2.  **Render Path**: If the fast path fails (e.g., 403 Forbidden, 429 Too Many Requests, or empty content due to JavaScript), it switches to **Playwright**. It launches a headless Chromium browser, renders the page (executing JS), and then extracts the content.
