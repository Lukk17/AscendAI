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
*   [How it Works (Extraction Strategy)](#how-it-works-extraction-strategy)

---

## API Documentation

*   **Swagger UI**: [http://localhost:7021/docs](http://localhost:7021/docs)
*   **Redoc**: [http://localhost:7021/redoc](http://localhost:7021/redoc)

---

## Prerequisites

*   **Python 3.11**
*   **SearXNG Instance** (Running on port 8080 or accessible via URL)
*   **Playwright Browsers** (If running locally)

---

## Configuration (Environment Variables)

*   `SEARXNG_BASE_URL`: **(Required)** URL of the SearXNG instance. Default: `http://searxng:8080`.
*   `API_PORT`: **(Optional)** Port to run the server on. Default: `7021`.
*   `API_HOST`: **(Optional)** Host to bind to. Default: `0.0.0.0`.
*   `LOG_LEVEL`: **(Optional)** Logging level. Default: `INFO`.

---

## Running the Service

### Running as a standard Python App (without Docker)

1.  **Install Dependencies:**
    
    ```shell
    python -m venv .venv
    source .venv/bin/activate
    pip install .
    ```

2.  **Install Playwright Browsers:**
    
    ```shell
    playwright install chromium
    ```

3.  **Run the Server:**
    
    ```shell
    # Ensure SearXNG is running
    export SEARXNG_BASE_URL="http://localhost:8080" # Example
    
    python src/main.py
    ```

### Running with Docker (Recommended)

1.  **Build the Image:**
    
    ```shell
    docker build -t ascend-web-search:latest .
    ```

2.  **Run the Container:**
    
    ```shell
    docker run -d \
      --name ascend-web-search \
      -p 7021:7021 \
      -e SEARXNG_BASE_URL="http://searxng:8080" \
      ascend-web-search:latest
    ```

---

## MCP Server Mode

The service exposes an MCP server over SSE at `/mcp`.

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

## How it Works (Extraction Strategy)

The `web_read` tool uses a smart fallback strategy to ensure high success rates while maintaining speed:

1.  **Fast Path**: Attempts to fetch the URL using standard HTTP GET and extract content with `trafilatura`. This is fast and resource-efficient.
2.  **Render Path**: If the fast path fails (e.g., 403 Forbidden, 429 Too Many Requests, or empty content due to JavaScript), it switches to **Playwright**. It launches a headless Chromium browser, renders the page (executing JS), and then extracts the content.
