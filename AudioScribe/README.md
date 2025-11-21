# AudioScribe

AudioScribe is a versatile, dynamic speech-to-text service supporting local, OpenAI, and Hugging Face models. The transcription model is chosen **per-request**, allowing for maximum flexibility.

---

## Table of Contents

*   [API Documentation](#api-documentation)
*   [Prerequisites](#prerequisites)
*   [Configuration (Environment Variables)](#configuration-environment-variables)
*   [Running the Service](#running-the-service)
    *   [Standard Python App](#running-as-a-standard-python-app-without-docker)
    *   [Docker](#running-with-docker-recommended)
*   [Making API Requests](#making-api-requests)
*   [MCP Server Mode](#mcp-server-mode)
    *   [Using Audio URIs](#using-audio-uris-in-mcp)
*   [Dependencies](#dependencies)
*   [Troubleshooting](#troubleshooting)

---

## API Documentation

The REST API is self-documenting via Swagger and Redoc. While the server is running, you can access:

*   **Swagger UI**: [http://localhost:7017/docs](http://localhost:7017/docs)
*   **Redoc**: [http://localhost:7017/redoc](http://localhost:7017/redoc)

---

## Prerequisites

*   **Python 3.11**
*   **Nvidia CUDA**
    * https://developer.nvidia.com/cuda-12-6-0-download-archive
    * https://developer.nvidia.com/cudnn-downloads
*   **PyTorch**
    * https://pytorch.org/get-started/locally/ 
*   **ffmpeg**: Required for audio processing.
    *   Linux: `sudo apt install ffmpeg`
    *   Windows: `choco install ffmpeg`

Python default packages repository:
https://pypi.org/

---

## Configuration (Environment Variables)

For the service to function, certain environment variables must be set.  
For local development, it is best practice to set these in your operating system's environment variables,  
as they include secrets and user-specific paths.

*   `OPENAI_API_KEY`: **(Secret)** Your secret key for the OpenAI API.
    https://platform.openai.com/settings/organization/api-keys
*   `HF_TOKEN`: **(Secret)** Your Hugging Face token. Required for downloading models and for using the Hugging Face API provider.
    https://huggingface.co/settings/tokens
*   `HF_HOME`: **(Local Path)** The directory where Hugging Face will cache downloaded models. This prevents re-downloading large models every time.

**Example `HF_HOME` and Model Parameter:**

If you set your `HF_HOME` environment variable to `D:\Development\AI\hf-cache`,  
the `transformers` library will automatically use this folder.  
When you make an API request, you still use the public model *identifier* in the `model` field.  
The library handles the mapping.

*   **Environment Variable:** `HF_HOME=D:\Development\AI\hf-cache`
*   **API `model` parameter:** `openai/whisper-large-v3`

---

## Running the Service

### Running as a standard Python App (without Docker)

This method is suitable for local development.  
Ensure you have set the **environment variables** mentioned above.

1.  **Install Dependencies:**
    In `./AudioScribe` directory in terminal:

    ```shell
    python -m venv .venv
    ```
    Activate the virtual environment
    Windows
    ```PowerShell
    .\.venv\Scripts\activate.ps1
    ```
    Unix
    ```shell
    ./.venv/bin/activate
    ```
    Install PyTorch separately from its specific index
    ```shell
    pip install --index-url https://download.pytorch.org/whl/cu121 "torch==2.5.1+cu121"
    ```
    Install all other application requirements
    ```shell
    pip install -r pytorch-requirements.txt -r requirements.txt
    ```
    without cache:
    ```shell
    pip install --no-cache-dir -r pytorch-requirements.txt -r requirements.txt
    ```

2.  **Run the Uvicorn Server:**
    ```shell
    uvicorn main:app --host 0.0.0.0 --port 7017 --reload
    ```

### Running with Docker (Recommended)

This is the recommended method for a stable deployment.

**1. Build the Docker image:**
```shell
# Build the main image for the REST API
docker build -t audio-scribe:latest .

# Or, build the image for the MCP server
docker build -f Dockerfile.mcp -t audio-scribe-mcp:latest .
```

**2. Run the container:**

**For Linux/macOS:**
```shell
docker run -d \
  --name audio-scribe \
  --gpus all \
  -p 7017:7017 \
  -e OPENAI_API_KEY="sk-..." \
  -e HF_TOKEN="hf_..." \
  -e HF_HOME=/hf-cache \
  -v ~/hf-cache:/hf-cache \
  audio-scribe:latest
```

**For Windows (PowerShell):**
```PowerShell
docker run -d `
  --name audio-scribe `
  --gpus all `
  -p 7017:7017 `
  -e OPENAI_API_KEY="sk-..." `
  -e HF_TOKEN="hf_..." `
  -e HF_HOME=/hf-cache `
  -v "D:/path/to/your/hf-cache:/hf-cache" `
  audio-scribe:latest
```
*   `--gpus all`: **Required** for local transcription to run on the GPU.
*   `-v ...:/hf-cache`: **Recommended**. Mounts a local directory to cache models.

---

## Making API Requests

### REST Client
For testing and examples, you can use the included `mcp_requests.http` file.
*   [mcp_requests.http](mcp_requests.http): Contains ready-to-use HTTP requests for the REST Client extension in VS Code. It covers both standard API calls and MCP protocol interactions.

### API Requests
You specify the model and other parameters in the body of your `POST` request.

### Local Transcription
Uses `faster-whisper` and requires a pre-converted model format.
*   **model**: (e.g., `Systran/faster-whisper-large-v3`)
*   **language**: (optional, e.g., `en`, `pl`)
*   **with_timestamps**: (optional, `true` or `false`, defaults to `true`)

**Example `curl` (Linux/macOS):**
```shell
curl -X POST "http://localhost:7017/api/v1/transcribe/local" \
  -H "Content-Type: multipart/form-data" \
  -F "file=@$HOME/Desktop/audio.wav" \
  -F "model=Systran/faster-whisper-large-v3" \
  -F "language=en" \
  -F "with_timestamps=false"
```

**Example `curl` (Windows PowerShell):**
```powershell
curl -X POST "http://localhost:7017/api/v1/transcribe/local" `
  -H "Content-Type: multipart/form-data" `
  -F "file=@$env:USERPROFILE\Desktop\audio.wav" `
  -F "model=Systran/faster-whisper-large-v3" `
  -F "language=en" `
  -F "with_timestamps=false"
```

### OpenAI Transcription
*   **model**: (e.g., `whisper-1`)
*   **language**: (optional, e.g., `en`, `pl`)

**Example `curl` (Linux/macOS):**
```shell
curl -X POST "http://localhost:7017/api/v1/transcribe/openai" \
  -H "Content-Type: multipart/form-data" \
  -F "file=@$HOME/Desktop/audio.wav" \
  -F "model=whisper-1" \
  -F "language=en"
```

**Example `curl` (Windows PowerShell):**
```powershell
curl -X POST "http://localhost:7017/api/v1/transcribe/openai" `
  -H "Content-Type: multipart/form-data" `
  -F "file=@$env:USERPROFILE\Desktop\audio.wav" `
  -F "model=whisper-1" `
  -F "language=en"
```

### Hugging Face Transcription
*   **model**: (e.g., `openai/whisper-large-v3`)
*   **hf_provider**: (optional, defaults to `hf-inference`)

**Example `curl` (Linux/macOS):**
```shell
curl -X POST "http://localhost:7017/api/v1/transcribe/hf" \
  -H "Content-Type: multipart/form-data" \
  -F "file=@$HOME/Desktop/audio.wav" \
  -F "model=openai/whisper-large-v3"
```

**Example `curl` (Windows PowerShell):**
```powershell
curl -X POST "http://localhost:7017/api/v1/transcribe/hf" `
  -H "Content-Type: multipart/form-data" `
  -F "file=@$env:USERPROFILE\Desktop\audio.wav" `
  -F "model=openai/whisper-large-v3"
```

---

## MCP Server Mode

The MCP server runs on a separate port (default `7016`) to avoid conflicts with the main API when running locally.
When using Docker, it can be mapped to any port.

**Exposed MCP Tools:**
*   `health()`
*   `transcribe_local(audio_uri: str, model: str, language: str, with_timestamps: bool)`
*   `transcribe_openai(audio_uri: str, model: str, language: str)`
*   `transcribe_hf(audio_uri: str, model: str, hf_provider: str)`

### How to run (both transports enabled):

```shell
uvicorn mcp_server:app --host 0.0.0.0 --port 7016
```

Streamable HTTP (bidirectional over HTTP):
  - Endpoint: POST http://localhost:7016/mcp
  - Headers:  Content-Type: application/json
              Accept: application/json, text/event-stream

SSE transport (server-sent events + POST messages):
  - Stream:   GET  http://localhost:7016/sse-root/sse
              Accept: text/event-stream
  - Messages: POST http://localhost:7016/sse-root/messages/
              Headers: Content-Type: application/json
              Note: The messages path includes a required `session_id` query param
                    provided by the server in the first SSE event named "endpoint".

### Example MCP Client Configurations

To use these tools, configure your AI-powered editor or client to connect to the running server's URL.

**For Claude Desktop / Generic Clients:**
```json
{
  "mcpServers": {
    "audio-scribe": {
      "url": "http://localhost:7016"
    }
  }
}

### Using Audio URIs in MCP

The MCP tools accept an `audio_uri` argument, which supports both local files and HTTP(S) URLs.

#### 1. Local Files (`file://`)
To use a file on the server's local filesystem, use the `file://` scheme.
*   **Windows**: `file:///C:/Users/User/Desktop/audio.wav`
*   **Linux/macOS**: `file:///home/user/audio.wav`
*   **Docker**: `file:///audio/audio.wav` (ensure the file is mounted into the container)

#### 2. HTTP/HTTPS URLs (`http://`, `https://`)
You can also provide a URL to an audio file hosted on a web server. The MCP server will download it to a temporary file for processing.

**Example: Serving files locally with `http-server`**

If you have audio files on your local machine and want to expose them to the MCP server (especially if running in Docker or a different environment), you can use a simple HTTP server.

1.  **Install `http-server`** (requires Node.js):
    ```shell
    npm install -g http-server
    ```

2.  **Run the server** in the directory containing your audio files (e.g., parent of `audio` folder):
    ```shell
    http-server -p 9999
    ```

3.  **Access the file**:
    If your file is at `./audio/test.wav` relative to where you ran the command, the URI will be:
    `http://localhost:9999/audio/test.wav` (or use your machine's LAN IP if accessing from a Docker container).
```

---

## Dependencies

To update dependency versions in `requirements.txt` excluding ones which should be manually updated,  
due to torch compatibility  
Windows:
```PowerShell
pip freeze | Select-String -NotMatch -Pattern '^(torch|numpy|sympy|networkx|mpmath|filelock|fsspec|jinja2|typing_extensions)$' > requirements.txt
```
Unix:
```shell
pip freeze | grep -v -E '^(torch|numpy|sympy|networkx|mpmath|filelock|fsspec|jinja2|typing_extensions)$' > requirements.txt
```

---
## Troubleshooting

### Checking lib versions

#### nvidia drivers
```shell
nvidia-smi
```
#### torch
```python
import torch
print(torch.cuda.is_available())
```

#### cudnn

```python
import torch
print(torch.backends.cudnn.version())
```

### Hugging Face Symlinks Warning on Windows

When running the application on Windows, you may see a `UserWarning` about symlinks not being supported.

**Why it happens:** The `huggingface_hub` library uses symbolic links by default to efficiently manage its cache. Standard user accounts on Windows cannot create symlinks without special permissions. This is a warning, not an error, and the cache will still function, but it may take up more disk space.

**Solution 1 (Recommended): Set Environment Variable**

The easiest way to resolve this is to disable the warning by setting an environment variable:
```
HF_HUB_DISABLE_SYMLINKS_WARNING=1
```

**Solution 2: Enable Developer Mode**

Alternatively, you can enable Developer Mode on Windows to allow your user account to create symlinks.
1.  Open **Settings**.
2.  Go to **System** > **Advanced** > **For developers**.
3.  Toggle **Developer Mode** to **On**.
You may need to restart your terminal or IDE for the change to take effect.

---

### Reinstalling python dependencies
Terminal in your activated virtual environment.  

This creates a temporary list of everything that's currently installed.
```shell
pip freeze > temp_requirements.txt
```
Now, use that list to uninstall everything.  
The -y flag automatically confirms all the uninstallations so you don't have to do it one by one.
```shell
pip uninstall -y -r temp_requirements.txt
```
Then reinstall:
```shell
pip install --no-cache-dir -r pytorch-requirements.txt -r requirements.txt
```
Now you can remove `temp_requirements.txt` file.
