# AscendAI Orchestrator

---

This project is the central hub of the AI system, acting as an orchestrator.  
It's a Spring Boot application that provides a REST API to connect user prompts with a Large Language Model (LLM).  
It extends the LLM's capabilities by integrating external tools via the Model Context Protocol (MCP), a retrieval-gated RAG pipeline (Qdrant), and a dedicated semantic memory service (`ascend-memory`).

---

## Architecture Overview

The orchestrator manages the flow of information between the user, the LLM, persistent storage, and external tools.

```mermaid
flowchart TD
    User["User"] -- "HTTP POST /prompt" --> Orchestrator["Orchestrator"]
    
    subgraph Core ["Core Orchestration"]
        Orchestrator -- "1. Context Retrieval" --> Redis["Redis (Active Memory)"]
        Orchestrator -- "2. History Lookup" --> Postgres["PostgreSQL (Long-term)"]
        Orchestrator -- "3. Soft-RAG (Thresholded)" --> Qdrant["Qdrant (RAG)"]
        Orchestrator -- "4. Semantic Memory (REST)" --> AscendMemory["ascend-memory"]
    end
    
    subgraph MCP ["Model Context Protocol (MCP)"]
        Orchestrator -- "Tool Discovery & Calls" --> ExtTools["External Tools"]
        ExtTools --> Weather["Weather MCP"]
        ExtTools --> Audio["AudioScribe MCP"]
        ExtTools --> WebTools["Web Tools MCP"]
        WebTools --> Searxng["SearXNG"]
    end

    subgraph Ingestion ["Ingestion Pipeline"]
        MinIO["MinIO (S3)"] -- "Syncs Files" --> Orchestrator
        Orchestrator -- "Route: /obsidian" --> MarkdownParser["CommonMark Parser"]
        Orchestrator -- "Route: /documents" --> UnstructuredAPI["Unstructured API"]
        MarkdownParser -- "Chunks & Embeds" --> Qdrant
        UnstructuredAPI -- "Chunks & Embeds" --> Qdrant
    end
    
    Orchestrator -- "Final Prompt" --> LLM["LLM (LM Studio)"]
```

### Core Components
1.  **Redis**:
    *   **Purpose**: High-performance caching and "Active Memory".
    *   **Usage**: Stores short-term conversation context, user instructions, and cached embedding results to reduce latency.
2.  **PostgreSQL**:
    *   **Purpose**: Persistent, reliable storage.
    *   **Usage**: Archival of all Chat History and structured User Metadata (preferences, profile data).
3.  **Qdrant**:
    *   **Purpose**: Vector Database for RAG.
    *   **Usage**: Stores semantic embeddings of ingested documents (Markdown, PDF, etc.) for similarity search.
4.  **ascend-memory**:
    *   **Purpose**: Semantic memory service (separate from chat history).
    *   **Usage**: Orchestrator retrieves user-scoped memories over REST and injects them as optional context.

---

## Operational Workflow

### 1. Memory vs. Tools
The Orchestrator uses a retrieval-gated approach:
*   **Soft-RAG (Thresholded)**: It always queries Qdrant, but injects RAG context only if the top similarity score is above a configured threshold. This prevents context-only refusals and avoids suppressing tool usage.
*   **Tools (MCP)**: Tools remain available for dynamic/external information (weather, web search, transcription).
*   **Semantic Memory (REST)**: User-scoped memories are retrieved from `ascend-memory` and injected as optional context.

#### Optional upgrade: Model Router (1 extra LLM call)
For a larger tool set and ambiguous prompts, you can add a model-router step that returns JSON like `{route: RAG|TOOL|BOTH}` and drives retrieval/tooling explicitly.

### 2. Document & Image Ingestion
*   **Direct Ingestion**: Users can upload images or documents directly in the `/prompt` request (`multipart/form-data`). These are processed on-the-fly (`On-Demand Ingestion`) and added to the temporary context window for the current reply.
*   **Background Ingestion (S3)**:
    *   The system monitors a **MinIO S3 Bucket (`knowledge-base`)**.
    *   **Manual**: Ingestion is disabled by default to avoid startup latency and unexpected cloud embedding costs. Trigger ingestion explicitly via the REST endpoint.

---

## Model Selection & Justification

### LLM: `meta-llama-3.1-8b-instruct`
*   **Why**: We prioritize reliability and instruction following over raw creative power for the Orchestrator.
*   **Issue with Qwen**: While powerful, Qwen models occasionally output non-standard tokens or struggle with the strict tool-calling format required by our MCP implementation, leading to parsing errors.
*   **Llama 3.1**: Provides a balanced trade-off—excellent tool use coherence, robust instruction following, and decent reasoning capabilities for an 8B model.

### Embeddings: `text-embedding-nomic-embed-text-v2-moe`
*   **Why**:
    *   **Matryoshka Representation**: Allows flexible embedding sizes.
    *   **Multilingual Support**: Crucial for our use case (Polish/English mixing). The `v2` version specifically handles non-English contexts significantly better than `v1.5` or standard BERT models.

---

## Prerequisites

Before running the application, ensure you have the following services up and running.

1.  **Docker Environment**:
    *   The project uses `docker-compose.yaml` in the root directory to spin up required services.
    *   **MinIO**: S3-compatible storage for file ingestion (Ports: 9070 API, 9071 Console).
    *   **Qdrant**: Vector database for storing embeddings.
    *   **Unstructured API**: For parsing complex document types (PDFs, PPTX, etc.).
    *   **PostgreSQL**: Metadata store for the ingestion pipeline (schema `ascend_ai`).
    *   **Redis**: Caching and active memory store.
    *   **SearXNG**: Self-hosted meta-search engine (Web Tools dependency).
    *   **web-tools-mcp**: MCP server providing `web_search` and `read_url` tools.
    *   **ascend-memory**: Semantic memory service used by Orchestrator over REST.

2.  **LLM Provider**:
    *   **LM Studio** (or similar) running locally on port `1234` (default).
    *   Ensure an embedding model is also loaded or accessible if using a separate embedding service (default config uses OpenAI format, potentially pointing to local or remote).

---

## RAG Pipeline & Document Ingestion

The orchestrator includes an ingestion pipeline for processing S3 bucket files on demand.

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
1.  **Trigger**: Call `POST /api/ingestion/run` to scan the `knowledge-base` bucket.
2.  **Routing**:
    *   Files containing `obsidian` in their path go to the Markdown processor.
    *   Files containing `documents` in their path go to the Unstructured processor.
3.  **Processing**:
    *   **Markdown**: Parsed into text, split into chunks.
    *   **Unstructured**: Sent to the Unstructured API, which returns extracted text, then split into chunks.
4.  **Embedding & Storage**: Text chunks are converted to vectors and stored in **Qdrant**.

Auto ingestion is available but disabled by default. Enable it with `app.ingestion.auto.enabled=true`.

---

## How to Run and Test

### 1. Start Support Services
From the project root:
```bash
docker-compose up -d
```
Ensure MinIO, Qdrant, Redis, Postgres, Unstructured API, SearXNG, `ascend-memory`, and `web-tools-mcp` are running.

### 2. Run the Orchestrator
```bash
./gradlew bootRun
```
Access the fancy startup log to see the running port (default `9917`) and active profiles.
It will also display:
*   Postgres & Redis Connection Status.
*   Count of available files in S3 (`knowledge-base`) ready for ingestion.
*   List of active MCP Tools.

### 3. Test Ingestion (RAG)
1.  Open MinIO Console: http://localhost:9071
2.  Navigate to the `knowledge-base` bucket.
3.  **Test Markdown**:
    *   Create a folder `obsidian`.
    *   Upload a sample `.md` file inside it.
    *   Trigger ingestion: `POST http://localhost:9917/api/ingestion/run`
    *   Check application logs. You should see: `Indexed markdown document: <id>`
4.  **Test Unstructured**:
    *   Create a folder `documents`.
    *   Upload a `.pdf` or `.docx`.
    *   Trigger ingestion: `POST http://localhost:9917/api/ingestion/run`
    *   Check application logs. You should see: `Indexed unstructured document: <id>`

### 4. Testing Scenarios (CURL)

**Prerequisites**:
- Server running on `localhost:9917`.
- `X-User-Id` header is required for context.

#### 1. RAG: Summarizing a Document

**Windows (PowerShell)**:
```powershell
curl -X POST "http://localhost:9917/prompt" `
     -H "X-User-Id: user1" `
     -H "Content-Type: multipart/form-data" `
     -F "prompt=Summarize the key points." `
     -F "doc=@notes.md"
```

**Linux/Mac (Bash)**:
```bash
curl -X POST "http://localhost:9917/prompt" \
     -H "X-User-Id: user1" \
     -H "Content-Type: multipart/form-data" \
     -F "prompt=Summarize the key points." \
     -F "doc=@notes.md"
```

#### 2. Vision: Describing a Picture

**Windows (PowerShell)**:
```powershell
curl -X POST "http://localhost:9917/prompt" `
     -H "X-User-Id: user1" `
     -H "Content-Type: multipart/form-data" `
     -F "prompt=Describe this image." `
     -F "image=@screenshot.png"
```

**Linux/Mac (Bash)**:
```bash
curl -X POST "http://localhost:9917/prompt" \
     -H "X-User-Id: user1" \
     -H "Content-Type: multipart/form-data" \
     -F "prompt=Describe this image." \
     -F "image=@screenshot.png"
```

#### 3. MCP Tool Usage (Weather)

**Windows (PowerShell)**:
```powershell
curl -X POST "http://localhost:9917/prompt" `
     -H "X-User-Id: user1" `
     -H "Content-Type: multipart/form-data" `
     -F "prompt=What is the weather in Warsaw?"
```

#### 4. Memory Context

**Set Context (Bash)**:
```bash
curl -X POST "http://localhost:9917/prompt" \
     -H "X-User-Id: user1" \
     -H "Content-Type: multipart/form-data" \
     -F "prompt=My name is Luke."
```

**Retrieve Context (Bash)**:
```bash
curl -X POST "http://localhost:9917/prompt" \
     -H "X-User-Id: user1" \
     -H "Content-Type: multipart/form-data" \
     -F "prompt=What is my name?"
```

### 5. Verify Persistence & Memory

#### 1. Redis (Chat History & Instructions)

**Connect to Redis**:
```bash
docker exec -it orchestrator-redis-1 redis-cli
```

**Check Keys**:
All keys:
```bash
KEYS *
```
Specific keys:
```bash
KEYS "user:user1:*"
```

**View History**:
```bash
LRANGE user:user1:history 0 -1
```

**View Instructions**:
```bash
GET user:user1:instructions
```

#### 2. PostgreSQL (Long-term Storage)

**Connect to Database**:
```bash
docker exec -it orchestrator-postgres-1 psql -U postgres -d orchestrator_db
```

**Check History**:
```sql
SELECT * FROM chat_history WHERE user_id = 'user1' ORDER BY created_at DESC LIMIT 5;
```

**Check Instructions**:
```sql
SELECT * FROM user_instructions WHERE user_id = 'user1';
```

---

## Configuration

### Key Application Properties (`application.yaml`)

*   **Server Port**: `9917`
*   **Vector Store (Qdrant)**:
    *   `app.vectorstore.collection-name`: local collection name (default: `ascendai`)
    *   `app.vectorstore.size`: must match embedding dimension (default: `768` for `text-embedding-nomic-embed-text-v2-moe`)
    *   `application-cloud.yaml`: overrides to `ascendai-cloud` + `1536` (OpenAI `text-embedding-3-small`) to avoid dimension mismatches
*   **S3 Configuration**:
    *   `s3.endpoint`: `http://localhost:9070`
    *   `s3.bucket`: `knowledge-base`
*   **Data Source**: Postgres connection for metadata store.
*   **Unstructured API**: Base URL for the document parsing service.
*   **RAG**:
    *   `app.rag.enabled`: enables retrieval-gated soft-RAG
    *   `app.rag.similarity-threshold`: controls when retrieved context is injected
*   **Ingestion**:
    *   `app.ingestion.auto.enabled`: disabled by default to avoid startup latency/costs (use manual ingestion endpoint)

### MCP Client
*   `spring.ai.mcp.client`: Configured via `application.yaml` connections (Weather, AudioScribe, Web Tools).
