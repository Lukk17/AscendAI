# AscendAI

This repository contains a multi-module project demonstrating a complete RAG (Retrieval-Augmented Generation) system using Spring AI's Model Context Protocol (MCP). It extends the capabilities of a Large Language Model (LLM) with external tools and a memory-rich context window.

The system is composed of an Orchestrator (Spring Boot), an MCP Tool Server, and a suite of Dockerized support services for vector storage, object storage, and document processing.

---

## 🏗️ System Architecture

*   **Orchestrator**: The main Spring Boot application that handles user requests, manages the RAG pipeline, and communicates with the LLM.
*   **MCP Server**: Provides external tools to the LLM via the Model Context Protocol.
*   **OpenMemory**: A personalized memory service powered by Qdrant.
*   **Support Services** (Dockerized):
    *   **MinIO**: S3-compatible object storage for document ingestion (`knowledge-base` bucket).
    *   **Unstructured API**: Processes complex document formats (PDF, DOCX) into text.
    *   **Qdrant**: Vector database for storing document embeddings and memory.
*   **PostgreSQL**: Stores metadata for the ingestion pipeline (running locally or via Docker).

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

## ⚙️ Configuration & Ports

| Service | Port | Default Credentials | Description |
| :--- | :--- | :--- | :--- |
| **Orchestrator** | `9917` | - | Main Application API |
| **MinIO API** | `9070` | `admin` / `password` | S3 API Endpoint |
| **MinIO Console** | `9071` | `admin` / `password` | Web UI for File Management |
| **Unstructured API** | `9080` | - | Text Extraction Service |
| **Qdrant** | `6333` | - | Vector Database |
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

## 🏗️ Managing Custom Service Images (Advanced)

The project also builds a custom image for the `openmemory` service (defined in `OpenMemory/Dockerfile.mem0mcp`). If you want to version and publish this image to your own Docker Hub:

### 1. Build the OpenMemory Image
```bash
docker build -t openmemory-ascend-ai:latest -f OpenMemory/Dockerfile.mem0mcp OpenMemory
```

### 2. Tag and Push
```bash
# Tag with your username and a version
docker tag openmemory-ascend-ai:latest lukk17/openmemory-ascend-ai:v0.0.1

# Push
docker push lukk17/openmemory-ascend-ai:v0.0.1
```


### 3. Update docker-compose.yaml
To use your published image instead of building locally, update `docker-compose.yaml`:

```yaml
  openmemory:
    image: lukk17/openmemory-ascend-ai:v0.0.1
    # build: ...  <-- Comment out or remove the build section
```

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