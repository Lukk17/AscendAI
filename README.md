# AscendAI

This repository contains a multi-module AI orchestration platform built with Spring AI and the Model Context Protocol (MCP). It routes user prompts to multiple AI providers (LM Studio, OpenAI, Gemini, Anthropic, MiniMax) with per-request selection, extends LLM capabilities with external tools, and provides a RAG pipeline with semantic memory.

---

## 🏗️ System Architecture

📐 **[Full Architecture Documentation](docs/architecture/arc42/01-introduction-and-goals.md)** — arc42, ADRs, and C4 Mermaid diagrams.

*   **Orchestrator**: Spring Boot application — REST API, multi-provider AI, RAG pipeline, MCP tool integration.
*   **AudioScribe**: MCP server for audio transcription (FastMCP/Python).
*   **WeatherMCP**: MCP server for weather data (Spring Boot/Java).
*   **AscendWebSearch**: MCP server for web search via SearXNG (FastMCP/Python).
*   **AscendMemory**: Semantic memory service with REST API (FastAPI/Python).
*   **Support Services** (Dockerized):
    *   **MinIO**: S3-compatible object storage for document ingestion.
    *   **Qdrant**: Vector database for RAG embeddings and semantic memory.
    *   **Redis**: Chat history cache.
    *   **SearXNG**: Privacy-respecting meta search engine.
    *   **FlareSolverr**: Cloudflare bypass proxy for web scraping.
*   **PostgreSQL**: Persistent metadata and chat history (local or Docker).

---

## 🚀 Getting Started

### Prerequisites

*   **Docker Desktop** (running)
*   **Java 21**
*   **PostgreSQL** (Active instance on port 5432)

### 1. Start Infrastructure

Run the following command at the project root to start MinIO, Qdrant, Unstructured API, and OpenMemory:

```bash
docker-compose up -d
```

### 2. Configure Database

Ensure your local PostgreSQL has a database named `ascend_ai`. The application is configured to connect with the following default credentials (update `Orchestrator/src/main/resources/application.yaml` if yours differ):
*   **User**: `postgres`
*   **Password**: `local`
*   **Database**: `ascend_ai`

### 3. Run the Orchestrator

Navigate to the `Orchestrator` directory and run the application:

```bash
cd Orchestrator
./gradlew bootRun
```

The application will automatically:
*   Connect to MinIO.
*   Create the `knowledge-base` bucket if it doesn't exist.
*   Initialize the necessary database tables (`INT_METADATA_STORE`, etc.).

---

## 🌐 HTTP Orchestrator API

### 1. Extract Web Payload (`v2`)
The `/api/v2/web/read` endpoint accepts a `POST` request with an explicit JSON payload. This is required because complex target URLs containing parameters (e.g., `?login=true&auth=1`) get natively stripped by standard HTTP `GET` query parsing. 

```bash
curl -X POST http://localhost:7021/api/v2/web/read \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://secure.indeed.com/auth?continue=http://www.indeed.com/jobs...&from=page-two-signin",
    "include_links": true,
    "heavy_mode": true
  }'
```

---

## ⚙️ Configuration & Ports

| Service | Port | Default Credentials | Description |
| :--- | :--- | :--- | :--- |
| **Orchestrator** | `9917` | - | Main API Gateway |
| **AudioScribe** | `7017` | - | MCP — Audio Transcription |
| **WeatherMCP** | `9998` | - | MCP — Weather Data |
| **AscendWebSearch** | `7021` | - | MCP — Web Search |
| **AscendMemory** | `7020` | - | REST — Semantic Memory |
| **MinIO API** | `9070` | `admin` / `password` | S3 API Endpoint |
| **MinIO Console** | `9071` | `admin` / `password` | Web UI for File Management |
| **Qdrant** | `6333` / `6334` | - | Vector Database (HTTP/gRPC) |
| **Redis** | `6379` | - | Cache |
| **SearXNG** | `8088` | - | Meta Search Engine |
| **FlareSolverr** | `8191` | - | Cloudflare Bypass |
| **PostgreSQL** | `5432` | `postgres` / `local` | Metadata Storage |

### 3. Publish (Push)
Log in to Docker Hub if you haven't already:
```bash
docker login
```

Push the tagged images:
```bash
docker push lukk17/ascend-ai:v1.0.0
docker push lukk17/ascend-ai:latest
```

---


---

## � Data and Persistence

Docker uses a **named volume** (`minio_data`) to persist your MinIO data (buckets and files). This ensures that even if you remove the container, your data remains safe.
*   **Location**: Managed by Docker (usually in `/var/lib/docker/volumes/...`).
*   **Management**: Use `docker volume ls` and `docker volume inspect minio_data` to view details.

---

## �📄 Adding Documents for RAG

To add documents (Markdown, PDF, DOCX) to your RAG pipeline, you need to upload them to the `knowledge-base` bucket in MinIO.

### Option 1: MinIO Console (Web UI)
1.  Open [http://localhost:9071](http://localhost:9071).
2.  Login with default credentials: `admin` / `password`.
3.  Click on **Buckets** in the left menu.
4.  Select `knowledge-base`.
    *   *If it doesn't exist, the Orchestrator will create it on startup, or you can create it manually.*
5.  Click **Object Browser** -> **Upload**.
6.  Select your file(s) or folder(s).
    *   **Markdown**: Files with `.md` (best if from Obsidian).
    *   **Documents**: PDFs, DOCX, etc. (processed via Unstructured API).

### Option 2: CLI (curl) via Orchestrator
You can directly upload files using the Orchestrator's API, which will automatically route them to the correct folder (`obsidian/` or `documents/`):

```bash
# Example: Uploading a Markdown file
curl -X POST -F "file=@width_test.md" http://localhost:9917/api/ingestion/upload
```
*Note: Make sure the file exists in your current directory.*

---

## 🔧 Troubleshooting

### 1. MinIO: "Bucket already exists" or "Access Denied" errors

If you need to completely reset the MinIO state or delete a bucket that is stuck, you **cannot** use the Web UI in recent versions. You must use the command line inside the Docker container.

**How to force delete a bucket via Docker:**

1.  Open a terminal.
2.  Execute the following command to verify the running container name (usually `minio`):
    ```bash
    docker ps
    ```
3.  Exec into the MinIO container (or use Docker Desktop's "Exec" terminal):
    ```bash
    docker exec -it minio /bin/sh
    ```
4.  **Configure the `mc` client** (this aliases 'local' to your server):
    ```bash
    mc alias set local http://localhost:9000 admin password
    ```
5.  **Force delete the bucket**:
    ```bash
    mc rb --force local/knowledge-base
    ```

### 2. Qdrant: Managing Vector Data

The Orchestrator uses a Qdrant collection named `ascendai` (configured in `application.yaml`).

**Delete Entire Collection (Reset Memory):**
To completely wipe all vector data:
```bash
curl -X DELETE "http://localhost:6333/collections/ascendai"
```

**Granular Deletion (Remove Specific File):**
To remove only the vectors associated with a specific file (e.g., `kierunki.md`):
```bash
curl -X POST "http://localhost:6333/collections/ascendai/points/delete" \
     -H "Content-Type: application/json" \
     -d '{
       "filter": {
         "must": [
           { "key": "metadata.source", "match": { "value": "kierunki.md" } }
         ]
       }
     }'
```

**List All Collections:**
To view all existing collections:
```bash
curl http://localhost:6333/collections
```

**Visualizing Data (Qdrant Dashboard):**
The Qdrant image includes a **Built-in Dashboard**.
*   **URL**: [http://localhost:6333/dashboard](http://localhost:6333/dashboard)
*   You can browse collections, view stored vectors, and verify data ingestion visually without needing extra containers.

### 3. Resetting Ingestion History (PostgreSQL)

To force the system to re-process files, you must remove their entries from the metadata store.

**Database Details:**
*   **Database**: `ascend_ai`
*   **Schema**: `public`
*   **Table**: `int_metadata_store`

**Option A: Clear History for a Single File (Granular)**
If you want to re-ingest a specific file (e.g., `test.md`):
```sql
DELETE FROM public.int_metadata_store 
WHERE metadata_key LIKE '%test.md' 
   OR metadata_key LIKE '%test.md'; 
```
*(Note: Keys often include prefixes like `s3-metadata` or `local-fs-metadata`)*

**Option B: Clear ALL History (Full Reset)**
To force the system to re-process **everything**:
```sql
TRUNCATE TABLE public.int_metadata_store;
```

**After running either command, restart the Orchestrator.**