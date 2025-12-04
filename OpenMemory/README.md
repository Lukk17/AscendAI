# OpenMemory MCP Server for AscendAI

This directory contains the custom configuration and Docker setup for the **OpenMemory MCP Server**, which provides persistent memory capabilities for AI agents (specifically integrated with AnythingLLM via MCP).

## 🏗️ Architecture

The system consists of three main components running in Docker:

1.  **OpenMemory (MCP Server)**:
    -   Based on `mem0/openmemory-mcp`.
    -   Exposes an MCP (Model Context Protocol) endpoint for agents to store and retrieve memories.
    -   Uses **LM Studio** for LLM and Embedding tasks (via OpenAI-compatible API).
    -   Connects to Qdrant for vector storage.

2.  **Qdrant**:
    -   Vector database for storing memory embeddings.
    -   Persists data in the `qdrant_data` volume.

3.  **Mem0 Configurator**:
    -   A transient service that runs `configure_mem0.sh` on startup.
    -   Automatically configures the Mem0 API with the correct models and vector store settings.
    -   Ensures Qdrant collection is created with the correct dimensions (768).

## 🛠️ Customizations & Patches

The official `mem0` image was customized to support **LM Studio** and **Local Execution**:

*   **`Dockerfile.mem0mcp`**: Custom Dockerfile that applies the following patches:
    *   **`categorization.py`**: Patched to remove `response_format={"type": "json_object"}` (which causes errors with some local models) and to dynamically load the LLM model name from environment variables.
    *   **`patch_config.py`**: A script that modifies `app/routers/config.py` to allow extra configuration fields (like `embedding_model_dims`) which are stripped by default in the official image.
*   **`configure_mem0.sh`**: A startup script that:
    *   Waits for the OpenMemory API to be healthy.
    *   Pushes the configuration (LLM, Embedder, Vector Store) to the API.
    *   Resets the Qdrant collection if needed to ensure 768 dimensions (for `nomic-embed-text`).
*   **`docker-compose.yaml`**:
    *   Uses **YAML Anchors** (`x-common-env`) to define models in one place.
    *   Configures networking to allow containers to access LM Studio on the host (`host.docker.internal`).

## 🚀 How to Build and Run

### Prerequisites
*   **Docker Desktop** installed and running.
*   **LM Studio** running with the local server enabled (port 1234).
*   **Models Loaded in LM Studio**:
    *   LLM: `meta-llama-3.1-8b-instruct` (or similar).
    *   Embedder: `nomic-ai/nomic-embed-text-v1.5-GGUF`.

### Run Command
To build the custom image and start all services:

```powershell
cd OpenMemory
docker-compose up -d --build --force-recreate
```

*   `--build`: Rebuilds the custom `openmemory` image with our patches.
*   `--force-recreate`: Ensures containers are recreated with the latest configuration.

### Verify Status
Check if the services are healthy:
```powershell
docker ps
```
You should see `ascend-ai-openmemory-1` and `qdrant` as `healthy`.

## 📦 Pushing to Docker Hub

To push your custom working version to your Docker Hub repository, follow these steps:

1.  **Login to Docker Hub**:
    ```powershell
    docker login
    ```

2.  **Tag the Image**:
    It is recommended to tag with both a specific version (Semantic Versioning) and `latest`.
    Replace `your-username` with your Docker Hub username.
    ```powershell
    # Tag as v1.0.0
    docker tag openmemory-ascend-ai:latest your-username/openmemory-ascend-ai:v1.0.0
    
    # Tag as latest
    docker tag openmemory-ascend-ai:latest your-username/openmemory-ascend-ai:latest
    ```

3.  **Push the Images**:
    ```powershell
    docker push your-username/openmemory-ascend-ai:v1.0.0
    docker push your-username/openmemory-ascend-ai:latest
    ```

4.  **Using the Pushed Image**:
    Update `docker-compose.yaml` to use your pushed image instead of building locally:
    ```yaml
    services:
      openmemory:
        image: your-username/openmemory-ascend-ai:v1.0.0 # Pin to a specific version for stability
        # build: ... (comment out build section)
    ```

## 📝 Configuration

Model names are defined at the top of `docker-compose.yaml`:

```yaml
x-common-env: &common-env
  LLM_MODEL: meta-llama-3.1-8b-instruct
  EMBEDDER_MODEL: nomic-ai/nomic-embed-text-v1.5-GGUF
```

Change these values and rebuild if you switch models in LM Studio.
