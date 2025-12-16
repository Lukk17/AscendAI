# AscendAI Orchestrator

---

This project is the central hub of the AI system, acting as an orchestrator.  
It's a Spring Boot application that provides a REST API to connect user prompts with a Large Language Model (LLM).  
Crucially, it extends the LLM's capabilities by dynamically discovering and integrating external tools via the Model Context Protocol (MCP) and providing a RAG (Retrieval-Augmented Generation) pipeline for document ingestion.

---

## Architecture Overview
The orchestrator manages the flow of information between the user, the LLM, any connected MCP tool servers, and the knowledge base.

```mermaid
graph TD
    User[User] -- "HTTP POST /prompt" --> Orchestrator
    Orchestrator -- "1. Tool Discovery" --> MCP[MCP Servers]
    Orchestrator -- "2. Check Memory/RAG" --> Qdrant[Vector Store (Qdrant)]
    Orchestrator -- "3. Send Prompt + Context" --> LLM[LLM (LM Studio)]
    
    subgraph "Ingestion Pipeline"
        MinIO[MinIO (S3)] -- "Syncs Files" --> Orchestrator
        Orchestrator -- "Route: /obsidian" --> MarkdownParser[CommonMark Parser]
        Orchestrator -- "Route: /documents" --> UnstructuredAPI[Unstructured API]
        MarkdownParser -- "Chunks & Embeds" --> Qdrant
        UnstructuredAPI -- "Chunks & Embeds" --> Qdrant
    end
```

---

## Prerequisites

Before running the application, ensure you have the following services up and running.

1.  **Docker Environment**:
    *   The project uses `docker-compose.yaml` in the root directory to spin up required services.
    *   **MinIO**: S3-compatible storage for file ingestion (Ports: 9070 API, 9071 Console).
    *   **Qdrant**: Vector database for storing embeddings.
    *   **Unstructured API**: For parsing complex document types (PDFs, PPTX, etc.).
    *   **PostgreSQL**: Metadata store for the ingestion pipeline (schema `ascend_ai`).

2.  **LLM Provider**:
    *   **LM Studio** (or similar) running locally on port `1234` (default).
    *   Ensure an embedding model is also loaded or accessible if using a separate embedding service (default config uses OpenAI format, potentially pointing to local or remote).

---

## RAG Pipeline & Document Ingestion

The orchestrator includes an automated ingestion pipeline that monitors an S3 bucket for new files.

### 1. S3 Storage (MinIO)
*   **Bucket Name**: `knowledge-base` (Created automatically on startup if missing).
*   **Access**:
    *   **Console**: http://localhost:9071
    *   **User**: `admin`
    *   **Password**: `password`
*   **Uploads**: You can upload files directly via the MinIO Console or using the AWS CLI/MinIO Client (`mc`).

### 2. File Routing & Supported Types
The pipeline routes files based on the folder specifically in the S3 bucket:

| Folder Path in S3 | Processor | Supported Formats | Description |
| :--- | :--- | :--- | :--- |
| `obsidian/` | **Markdown Flow** | `.md` | Uses a local CommonMark parser. Optimized for Obsidian vaults and markdown notes. Extracts headers as metadata. |
| `documents/` | **Unstructured Flow** | `.pdf`, `.docx`, `.pptx`, `.html`, `.txt`, etc. | Sends files to the **Unstructured API** container. Capable of performing OCR and extracting text from complex layouts. |

### 3. How it Works
1.  **Polling**: The application polls the `knowledge-base` bucket every 5 seconds.
2.  **Synchronization**: New files are downloaded to a local `downloads/` directory.
3.  **Routing**:
    *   Files containing `obsidian` in their path go to the Markdown processor.
    *   Files containing `documents` in their path go to the Unstructured processor.
4.  **Processing**:
    *   **Markdown**: Parsed into text, split into chunks.
    *   **Unstructured**: Sent to the Unstructured API, which returns extracted text, then split into chunks.
5.  **Embedding & Storage**: Text chunks are converted to vectors and stored in **Qdrant**.

---

## How to Run and Test

### 1. Start Support Services
From the project root:
```bash
docker-compose up -d
```
Ensure MinIO, Qdrant, and Unstructured API are running.

### 2. Run the Orchestrator
```bash
./gradlew bootRun
```
Access the fancy startup log to see the running port (default `9917`) and active profiles.

### 3. Test Ingestion (RAG)
1.  Open MinIO Console: http://localhost:9071
2.  Navigate to the `knowledge-base` bucket.
3.  **Test Markdown**:
    *   Create a folder `obsidian`.
    *   Upload a sample `.md` file inside it.
    *   Check application logs. You should see: `Indexed markdown document: <id>`
4.  **Test Unstructured**:
    *   Create a folder `documents`.
    *   Upload a `.pdf` or `.docx`.
    *   Check application logs. You should see: `Indexed structured document: <id>`

### 4. Test Prompt (Search)
Once documents are ingested, you can query the system.
```bash
curl -X POST http://localhost:9917/prompt \
-H "Content-Type: application/json" \
-d '{"prompt": "What information do you have about <TOPIC_IN_UPLOADED_DOC>?"}'
```

---

## Configuration

### Key Application Properties (`application.yaml`)

*   **Server Port**: `9917`
*   **S3 Configuration**:
    *   `s3.endpoint`: `http://localhost:9070`
    *   `s3.bucket`: `knowledge-base`
*   **Data Source**: Postgres connection for metadata store.
*   **Unstructured API**: Base URL for the document parsing service.

### MCP Client
*   `spring.ai.mcp.client`: Configured to manage local MCP servers (e.g., `sqlite`, `filesystem`) via `mcp-servers-config.json`.
