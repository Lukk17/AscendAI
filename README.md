# AscendAI

This repository contains a multi-module AI orchestration platform built with Spring AI and the Model Context Protocol (MCP). It routes user prompts to multiple AI providers (LM Studio, OpenAI, Gemini, Anthropic, MiniMax) with per-request selection, extends LLM capabilities with external tools, and provides a RAG pipeline with semantic memory.

**Supported AI Providers:** LM Studio (local), OpenAI, Gemini, Anthropic, MiniMax — with per-request model selection.

---

## 🏗️ System Architecture

📐 **[Monorepo Architecture](docs/architecture/README.md)** — system overview, service interactions, deployment topology, ADRs.

📐 **[AscendAgent Internals](AscendAgent/docs/architecture/arc42/01-introduction-and-goals.md)** — detailed arc42, component diagrams, module-specific ADRs.

- **AscendAgent**: Spring Boot application — REST API, multi-provider AI, RAG pipeline, MCP tool integration.
- **AudioScribe**: MCP server for audio transcription (FastMCP/Python).
- **WeatherMCP**: MCP server for weather data (Spring Boot/Java).
- **AscendWebSearch**: MCP server for web search via SearXNG (FastMCP/Python).
- **AscendMemory**: Semantic memory service with REST API (FastAPI/Python).
- **External Prerequisites** (must be running before docker-compose):
  - **PostgreSQL**: Persistent metadata and chat history.
  - **Redis**: Chat history cache.
  - **Qdrant**: Vector database for RAG embeddings and semantic memory.
  - **MinIO**: S3-compatible object storage for document ingestion.
- **Support Services** (Dockerized):
  - **SearXNG**: Privacy-respecting meta search engine.
  - **FlareSolverr**: Cloudflare bypass proxy for web scraping.

---

## 🚀 Getting Started

### Prerequisites

- **Docker Desktop** (running)
- **Java 21**
- **PostgreSQL** (Active instance on port 5432)
- **Redis** (Active instance on port 6379)
- **Qdrant** (Active instance on ports 6333/6334)
- **MinIO** (Active instance on ports 9070/9071, credentials: `admin` / `password`)

### 1. Start Application Services

Ensure all external prerequisites above are running, then start application and support services (SearXNG, AscendMemory, AudioScribe, etc.):

```shell
docker-compose up -d
```

To rebuild and recreate all services:
```shell
docker compose up -d --build --force-recreate
```

To build and recreate the selected service:
```shell
docker compose up -d --no-deps --build --force-recreate <service name>
```
where:
`<service name>` is the name from `docker-compose.yaml` like `audio-scribe`
`--no-deps` - do not start linked services (database, redis, etc.)

Only to build (without recreation):
```shell
docker compose build --no-cache
```
where:
`--no-cache` - rebuild images without using of layer cache

### 2. Configure Database

Ensure your local PostgreSQL has a database named `ascend_ai`. The application is configured to connect with the following default credentials (update `AscendAgent/src/main/resources/application.yaml` if yours differ):

- **User**: `postgres`
- **Password**: `local`
- **Database**: `ascend_ai`

### 3. Run the AscendAgent

Navigate to the `AscendAgent` directory and run the application:

```bash
cd AscendAgent
./gradlew bootRun
```

The application will automatically:

- Connect to MinIO.
- Create the `knowledge-base` bucket if it doesn't exist.
- Initialize the necessary database tables (`INT_METADATA_STORE`, etc.).

---

## 🌐 HTTP AscendAgent API

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

| Service             | Port            | Default Credentials  | Description                 |
| :------------------ | :-------------- | :------------------- | :-------------------------- |
| **AscendAgent**    | `9917`          | -                    | Main API Gateway            |
| **AudioScribe**     | `7017`          | -                    | MCP — Audio Transcription   |
| **WeatherMCP**      | `9998`          | -                    | MCP — Weather Data          |
| **AscendWebSearch** | `7021`          | -                    | MCP — Web Search            |
| **AscendMemory**    | `7020`          | -                    | REST/MCP — Semantic Memory  |
| **PaddleOCR**       | `7022`          | -                    | MCP — OCR Service           |
| **Docling Serve**   | `5001`          | -                    | Document Conversion         |
| **Unstructured API**| `9080`          | -                    | Document Parsing for RAG    |
| **MinIO API**       | `9070`          | `admin` / `password` | S3 API Endpoint             |
| **MinIO Console**   | `9071`          | `admin` / `password` | Web UI for File Management  |
| **Qdrant**          | `6333` / `6334` | -                    | Vector Database (HTTP/gRPC) |
| **Redis**           | `6379`          | -                    | Cache                       |
| **SearXNG**         | `9020`          | -                    | Meta Search Engine          |
| **FlareSolverr**    | `8191`          | -                    | Cloudflare Bypass           |
| **PostgreSQL**      | `5432`          | `postgres` / `local` | Metadata Storage            |

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

MinIO runs as an external prerequisite. Data persistence depends on your MinIO installation (local or cloud-managed S3).

---

## �📄 Adding Documents for RAG

To add documents (Markdown, PDF, DOCX) to your RAG pipeline, you need to upload them to the `knowledge-base` bucket in MinIO.

### Option 1: MinIO Console (Web UI)

1.  Open [http://localhost:9071](http://localhost:9071).
2.  Login with default credentials: `admin` / `password`.
3.  Click on **Buckets** in the left menu.
4.  Select `knowledge-base`.
    - _If it doesn't exist, the AscendAgent will create it on startup, or you can create it manually._
5.  Click **Object Browser** -> **Upload**.
6.  Select your file(s) or folder(s).
    - **Markdown**: Files with `.md` (best if from Obsidian).
    - **Documents**: PDFs, DOCX, etc. (processed via Unstructured API).

### Option 2: CLI (curl) via AscendAgent

You can directly upload files using the AscendAgent's API, which will automatically route them to the correct folder (`obsidian/` or `documents/`):

```bash
# Example: Uploading a Markdown file
curl -X POST -F "file=@width_test.md" http://localhost:9917/api/ingestion/upload
```

_Note: Make sure the file exists in your current directory._

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

The system uses Qdrant for two distinct features:

1. **RAG (AscendAgent)**: Uses `ascendai-768` (for Gemini/LM Studio) or `ascendai-1536` (for OpenAI) depending on the active embedding dimensions.
2. **Semantic Memory (AscendMemory / Mem0)**: Uses `ascend_memory_768` (for lmstudio/gemini, 768 dims) or `ascend_memory_1536` (for openai, 1536 dims) depending on the embedding provider.

**Delete Entire Collection (Reset Memory):**
To completely wipe all vector data for a given collection:

```bash
curl -X DELETE "http://localhost:6333/collections/ascendai-768"
curl -X DELETE "http://localhost:6333/collections/ascendai-1536"
curl -X DELETE "http://localhost:6333/collections/ascend_memory_768"
curl -X DELETE "http://localhost:6333/collections/ascend_memory_1536"
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

- **URL**: [http://localhost:6333/dashboard](http://localhost:6333/dashboard)
- You can browse collections, view stored vectors, and verify data ingestion visually without needing extra containers.

### 3. Resetting Ingestion History (PostgreSQL)

To force the system to re-process files, you must remove their entries from the metadata store.

**Database Details:**

- **Database**: `ascend_ai`
- **Schema**: `public`
- **Table**: `int_metadata_store`

**Option A: Clear History for a Single File (Granular)**
If you want to re-ingest a specific file (e.g., `test.md`):

```sql
DELETE FROM public.int_metadata_store
WHERE metadata_key LIKE '%test.md'
   OR metadata_key LIKE '%test.md';
```

_(Note: Keys often include prefixes like `s3-metadata` or `local-fs-metadata`)_

**Option B: Clear ALL History (Full Reset)**
To force the system to re-process **everything**:

```sql
TRUNCATE TABLE public.int_metadata_store;
```

**After running either command, restart the AscendAgent.**

### 4. Resetting Chat History (Redis & PostgreSQL)

The AscendAgent maintains your chat context in two places:

1.  **Short-Term History (Redis)**: This is the active context window sent to the LLM during conversational interactions.
2.  **Long-Term History (PostgreSQL)**: The system archives all interactions to the database for persistent auditing and user analytics.

**Clear Active Context (Redis):**
To completely wipe the active memory for all sessions, flush the Redis cached keys:

1. Connect to Redis (running externally):
   ```bash
   redis-cli
   ```
2. Flush all keys:
   ```bash
   FLUSHALL
   ```

**Clear Archived History (PostgreSQL):**
If you want to completely erase the persistent database records of previous chats from the system:

1. Connect to the PostgreSQL database (`ascend_ai`).
2. Run the following command:
   ```sql
   DELETE FROM chat_history;
   ```

---

### Agent standards import

To import the central AI standards into this project without overwriting existing files, we use Git Selective Checkout. 

This approach extracts only the required AI folders and template files directly into the project root.

To protect the central repository, we configure the remote as a read-only source in your local workspace by setting the push URL to an invalid address. 

This ensures you can pull updates from the central repository, but Git will block any accidental pushes of your project-specific changes back to the global standards.

### Step 1: Initial Setup

Enable symlink support in Git:
Globally
```shell
git config --global core.symlinks true
```
Locally for this repository only
```shell
git config core.symlinks true
```

Run these commands in the root of this project to add the remote, disable pushing, and extract the specific payload files into your workspace.

```bash
git remote add agent-standards https://github.com/Lukk17/agent-standards
```

```bash
git remote set-url --push agent-standards no_push
```

```bash
git fetch agent-standards
```

```bash
git checkout agent-standards/master -- .agents .claude .kilocode .opencode .codex AGENTS.md.example kilo.jsonc.example opencode.json.example
```

```bash
git commit -m "Import central agent-standards (.agents and .claude)"
```

### Step 2: Pulling Future Updates

When the central standards repository is updated, pull the latest files into this project by running the following commands.

```bash
git fetch agent-standards
```

```bash
git checkout agent-standards/master -- .agents .claude
```

```bash
git commit -m "Update AI standards from central repository"
```

---

### OpenSpec Integration

[OpenSpec](https://github.com/Fission-AI/OpenSpec) is a spec-driven development framework that installs skills and commands into each agent's native directories.

#### How the symlinks work with OpenSpec

The `.kilocode/skills/`, `.opencode/skills/`, and `.codex/skills/` directories are all symlinked to `.agents/skills/`. When `openspec init` writes skills to any of these directories, they land in `.agents/skills/` — the canonical location already read by all agents.

Commands are tool-specific (different formats per agent) and cannot be centralized. OpenSpec creates them in each tool's native commands directory, which is expected and correct.
#### Using OpenSpec in a project that imports agent-standards

After running Step 1 above, initialize OpenSpec in your project:

```bash
# Install OpenSpec globally
npm install -g @fission-ai/openspec@latest

# Initialize with all agents
# Skills land in .agents/skills/ via existing symlinks
# Commands are created in each tool's native commands directory
openspec init --tools "claude,kilocode,opencode,codex"
```

What `openspec init` creates:

```text
openspec/
  config.yaml              # OpenSpec project config
  specs/                   # Living documentation of your system
  changes/                 # Active feature work
    archive/               # Completed changes

# Skills (via symlinks, all land in .agents/skills/):
.agents/skills/openspec-workflow/SKILL.md
.agents/skills/openspec-specs/SKILL.md

# Commands (tool-specific, not symlinked):
.claude/commands/opsx/propose.md
.kilocode/workflows/opsx-propose.md
.opencode/commands/opsx-propose.md
```

Restart IDE and terminal after openspec initialization.

#### OpenSpec tool directories reference

| Tool | Skills written to | Commands written to |
|---|---|---|
| Claude Code | `.claude/skills/openspec-*/` -> `.agents/skills/` | `.claude/commands/opsx/*.md` |
| Kilo Code | `.kilocode/skills/openspec-*/` -> `.agents/skills/` | `.kilocode/workflows/opsx-*.md` |
| OpenCode | `.opencode/skills/openspec-*/` -> `.agents/skills/` | `.opencode/commands/opsx-*.md` |
| Codex | `.codex/skills/openspec-*/` -> `.agents/skills/` | `$CODEX_HOME/prompts/opsx-*.md` |

#### Command Syntax Variations

Because the AI coding landscape is fragmented, OpenSpec generates files for two different architectures. Depending on your specific agent UI, your commands will appear in one of two ways:
* Standalone Markdown Commands: Agents that read flat files will show commands with extensions in their dropdowns (e.g., /opsx-propose.md).
* Agent Skills: Agents that parse semantic SKILL.md metadata or have native integration will use standard slash syntax (e.g., /opsx:propose).

Use the syntax that appears in your agent's autocomplete menu.

#### The Full OpenSpec Workflow

Once initialized, invoke OpenSpec skills from your agent using the full artifact-driven lifecycle:

#### 0. Run Coding Agent
You need to start coding agent first - for example, by running in terminal:
```shell
claude
```
#### 1. Propose the change
Use multiline prompts to include logs or detailed context.
Inside coding agent shell run your specific command variation:

```text
/opsx:propose add dark mode support
```

```text
/opsx-propose.md add dark mode support
```
The agent creates the proposal, design, and implementation tasks under `openspec/changes/`.

#### 2. Apply the code
Review the generated `tasks.md` by manually editing md files or just telling agent what is wrong with it.

After plan approval agent can start implementation:

```text
/opsx:apply
```

```text
/opsx-apply.md
```
The agent writes the code and checks off the boxes in your `tasks.md`.

#### 3. Verify and refine
If bugs occur or tests fail, pass the logs back to refine the implementation.

```text
/opsx:verify The toggle button is invisible on mobile. Fix it.
```

```text
/opsx-verify.md The toggle button is invisible on mobile. Fix it.
```

#### 4. Archive the change
Once the code is working and tested, merge the documentation.

```text
/opsx:archive
```

```text
/opsx-archive.md
```
The agent merges the delta specs into `openspec/specs/` and moves the change folder to `openspec/changes/archive/`.
